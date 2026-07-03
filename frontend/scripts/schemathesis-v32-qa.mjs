#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v32-schemathesis-qa");

const ownOptionsWithValue = new Set([
  "--repeat",
  "--interval-ms",
  "--artifact-root",
  "--timeout-ms",
  "--from-report",
  "--max-examples",
  "--seed",
]);

const safeReadRouteCandidates = [
  "/api/health",
  "/api/modules",
  "/api/leads",
  "/api/outbound/overview",
  "/api/outbound/tasks",
  "/api/outbound/records",
  "/api/outbound/scripts",
  "/api/outbound/recall-rules",
  "/api/outbound/live",
  "/api/outbound/telephony/config",
  "/api/outbound/telephony/health",
  "/api/outbound/telephony/preflight",
  "/api/outbound/realtime/pipeline",
  "/api/outbound/realtime/live-events",
  "/api/collections/tasks",
  "/api/collections/runs",
  "/api/collections/raw-records",
  "/api/direct-messages/overview",
  "/api/direct-messages/config",
  "/api/direct-messages/accounts",
  "/api/direct-messages/platform-configs",
  "/api/direct-messages/templates",
  "/api/direct-messages/tasks",
  "/api/direct-messages/conversations",
  "/api/direct-messages/messages",
  "/api/direct-messages/intercepts/overview",
  "/api/direct-messages/intercepts/sources",
  "/api/direct-messages/intercepts/comments",
  "/api/intent/overview",
  "/api/intent/customers",
  "/api/intent/events",
  "/api/intent/work-orders",
  "/api/voice/overview",
  "/api/voice/provider/status",
  "/api/voice/system-voices",
  "/api/voice/profiles",
  "/api/voice/samples",
  "/api/voice/clone-records",
  "/api/voice/usage-records",
  "/api/reports/overview",
  "/api/reports/channels",
  "/api/reports/sales",
  "/api/settings/overview",
  "/api/settings/items",
  "/api/settings/audit-logs",
];

const sideEffectProbeRoutes = [
  "/direct-messages/conversations",
  "/direct-messages/messages",
  "/reports/exports",
  "/collections/runs",
  "/collections/raw-records",
  "/outbound/records",
  "/voice/training-jobs",
];

const dangerousRoutePatterns = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/sync-replies\b/,
  /\/api\/direct-messages\/accounts\/[^/]+\/(?:login-window|login-session)\b/,
  /\/api\/direct-messages\/intercepts\/sources\/[^/]+\/(?:sync|browser-dm-actions)\b/,
  /\/api\/collections\/tasks\/[^/]+\/run\b/,
  /\/api\/voice\/.*(?:preview|training-jobs)/,
  /\/api\/reports\/exports\b/,
  /\/api\/settings\/items\/[^/]+\b/,
];

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    timeoutMs: 180000,
    fromReport: "",
    maxExamples: 1,
    seed: 32032,
    json: false,
    batch: false,
    skipV31: false,
    fullChain: false,
    keep: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 1000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--timeout-ms") options.timeoutMs = Math.max(10000, Number(next) || 180000);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      if (arg === "--max-examples") options.maxExamples = Math.max(1, Number(next) || 1);
      if (arg === "--seed") options.seed = Number(next) || 32032;
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--skip-v31") {
      options.skipV31 = true;
    } else if (arg === "--full-chain") {
      options.fullChain = true;
    } else if (arg === "--keep") {
      options.keep = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      options.passThrough.push(arg);
      if (next && !next.startsWith("--")) {
        options.passThrough.push(next);
        index += 1;
      }
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V32 Schemathesis OpenAPI property QA

Default: preserve V31 OpenAPI model gate, then run safe authenticated Schemathesis GET contract/property checks.
  npm run qa:v32 -- --repeat 2

Run only V32 against a fresh isolated backend:
  npm run qa:v32 -- --skip-v31 --max-examples 1

Use a prior V31 report:
  npm run qa:v32 -- --from-report .playwright-cli/v31-openapi-model-qa/<run>/report.json

Run the full nested V31->V30 chain instead of the compact V31 gate:
  npm run qa:v32 -- --full-chain
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/.test(normalized);
}

