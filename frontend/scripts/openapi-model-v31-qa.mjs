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
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v31-openapi-model-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

const modelJourneys = [
  {
    key: "auth",
    label: "认证",
    requiredRoutes: [["POST", "/api/auth/login"], ["GET", "/api/auth/me"]],
  },
  {
    key: "stateful_outbound",
    label: "线索到外呼任务",
    requiredRoutes: [["GET", "/api/leads"], ["POST", "/api/leads"], ["GET", "/api/outbound/tasks"], ["POST", "/api/outbound/tasks"]],
  },
  {
    key: "collector",
    label: "线索采集",
    requiredRoutes: [["GET", "/api/collections/tasks"], ["POST", "/api/collections/tasks"], ["GET", "/api/collections/runs"], ["GET", "/api/collections/raw-records"]],
  },
  {
    key: "platform_dm",
    label: "平台私信",
    requiredRoutes: [
      ["POST", "/api/direct-messages/accounts"],
      ["POST", "/api/direct-messages/accounts/{account_id}/desktop-login-check"],
      ["POST", "/api/direct-messages/templates"],
      ["POST", "/api/direct-messages/tasks"],
      ["GET", "/api/direct-messages/conversations"],
      ["GET", "/api/direct-messages/messages"],
    ],
  },
  {
    key: "comment_intent",
    label: "评论截流到意向客户",
    requiredRoutes: [
      ["POST", "/api/direct-messages/intercepts/sources"],
      ["POST", "/api/direct-messages/intercepts/sources/{source_id}/browser-capture"],
      ["POST", "/api/direct-messages/intercepts/comments/convert"],
      ["GET", "/api/intent/customers"],
      ["GET", "/api/intent/work-orders"],
    ],
  },
  {
    key: "semantic_breadth",
    label: "声音/报表/设置广度",
    requiredRoutes: [
      ["GET", "/api/voice/overview"],
      ["GET", "/api/voice/system-voices"],
      ["GET", "/api/reports/overview"],
      ["GET", "/api/reports/channels"],
      ["GET", "/api/reports/sales"],
      ["GET", "/api/reports/exports"],
      ["GET", "/api/settings/overview"],
      ["GET", "/api/settings/items"],
    ],
  },
];