function sanitizeText(text) {
  return String(text || "")
    .replace(/Authorization:\s*Bearer\s+[A-Za-z0-9._-]+/gi, "Authorization: Bearer [redacted]")
    .replace(/\bBearer\s+[A-Za-z0-9._-]+/g, "Bearer [redacted]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[token-redacted]");
}

function redact(value, key = "") {
  if (typeof value === "string") {
    if (isSensitiveKey(key)) return value ? "[redacted]" : "";
    return sanitizeText(value)
      .replace(/\b1[3-9]\d{9}\b/g, (match) => `${match.slice(0, 3)}****${match.slice(-4)}`);
  }
  if (Array.isArray(value)) return value.map((item) => redact(item, key));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([itemKey, item]) => [itemKey, redact(item, itemKey)]));
  }
  return value;
}

function parseJsonOutput(stdout) {
  const text = String(stdout || "").trim();
  if (!text) throw new Error("empty JSON output");
  try {
    return JSON.parse(text);
  } catch {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start >= 0 && end > start) return JSON.parse(text.slice(start, end + 1));
    throw new Error(`unable to parse JSON output: ${text.slice(0, 300)}`);
  }
}

function runV31(options, artifactDir) {
  const args = [
    "scripts/openapi-model-v31-qa.mjs",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    artifactDir,
  ];
  if (!options.fullChain) args.push("--skip-v30");
  if (options.batch) args.push("--batch");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 260 * 1024 * 1024,
    timeout: 65 * 60 * 1000,
  });

  let report = null;
  let parseError = null;
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
    const reportPath = result.stdout?.match(/Report:\s*(.+report\.json)/)?.[1]?.trim();
    if (reportPath) {
      try {
        report = JSON.parse(fsSync.readFileSync(reportPath, "utf8"));
        parseError = null;
      } catch (readError) {
        parseError = `${parseError}; report file read failed: ${readError.message}`;
      }
    }
  }

  return {
    command: `${process.execPath} ${args.join(" ")}`,
    artifactDir,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: sanitizeText(result.stdout?.slice(-5000) || ""),
    stderrTail: sanitizeText(result.stderr?.slice(-5000) || ""),
  };
}

function makeCorrelation() {
  const random = Math.random().toString(16).slice(2, 18).padEnd(16, "0");
  const runId = `v32-schemathesis-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V32`,
  };
}

function correlationHeaders(correlation) {
  if (!correlation) return {};
  return {
    "X-AI-ACQ-QA-Correlation-Id": correlation.runId,
    "X-Request-ID": correlation.runId,
    traceparent: correlation.traceparent,
    baggage: correlation.baggage,
  };
}

async function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close(() => (port ? resolve(port) : reject(new Error("No free port assigned"))));
    });
    server.on("error", reject);
  });
}

async function waitForUrl(url, timeoutMs, expectText = "") {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (response.ok && (!expectText || text.includes(expectText))) return { status: response.status, text };
      lastError = new Error(`HTTP ${response.status}: ${text.slice(0, 160)}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown"}`);
}

async function runCommand(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}\n${stdout}\n${stderr}`));
    });
  });
}

async function backendPython() {
  const venvPython = path.join(BACKEND_ROOT, ".venv", "bin", "python");
  try {
    await fs.access(venvPython);
    return venvPython;
  } catch {
    return "python3";
  }
}

async function schemathesisBinary() {
  const venvBinary = path.join(BACKEND_ROOT, ".venv", "bin", "schemathesis");
  try {
    await fs.access(venvBinary);
    return venvBinary;
  } catch {
    return "schemathesis";
  }
}

function startProcess(command, args, options) {
  return spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    detached: true,
    stdio: ["ignore", options.stdout, options.stderr],
  });
}

function stopProcess(child) {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    try {
      process.kill(child.pid, "SIGTERM");
    } catch {
      // Already stopped.
    }
  }
}

function addCheck(report, name, status, detail, data = undefined) {
  report.schemathesisJourney.checks.push({ name, status, detail, data });
}

function recordApiResponse(report, method, pathName, status, headers = {}, ok = false, body = null) {
  report.schemathesisJourney.evidence.apiTraffic.push({
    method,
    path: pathName,
    status,
    ok,
    bodyType: Array.isArray(body) ? "array" : body === null ? "null" : typeof body,
    echoedCorrelationId: headers["x-ai-acq-qa-correlation-id"] || headers["x-request-id"] || "",
    traceparent: headers.traceparent || "",
    correlationEchoed: report.correlation?.runId ? headers["x-ai-acq-qa-correlation-id"] === report.correlation.runId : null,
    traceparentEchoed: report.correlation?.traceparent ? headers.traceparent === report.correlation.traceparent : null,
  });
}

async function apiRequest(report, baseUrl, pathName, options = {}) {
  const method = options.method || "GET";
  const response = await fetch(`${baseUrl}${pathName}`, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(report.schemathesisJourney.state.accessToken ? { Authorization: `Bearer ${report.schemathesisJourney.state.accessToken}` } : {}),
      ...correlationHeaders(report.correlation),
      ...options.headers,
    },
    method,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const headers = Object.fromEntries(response.headers.entries());
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text.slice(0, 1000) };
  }
  recordApiResponse(report, method, pathName, response.status, headers, response.ok, body);
  return { ok: response.ok, status: response.status, headers, body };
}

function countPayload(body) {
  if (Array.isArray(body)) return body.length;
  if (!body || typeof body !== "object") return null;
  if (Array.isArray(body.items)) return body.items.length;
  if (Array.isArray(body.records)) return body.records.length;
  if (Array.isArray(body.data)) return body.data.length;
  if (typeof body.total === "number") return body.total;
  if (typeof body.count === "number") return body.count;
  return null;
}

async function collectSideEffectCounts(report, apiBase) {
  const counts = {};
  for (const route of sideEffectProbeRoutes) {
    try {
      const response = await apiRequest(report, apiBase, route);
      counts[route] = {
        status: response.status,
        ok: response.ok,
        count: response.ok ? countPayload(response.body) : null,
      };
    } catch (error) {
      counts[route] = { status: "error", ok: false, count: null, error: error.message };
    }
  }
  return counts;
}

function countsUnchanged(before, after) {
  for (const route of sideEffectProbeRoutes) {
    const previous = before?.[route];
    const next = after?.[route];
    if (!previous || !next) return false;
    if (previous.ok !== next.ok) return false;
    if (previous.count !== null && next.count !== null && previous.count !== next.count) return false;
  }
  return true;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function selectSafeReadOperations(openapi) {
  const paths = openapi?.paths || {};
  const selectedRoutes = safeReadRouteCandidates.filter((route) => Boolean(paths[route]?.get));
  return {
    routes: selectedRoutes,
    pathRegex: selectedRoutes.length ? `^(${selectedRoutes.map(escapeRegExp).join("|")})$` : "$^",
    rejectedCandidates: safeReadRouteCandidates.filter((route) => !paths[route]?.get),
    dangerousCandidateMatches: selectedRoutes.filter((route) => dangerousRoutePatterns.some((pattern) => pattern.test(route))),
    totalGetOperations: Object.entries(paths).filter(([, operations]) => Boolean(operations.get)).length,
  };
}

function buildSafeGetOpenapi(openapi, safeRoutes, origin) {
  return {
    ...openapi,
    info: {
      ...(openapi.info || {}),
      title: `${openapi.info?.title || "AI ACQ"} V32 Safe GET Contract`,
    },
    servers: [{ url: origin }],
    paths: Object.fromEntries(
      safeRoutes.map((route) => [
        route,
        {
          get: openapi.paths[route].get,
        },
      ]),
    ),
  };
}

function redactedCommand(args) {
  return args.map((arg) => sanitizeText(arg)).join(" ");
}

async function runSchemathesis(report, options, origin, artifactDir) {
  const binary = await schemathesisBinary();
  const versionResult = spawnSync(binary, ["--version"], {
    cwd: REPO_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
  });
  const version = sanitizeText(`${versionResult.stdout || ""}${versionResult.stderr || ""}`.trim());
  report.schemathesisJourney.state.schemathesis.version = version;
  report.schemathesisJourney.state.schemathesis.binary = binary;
  addCheck(report, "Schemathesis CLI: 可执行", versionResult.status === 0 ? "pass" : "fail", version || `exit=${versionResult.status}`);

  const ndjsonPath = report.schemathesisJourney.artifacts.ndjson;
  const reportDir = report.schemathesisJourney.artifacts.schemathesisReportDir;
  await mkdirp(reportDir);
  const args = [
    "run",
    report.schemathesisJourney.artifacts.filteredOpenapiSchema,
    "--url",
    origin,
    "--phases",
    "coverage,fuzzing",
    "--checks",
    "not_a_server_error,status_code_conformance,content_type_conformance,response_schema_conformance",
    "--mode",
    "positive",
    "--max-examples",
    String(options.maxExamples),
    "--seed",
    String(options.seed),
    "--generation-deterministic",
    "--generation-with-security-parameters",
    "false",
    "--workers",
    "1",
    "--request-timeout",
    "5",
    "--max-response-time",
    "10",
    "--max-failures",
    "1",
    "--report",
    "ndjson",
    "--report-dir",
    reportDir,
    "--report-ndjson-path",
    ndjsonPath,
    "--output-sanitize",
    "true",
    "--output-truncate",
    "true",
    "--no-color",
    "-H",
    `Authorization:Bearer ${report.schemathesisJourney.state.accessToken}`,
    "-H",
    `X-AI-ACQ-QA-Correlation-Id:${report.correlation.runId}`,
    "-H",
    `X-Request-ID:${report.correlation.runId}`,
    "-H",
    `traceparent:${report.correlation.traceparent}`,
    "-H",
    `baggage:${report.correlation.baggage}`,
  ];

  const startedAt = Date.now();
  const result = spawnSync(binary, args, {
    cwd: REPO_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 120 * 1024 * 1024,
    timeout: Math.max(options.timeoutMs, 60000),
  });
  const stdout = sanitizeText(result.stdout || "");
  const stderr = sanitizeText(result.stderr || "");
  await fs.writeFile(report.schemathesisJourney.artifacts.stdoutLog, stdout, "utf8");
  await fs.writeFile(report.schemathesisJourney.artifacts.stderrLog, stderr, "utf8");

  const ndjsonExists = await pathExists(ndjsonPath);
  let ndjsonLines = 0;
  if (ndjsonExists) {
    const text = await fs.readFile(ndjsonPath, "utf8");
    ndjsonLines = text.split(/\r?\n/).filter(Boolean).length;
  }

  report.schemathesisJourney.state.schemathesis = {
    ...report.schemathesisJourney.state.schemathesis,
    command: `${binary} ${redactedCommand(args)}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    stdoutTail: stdout.slice(-6000),
    stderrTail: stderr.slice(-6000),
    ndjsonExists,
    ndjsonLines,
  };
  addCheck(
    report,
    "Schemathesis 属性测试: 安全 GET OpenAPI 合同 fuzz 通过",
    result.status === 0 ? "pass" : "fail",
    `exit=${result.status}, ndjson=${ndjsonExists}, events=${ndjsonLines}, durationMs=${Date.now() - startedAt}`,
  );
}