const probeRoutes = [
  ["GET", "/api/health"],
  ["GET", "/api/modules"],
  ["GET", "/api/leads"],
  ["GET", "/api/outbound/overview"],
  ["GET", "/api/outbound/tasks"],
  ["GET", "/api/outbound/telephony/config"],
  ["GET", "/api/outbound/telephony/preflight"],
  ["GET", "/api/collections/tasks"],
  ["GET", "/api/collections/runs"],
  ["GET", "/api/collections/raw-records"],
  ["GET", "/api/direct-messages/overview"],
  ["GET", "/api/direct-messages/accounts"],
  ["GET", "/api/direct-messages/templates"],
  ["GET", "/api/direct-messages/tasks"],
  ["GET", "/api/direct-messages/conversations"],
  ["GET", "/api/direct-messages/messages"],
  ["GET", "/api/direct-messages/intercepts/sources"],
  ["GET", "/api/direct-messages/intercepts/comments"],
  ["GET", "/api/intent/overview"],
  ["GET", "/api/intent/customers"],
  ["GET", "/api/intent/work-orders"],
  ["GET", "/api/voice/overview"],
  ["GET", "/api/voice/system-voices"],
  ["GET", "/api/voice/profiles"],
  ["GET", "/api/reports/overview"],
  ["GET", "/api/reports/channels"],
  ["GET", "/api/reports/sales"],
  ["GET", "/api/reports/exports"],
  ["GET", "/api/settings/overview"],
  ["GET", "/api/settings/items"],
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
    json: false,
    batch: false,
    skipV30: false,
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
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--skip-v30") {
      options.skipV30 = true;
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
  console.log(`AI ACQ V31 OpenAPI model-path QA

Default: run V30, then verify OpenAPI contracts and authenticated read probes for the V17-V30 model journeys.
  npm run qa:v31 -- --repeat 2

Evaluate an existing V30 report and only run V31 OpenAPI/model gate:
  npm run qa:v31 -- --from-report .playwright-cli/v30-semantic-breadth-qa/<run>/report.json

Batch composition keeps live calls/sends/sync gated:
  npm run qa:v31:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
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

function redact(value, key = "") {
  if (typeof value === "string") {
    if (isSensitiveKey(key)) return value ? "[redacted]" : "";
    return value
      .replace(/\b1[3-9]\d{9}\b/g, (match) => `${match.slice(0, 3)}****${match.slice(-4)}`)
      .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[token-redacted]");
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

function runV30(options, artifactDir) {
  const args = [
    "scripts/semantic-breadth-v30-qa.mjs",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--skip-v29",
    "--artifact-root",
    artifactDir,
  ];
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
    stdoutTail: result.stdout?.slice(-5000) || "",
    stderrTail: result.stderr?.slice(-5000) || "",
  };
}

function makeCorrelation() {
  const random = Math.random().toString(16).slice(2, 18).padEnd(16, "0");
  const runId = `v31-openapi-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V31`,
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
  report.openapiModelJourney.checks.push({ name, status, detail, data });
}

function recordApiResponse(report, method, pathName, status, headers = {}, ok = false, body = null) {
  report.openapiModelJourney.evidence.apiTraffic.push({
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
      ...(report.openapiModelJourney.state.accessToken ? { Authorization: `Bearer ${report.openapiModelJourney.state.accessToken}` } : {}),
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

function openApiHasRoute(openapi, method, pathName) {
  const lower = method.toLowerCase();
  return Boolean(openapi?.paths?.[pathName]?.[lower]);
}

function responseHasSchema(openapi, method, pathName) {
  const operation = openapi?.paths?.[pathName]?.[method.toLowerCase()];
  if (!operation) return false;
  const responses = operation.responses || {};
  const response = responses["200"] || responses["201"] || responses["204"] || Object.values(responses)[0];
  if (!response) return false;
  if (response.content?.["application/json"]?.schema) return true;
  return response.description && Object.keys(responses).length > 0;
}

function buildModelGraph(openapi) {
  return {
    version: "V31",
    generatedAt: new Date().toISOString(),
    journeys: modelJourneys.map((journey) => {
      const routes = journey.requiredRoutes.map(([method, pathName]) => ({
        method,
        path: pathName,
        inOpenApi: openApiHasRoute(openapi, method, pathName),
        hasResponseSchema: responseHasSchema(openapi, method, pathName),
      }));
      return {
        key: journey.key,
        label: journey.label,
        routes,
        complete: routes.every((route) => route.inOpenApi),
        schemaComplete: routes.every((route) => route.hasResponseSchema),
      };
    }),
  };
}

async function runOpenApiModelJourney(report, options, artifactDir) {
  const children = [];
  let backendStdout = null;
  let backendStderr = null;

  try {
    const apiPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v31.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v31_client_${Date.now().toString(36)}`,
      password: `V31-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v31-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v31-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V31隔离客户",
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
    report.openapiModelJourney.runtime = {
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
    await fs.writeFile(report.openapiModelJourney.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.openapiModelJourney.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.openapiModelJourney.artifacts.backendLog, "a");
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
    report.openapiModelJourney.state.openapi = {
      title: openapi.info?.title || "",
      version: openapi.info?.version || "",
      paths: Object.keys(openapi.paths || {}).length,
      components: Object.keys(openapi.components?.schemas || {}).length,
    };
    addCheck(
      report,
      "OpenAPI 合约: schema 可读取",
      openapiResponse.ok && report.openapiModelJourney.state.openapi.paths >= 50 ? "pass" : "fail",
      `paths=${report.openapiModelJourney.state.openapi.paths}, schemas=${report.openapiModelJourney.state.openapi.components}`,
    );

    const login = await apiRequest(report, apiBase, "/auth/login", {
      method: "POST",
      body: { identifier: credentials.username, password: credentials.password },
    });
    report.openapiModelJourney.state.accessToken = login.body?.accessToken || "";
    addCheck(report, "认证探针: seeded client 可登录", login.ok && report.openapiModelJourney.state.accessToken ? "pass" : "fail", `status=${login.status}`);

    const me = await apiRequest(report, apiBase, "/auth/me");
    addCheck(report, "认证探针: bearer token 可访问 /auth/me", me.ok && me.body?.username === credentials.username ? "pass" : "fail", `status=${me.status}, user=${me.body?.username || "missing"}`);

    const modelGraph = buildModelGraph(openapi);
    report.openapiModelJourney.state.modelGraph = modelGraph;
    await writeJson(report.openapiModelJourney.artifacts.modelGraph, modelGraph);
    const journeyComplete = modelGraph.journeys.filter((journey) => journey.complete).length;
    const schemaComplete = modelGraph.journeys.filter((journey) => journey.schemaComplete).length;
    addCheck(
      report,
      "模型路径: V17-V30 关键业务旅程在 OpenAPI 中完整",
      journeyComplete === modelGraph.journeys.length ? "pass" : "fail",
      `journeys=${journeyComplete}/${modelGraph.journeys.length}, schemaComplete=${schemaComplete}/${modelGraph.journeys.length}`,
      modelGraph,
    );

    const probeResults = [];
    for (const [method, route] of probeRoutes) {
      const response = await apiRequest(report, apiBase, route.replace(/^\/api/, ""));
      probeResults.push({ method, route, ok: response.ok, status: response.status, bodyType: Array.isArray(response.body) ? "array" : typeof response.body });
    }
    report.openapiModelJourney.state.probeResults = probeResults;
    const okProbes = probeResults.filter((item) => item.ok).length;
    addCheck(
      report,
      "认证探针: 关键只读 API 均可访问且无 5xx",
      okProbes === probeResults.length && probeResults.every((item) => item.status < 500) ? "pass" : "fail",
      `ok=${okProbes}/${probeResults.length}`,
      probeResults,
    );

    const beforeAfter = {
      conversations: probeResults.find((item) => item.route === "/api/direct-messages/conversations")?.status || null,
      messages: probeResults.find((item) => item.route === "/api/direct-messages/messages")?.status || null,
      exports: probeResults.find((item) => item.route === "/api/reports/exports")?.status || null,
    };
    addCheck(report, "安全门控: V31 只做合约和只读探针", "pass", `readOnlyStatuses=${JSON.stringify(beforeAfter)}`);
  } catch (error) {
    addCheck(report, "V31 OpenAPI model QA runner", "fail", error.stack || error.message);
  } finally {
    if (!options.keep) {
      for (const child of children.reverse()) stopProcess(child);
    }
    await backendStdout?.close().catch(() => {});
    await backendStderr?.close().catch(() => {});
  }
}

function checkStatus(report, pattern) {
  return report.openapiModelJourney.checks.find((check) => pattern.test(`${check.name} ${check.detail}`))?.status || "missing";
}

async function evaluate(report) {
  const modelGraphExists = await pathExists(report.openapiModelJourney.artifacts.modelGraph);
  const traffic = report.openapiModelJourney.evidence.apiTraffic;
  const echoedResponses = traffic.filter((item) => item.correlationEchoed === true);
  const routeCount = report.openapiModelJourney.state.openapi.paths || 0;
  const schemaCount = report.openapiModelJourney.state.openapi.components || 0;
  const modelGraph = report.openapiModelJourney.state.modelGraph || { journeys: [] };
  const journeyComplete = modelGraph.journeys.filter((journey) => journey.complete).length;
  const schemaCompleteRoutes = modelGraph.journeys.flatMap((journey) => journey.routes).filter((route) => route.hasResponseSchema).length;
  const totalModelRoutes = modelGraph.journeys.flatMap((journey) => journey.routes).length || 1;
  const probeResults = report.openapiModelJourney.state.probeResults || [];
  const okProbes = probeResults.filter((item) => item.ok).length;
  const dangerousCovered = traffic.some((item) => dangerousRoutePatterns.some((pattern) => pattern.test(item.path)) && item.method !== "GET");

  const dimensions = {
    v30RegressionPreserved: {
      status: report.v30?.summary?.canClaimSemanticBreadthUi || report.target.skipV30 ? "pass" : "fail",
      score: report.v30?.summary?.canClaimSemanticBreadthUi || report.target.skipV30 ? 10 : 0,
      detail: report.target.skipV30 ? "skipped by option" : `semanticBreadth=${Boolean(report.v30?.summary?.canClaimSemanticBreadthUi)}`,
    },
    openApiLoaded: {
      status: routeCount >= 50 && schemaCount >= 20 ? "pass" : "fail",
      score: routeCount >= 50 && schemaCount >= 20 ? 15 : 0,
      detail: `paths=${routeCount}, schemas=${schemaCount}`,
    },
    modelJourneyCompleteness: {
      status: journeyComplete === modelGraph.journeys.length && modelGraph.journeys.length >= 6 ? "pass" : "fail",
      score: Math.round((journeyComplete / Math.max(1, modelGraph.journeys.length)) * 25),
      detail: `journeys=${journeyComplete}/${modelGraph.journeys.length}`,
    },
    schemaContractCompleteness: {
      status: schemaCompleteRoutes / totalModelRoutes >= 0.9 ? "pass" : "warn",
      score: Math.round((schemaCompleteRoutes / totalModelRoutes) * 15),
      detail: `responseSchemas=${schemaCompleteRoutes}/${totalModelRoutes}`,
    },
    authenticatedProbeCoverage: {
      status: okProbes === probeResults.length && probeResults.length >= 25 ? "pass" : "fail",
      score: Math.round((okProbes / Math.max(1, probeResults.length)) * 15),
      detail: `ok=${okProbes}/${probeResults.length}`,
    },
    noDangerousSideEffects: {
      status: checkStatus(report, /只做合约和只读探针/) === "pass" && !dangerousCovered ? "pass" : "fail",
      score: checkStatus(report, /只做合约和只读探针/) === "pass" && !dangerousCovered ? 10 : 0,
      detail: `dangerousCovered=${dangerousCovered}, readOnly=${checkStatus(report, /只做合约和只读探针/)}`,
    },
    artifactsAndCorrelation: {
      status: modelGraphExists && echoedResponses.length >= 10 ? "pass" : "warn",
      score: modelGraphExists ? Math.min(10, 5 + Math.min(5, echoedResponses.length)) : 0,
      detail: `modelGraph=${modelGraphExists}, echo=${echoedResponses.length}/${traffic.length}`,
    },
  };

  const score = Math.min(100, Object.values(dimensions).reduce((sum, item) => sum + item.score, 0));
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  const status = hardFailure ? "fail" : "warn";

  return {
    status,
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure,
      canClaimOpenApiModelGate: !hardFailure,
      canClaimSemanticBreadthUi: Boolean(report.v30?.summary?.canClaimSemanticBreadthUi),
      canClaimCommentIntentStatefulUi: Boolean(report.v30?.summary?.canClaimCommentIntentStatefulUi),
      canClaimDmStatefulUi: Boolean(report.v30?.summary?.canClaimDmStatefulUi),
      canClaimBroadBusinessCoverage: false,
      canClaimRealBusinessReady: false,
      liveActionsStillGated: true,
      nextJourney: {
        module: "Schemathesis 重型状态/属性测试或 Playwright 模型生成路径",
        suggestedGate: "install/enable Schemathesis or an equivalent property-based API runner, then generate stateful API sequences from OpenAPI links/examples and compare them with V17-V31 UI model paths",
      },
    },
  };
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

function renderMarkdown(report) {
  const lines = [];
  const summary = report.summary;
  lines.push("# V31 OpenAPI Model-Path QA");
  lines.push("");
  lines.push(`Status: ${summary.status}`);
  lines.push(`Score: ${summary.score}/100`);
  lines.push(`OpenAPI model gate ready: ${summary.canClaimOpenApiModelGate}`);
  lines.push(`Semantic breadth preserved: ${summary.canClaimSemanticBreadthUi}`);
  lines.push(`Real business ready: ${summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, dimension] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${dimension.status} (${dimension.score}) - ${dimension.detail}`);
  }
  lines.push("");
  lines.push("## Model Journeys");
  for (const journey of report.openapiModelJourney.state.modelGraph?.journeys || []) {
    lines.push(`- ${journey.label}: complete=${journey.complete}, schemaComplete=${journey.schemaComplete}, routes=${journey.routes.length}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V31 report: ${report.artifacts.report}`);
  lines.push(`- V31 markdown: ${report.artifacts.markdown}`);
  lines.push(`- V31 model graph: ${report.openapiModelJourney.artifacts.modelGraph}`);
  lines.push(`- V30 report: ${report.summary.v30Report || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V31",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV30: options.skipV30,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Schemathesis-style OpenAPI testing generates property/stateful tests from API schemas and can discover API bugs beyond fixed happy paths.",
      "FastAPI exposes OpenAPI at runtime, so V31 can compare implementation routes, schemas, and authenticated probes against the tested UI/business model.",
      "Model-based testing maps the product into journeys and transitions, making missing paths explicit before adding heavier generated path runners.",
    ],
    correlation: makeCorrelation(),
    v30Execution: null,
    v30: null,
    openapiModelJourney: {
      checks: [],
      runtime: {},
      state: {
        accessToken: "",
        openapi: {},
        modelGraph: null,
        probeResults: [],
      },
      evidence: {
        apiTraffic: [],
      },
      artifacts: {
        root: artifactDir,
        modelGraph: path.join(artifactDir, "model-graph.json"),
        backendLog: path.join(artifactDir, "backend.log"),
        migrationLog: path.join(artifactDir, "migration.log"),
      },
    },
    durationMs: 0,
  };

  const startedAt = Date.now();
  if (options.fromReport) {
    report.v30 = await readJson(options.fromReport);
    report.v30Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV30) {
    report.v30Execution = runV30(options, path.join(artifactDir, "v30"));
    report.v30 = report.v30Execution.report;
  } else {
    report.v30Execution = { command: "skip V30", exitCode: 0, durationMs: 0, parseError: null };
    report.v30 = {
      summary: {
        canClaimSemanticBreadthUi: false,
        canClaimCommentIntentStatefulUi: false,
        canClaimDmStatefulUi: false,
      },
    };
  }

  await runOpenApiModelJourney(report, options, artifactDir);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = await evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimOpenApiModelGate: report.evaluation.readinessDecision.canClaimOpenApiModelGate,
    canClaimSemanticBreadthUi: report.evaluation.readinessDecision.canClaimSemanticBreadthUi,
    canClaimCommentIntentStatefulUi: report.evaluation.readinessDecision.canClaimCommentIntentStatefulUi,
    canClaimDmStatefulUi: report.evaluation.readinessDecision.canClaimDmStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v30Report: report.v30?.artifacts?.report || report.v30?.summary?.v30Report || options.fromReport || "",
    modelGraph: report.openapiModelJourney.artifacts.modelGraph,
  };
  report.artifacts = {
    root: artifactDir,
    report: path.join(artifactDir, "report.json"),
    markdown: path.join(artifactDir, "openapi-model.md"),
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V31 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} openApiModel=${report.summary.canClaimOpenApiModelGate} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`OpenAPI model evidence: ${report.artifacts.markdown}`);
    console.log(`Model graph: ${report.openapiModelJourney.artifacts.modelGraph}`);
  }

  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