async function runSchemathesisJourney(report, options, artifactDir) {
  const children = [];
  let backendStdout = null;
  let backendStderr = null;

  try {
    const apiPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v32.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v32_client_${Date.now().toString(36)}`,
      password: `V32-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v32-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v32-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V32隔离客户",
      INITIAL_CLIENT_PHONE: "",
      INITIAL_CLIENT_EMAIL: "",
      ASTERISK_LIVE_CALL_ENABLED: "false",
      ASTERISK_BULK_CALL_ENABLED: "false",
      OUTBOUND_QUEUE_ENABLED: "false",
      DM_BROWSER_LIVE_SEND_ENABLED: "false",
      DM_QUEUE_ENABLED: "false",
      COMMENT_INTERCEPT_LIVE_SYNC_ENABLED: "false",
      COMMENT_INTERCEPT_ADAPTER_MODE: "disabled",
      REALTIME_CONVERSATION_MODE: "pipeline",
      VOICE_SAMPLE_STORAGE_ROOT: path.join(artifactDir, "voice-samples"),
    };
    const origin = `http://127.0.0.1:${apiPort}`;
    const apiBase = `${origin}/api`;
    report.schemathesisJourney.runtime = {
      apiPort,
      apiBase,
      openapiUrl: `${origin}/openapi.json`,
      databasePath,
      databaseUrl,
      credentialsAlias: credentials.username,
    };

    const migration = await runCommand(python, ["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], {
      cwd: BACKEND_ROOT,
      env,
    });
    await fs.writeFile(report.schemathesisJourney.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.schemathesisJourney.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.schemathesisJourney.artifacts.backendLog, "a");
    const backend = startProcess(
      python,
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
      {
        cwd: BACKEND_ROOT,
        env,
        stdout: backendStdout.createWriteStream(),
        stderr: backendStderr.createWriteStream(),
      },
    );
    children.push(backend);
    await waitForUrl(`${apiBase}/health`, options.timeoutMs, "ok");
    addCheck(report, "沙箱后端: 临时 API 可用", "pass", apiBase);

    const openapiResponse = await fetch(`${origin}/openapi.json`, { headers: correlationHeaders(report.correlation) });
    const openapiHeaders = Object.fromEntries(openapiResponse.headers.entries());
    const openapi = await openapiResponse.json();
    recordApiResponse(report, "GET", "/openapi.json", openapiResponse.status, openapiHeaders, openapiResponse.ok, openapi);
    report.schemathesisJourney.state.openapi = {
      title: openapi.info?.title || "",
      version: openapi.info?.version || "",
      paths: Object.keys(openapi.paths || {}).length,
      schemas: Object.keys(openapi.components?.schemas || {}).length,
    };
    await writeJson(report.schemathesisJourney.artifacts.openapiSchema, openapi);
    addCheck(
      report,
      "OpenAPI 合约: schema 可读取",
      openapiResponse.ok && report.schemathesisJourney.state.openapi.paths >= 50 ? "pass" : "fail",
      `paths=${report.schemathesisJourney.state.openapi.paths}, schemas=${report.schemathesisJourney.state.openapi.schemas}`,
    );

    const login = await apiRequest(report, apiBase, "/auth/login", {
      method: "POST",
      body: { identifier: credentials.username, password: credentials.password },
    });
    report.schemathesisJourney.state.accessToken = login.body?.accessToken || "";
    addCheck(report, "认证探针: seeded client 可登录", login.ok && report.schemathesisJourney.state.accessToken ? "pass" : "fail", `status=${login.status}`);

    const safeOperations = selectSafeReadOperations(openapi);
    report.schemathesisJourney.state.safeOperations = safeOperations;
    const safeGetOpenapi = buildSafeGetOpenapi(openapi, safeOperations.routes, origin);
    await writeJson(report.schemathesisJourney.artifacts.filteredOpenapiSchema, safeGetOpenapi);
    addCheck(
      report,
      "安全选择: 仅纳入 GET 且排除 live/write 路由",
      safeOperations.routes.length >= 30 && safeOperations.dangerousCandidateMatches.length === 0 ? "pass" : "fail",
      `selected=${safeOperations.routes.length}, totalGet=${safeOperations.totalGetOperations}, rejected=${safeOperations.rejectedCandidates.length}, dangerousMatches=${safeOperations.dangerousCandidateMatches.length}`,
      safeOperations,
    );

    report.schemathesisJourney.state.sideEffectsBefore = await collectSideEffectCounts(report, apiBase);
    await runSchemathesis(report, options, origin, artifactDir);
    report.schemathesisJourney.state.sideEffectsAfter = await collectSideEffectCounts(report, apiBase);
    addCheck(
      report,
      "安全门控: Schemathesis 未改变消息/导出/采集/通话记录计数",
      countsUnchanged(report.schemathesisJourney.state.sideEffectsBefore, report.schemathesisJourney.state.sideEffectsAfter) ? "pass" : "fail",
      "read-only side-effect counters compared before/after",
      {
        before: report.schemathesisJourney.state.sideEffectsBefore,
        after: report.schemathesisJourney.state.sideEffectsAfter,
      },
    );
  } catch (error) {
    addCheck(report, "V32 Schemathesis QA runner", "fail", error.stack || error.message);
  } finally {
    if (!options.keep) {
      for (const child of children.reverse()) stopProcess(child);
    }
    await backendStdout?.close().catch(() => {});
    await backendStderr?.close().catch(() => {});
  }
}

function checkStatus(report, pattern) {
  return report.schemathesisJourney.checks.find((check) => pattern.test(`${check.name} ${check.detail}`))?.status || "missing";
}

async function pathExists(file) {
  if (!file) return false;
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

async function evaluate(report) {
  const state = report.schemathesisJourney.state;
  const checks = report.schemathesisJourney.checks;
  const stdoutExists = await pathExists(report.schemathesisJourney.artifacts.stdoutLog);
  const stderrExists = await pathExists(report.schemathesisJourney.artifacts.stderrLog);
  const ndjsonExists = await pathExists(report.schemathesisJourney.artifacts.ndjson);
  const openapiExists = await pathExists(report.schemathesisJourney.artifacts.openapiSchema);
  const filteredOpenapiExists = await pathExists(report.schemathesisJourney.artifacts.filteredOpenapiSchema);
  const selectedRoutes = state.safeOperations?.routes || [];
  const sideEffectsClean = countsUnchanged(state.sideEffectsBefore, state.sideEffectsAfter);
  const schemathesisPassed = state.schemathesis?.exitCode === 0;
  const hardCheckFailure = checks.some((check) => check.status === "fail");

  const dimensions = {
    v31RegressionPreserved: {
      status: report.v31?.summary?.canClaimOpenApiModelGate || report.target.skipV31 ? "pass" : "fail",
      score: report.v31?.summary?.canClaimOpenApiModelGate || report.target.skipV31 ? 10 : 0,
      detail: report.target.skipV31 ? "skipped by option" : `openApiModel=${Boolean(report.v31?.summary?.canClaimOpenApiModelGate)}`,
    },
    schemathesisInstalled: {
      status: state.schemathesis?.version ? "pass" : "fail",
      score: state.schemathesis?.version ? 10 : 0,
      detail: state.schemathesis?.version || "missing",
    },
    safeOperationSelection: {
      status: selectedRoutes.length >= 30 && state.safeOperations?.dangerousCandidateMatches?.length === 0 ? "pass" : "fail",
      score: Math.min(15, Math.round((selectedRoutes.length / 35) * 15)),
      detail: `selected=${selectedRoutes.length}, totalGet=${state.safeOperations?.totalGetOperations || 0}`,
    },
    generatedPropertyRun: {
      status: schemathesisPassed ? "pass" : "fail",
      score: schemathesisPassed ? 30 : 0,
      detail: `exit=${state.schemathesis?.exitCode}, maxExamples=${report.target.maxExamples}, seed=${report.target.seed}`,
    },
    contractChecks: {
      status: schemathesisPassed && checkStatus(report, /OpenAPI 合约/) === "pass" ? "pass" : "fail",
      score: schemathesisPassed && checkStatus(report, /OpenAPI 合约/) === "pass" ? 15 : 0,
      detail: `paths=${state.openapi?.paths || 0}, schemas=${state.openapi?.schemas || 0}`,
    },
    noDangerousSideEffects: {
      status: sideEffectsClean && checkStatus(report, /仅纳入 GET/) === "pass" ? "pass" : "fail",
      score: sideEffectsClean && checkStatus(report, /仅纳入 GET/) === "pass" ? 10 : 0,
      detail: `sideEffectsClean=${sideEffectsClean}`,
    },
    artifacts: {
      status: stdoutExists && stderrExists && ndjsonExists && openapiExists && filteredOpenapiExists ? "pass" : "warn",
      score: [stdoutExists, stderrExists, ndjsonExists, openapiExists, filteredOpenapiExists].filter(Boolean).length * 2,
      detail: `stdout=${stdoutExists}, stderr=${stderrExists}, ndjson=${ndjsonExists}, openapi=${openapiExists}, filteredOpenapi=${filteredOpenapiExists}`,
    },
  };

  const score = Math.min(100, Math.round(Object.values(dimensions).reduce((sum, item) => sum + item.score, 0)));
  const hardFailure = hardCheckFailure || Object.values(dimensions).some((item) => item.status === "fail");
  const status = hardFailure ? "fail" : "warn";

  return {
    status,
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure,
      canClaimSchemathesisContractGate: !hardFailure,
      canClaimOpenApiModelGate: Boolean(report.v31?.summary?.canClaimOpenApiModelGate),
      canClaimSemanticBreadthUi: Boolean(report.v31?.summary?.canClaimSemanticBreadthUi),
      canClaimCommentIntentStatefulUi: Boolean(report.v31?.summary?.canClaimCommentIntentStatefulUi),
      canClaimDmStatefulUi: Boolean(report.v31?.summary?.canClaimDmStatefulUi),
      canClaimBroadBusinessCoverage: false,
      canClaimRealBusinessReady: false,
      liveActionsStillGated: true,
      nextJourney: {
        module: "V33 OpenAPI links/stateful POST 沙箱链路",
        suggestedGate: "为安全创建类接口补充 OpenAPI links 或本地 adapter，先修复 V32 发现的 naive datetime date-time 合同问题，再让 Schemathesis stateful phase 自动链出 create/read/update 流程，同时继续阻断 start/send/call/export/provider-run live 动作",
      },
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  const summary = report.summary;
  lines.push("# V32 Schemathesis OpenAPI Property QA");
  lines.push("");
  lines.push(`Status: ${summary.status}`);
  lines.push(`Score: ${summary.score}/100`);
  lines.push(`Schemathesis contract gate ready: ${summary.canClaimSchemathesisContractGate}`);
  lines.push(`OpenAPI model gate preserved: ${summary.canClaimOpenApiModelGate}`);
  lines.push(`Real business ready: ${summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, dimension] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${dimension.status} (${dimension.score}) - ${dimension.detail}`);
  }
  lines.push("");
  lines.push("## Safe Operations");
  lines.push(`Selected GET routes: ${report.schemathesisJourney.state.safeOperations?.routes?.length || 0}`);
  for (const route of report.schemathesisJourney.state.safeOperations?.routes || []) {
    lines.push(`- GET ${route}`);
  }
  lines.push("");
  lines.push("## Schemathesis");
  lines.push(`- Version: ${report.schemathesisJourney.state.schemathesis?.version || ""}`);
  lines.push(`- Exit code: ${report.schemathesisJourney.state.schemathesis?.exitCode}`);
  lines.push(`- NDJSON events: ${report.schemathesisJourney.state.schemathesis?.ndjsonLines || 0}`);
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V32 report: ${report.artifacts.report}`);
  lines.push(`- V32 markdown: ${report.artifacts.markdown}`);
  lines.push(`- Schemathesis stdout: ${report.schemathesisJourney.artifacts.stdoutLog}`);
  lines.push(`- Schemathesis stderr: ${report.schemathesisJourney.artifacts.stderrLog}`);
  lines.push(`- Schemathesis ndjson: ${report.schemathesisJourney.artifacts.ndjson}`);
  lines.push(`- OpenAPI schema: ${report.schemathesisJourney.artifacts.openapiSchema}`);
  lines.push(`- Safe GET OpenAPI schema: ${report.schemathesisJourney.artifacts.filteredOpenapiSchema}`);
  lines.push(`- V31 report: ${summary.v31Report || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V32",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV31: options.skipV31,
      fullChain: options.fullChain,
      maxExamples: options.maxExamples,
      seed: options.seed,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Schemathesis CLI can run OpenAPI property-based tests with coverage/fuzzing/stateful phases, custom headers, path/method filters, fixed seeds, and machine-readable reports.",
      "Schemathesis stateful testing can chain real response data when OpenAPI links, Location headers, or inferable schemas expose producer/consumer relationships; V32 starts with safe generated GET contract checks and makes V33 links/stateful POST the next step.",
      "FastAPI serves its runtime OpenAPI schema at /openapi.json by default, so a temporary backend can be tested against the actual generated contract rather than a stale file.",
    ],
    correlation: makeCorrelation(),
    v31Execution: null,
    v31: null,
    schemathesisJourney: {
      checks: [],
      runtime: {},
      state: {
        accessToken: "",
        openapi: {},
        safeOperations: { routes: [], pathRegex: "$^", rejectedCandidates: [], dangerousCandidateMatches: [], totalGetOperations: 0 },
        schemathesis: {},
        sideEffectsBefore: {},
        sideEffectsAfter: {},
      },
      evidence: {
        apiTraffic: [],
      },
      artifacts: {
        root: artifactDir,
        backendLog: path.join(artifactDir, "backend.log"),
        migrationLog: path.join(artifactDir, "migration.log"),
        openapiSchema: path.join(artifactDir, "openapi.schema.json"),
        filteredOpenapiSchema: path.join(artifactDir, "openapi.safe-get.schema.json"),
        stdoutLog: path.join(artifactDir, "schemathesis.stdout.log"),
        stderrLog: path.join(artifactDir, "schemathesis.stderr.log"),
        schemathesisReportDir: path.join(artifactDir, "schemathesis-report"),
        ndjson: path.join(artifactDir, "schemathesis-events.ndjson"),
      },
    },
    durationMs: 0,
  };

  const startedAt = Date.now();
  if (options.fromReport) {
    report.v31 = await readJson(options.fromReport);
    report.v31Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV31) {
    report.v31Execution = runV31(options, path.join(artifactDir, "v31"));
    report.v31 = report.v31Execution.report;
  } else {
    report.v31Execution = { command: "skip V31", exitCode: 0, durationMs: 0, parseError: null };
    report.v31 = {
      summary: {
        canClaimOpenApiModelGate: false,
        canClaimSemanticBreadthUi: false,
        canClaimCommentIntentStatefulUi: false,
        canClaimDmStatefulUi: false,
      },
    };
  }

  await runSchemathesisJourney(report, options, artifactDir);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = await evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimSchemathesisContractGate: report.evaluation.readinessDecision.canClaimSchemathesisContractGate,
    canClaimOpenApiModelGate: report.evaluation.readinessDecision.canClaimOpenApiModelGate,
    canClaimSemanticBreadthUi: report.evaluation.readinessDecision.canClaimSemanticBreadthUi,
    canClaimCommentIntentStatefulUi: report.evaluation.readinessDecision.canClaimCommentIntentStatefulUi,
    canClaimDmStatefulUi: report.evaluation.readinessDecision.canClaimDmStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v31Report: report.v31?.artifacts?.report || report.v31?.summary?.v31Report || options.fromReport || "",
    schemathesis: {
      version: report.schemathesisJourney.state.schemathesis?.version || "",
      selectedRoutes: report.schemathesisJourney.state.safeOperations?.routes?.length || 0,
      ndjson: report.schemathesisJourney.artifacts.ndjson,
    },
  };
  report.artifacts = {
    root: artifactDir,
    report: path.join(artifactDir, "report.json"),
    markdown: path.join(artifactDir, "schemathesis.md"),
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V32 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} schemathesis=${report.summary.canClaimSchemathesisContractGate} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Safe generated routes: ${report.summary.schemathesis.selectedRoutes}`);
    console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Schemathesis evidence: ${report.artifacts.markdown}`);
    console.log(`NDJSON: ${report.schemathesisJourney.artifacts.ndjson}`);
  }

  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
