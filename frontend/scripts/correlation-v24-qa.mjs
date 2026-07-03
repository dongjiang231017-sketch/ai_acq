#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v24-authenticated-stateful-qa");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";
const DEFAULT_USERNAME = process.env.AI_ACQ_QA_AUTH_USERNAME || "v24_client";
const DEFAULT_PASSWORD = process.env.AI_ACQ_QA_AUTH_PASSWORD || "v24-client-password";

const ownOptionsWithValue = new Set([
  "--repeat",
  "--interval-ms",
  "--artifact-root",
  "--from-report",
  "--api",
  "--timeout-ms",
  "--mode",
  "--backend-port",
  "--auth-username",
  "--auth-password",
]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    api: DEFAULT_API,
    timeoutMs: 180000,
    backendPort: 0,
    authUsername: DEFAULT_USERNAME,
    authPassword: DEFAULT_PASSWORD,
    json: false,
    batch: false,
    live: false,
    skipV22: false,
    noStartBackend: false,
    keepBackend: false,
    allowExistingApiWrites: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 1000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      if (arg === "--api") options.api = next.replace(/\/$/, "");
      if (arg === "--timeout-ms") options.timeoutMs = Math.max(10000, Number(next) || 180000);
      if (arg === "--backend-port") options.backendPort = Number(next) || 0;
      if (arg === "--auth-username") options.authUsername = next;
      if (arg === "--auth-password") options.authPassword = next;
      if (arg === "--mode") options.live = next === "live";
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--live") {
      options.live = true;
    } else if (arg === "--skip-v22") {
      options.skipV22 = true;
    } else if (arg === "--no-start-backend") {
      options.noStartBackend = true;
    } else if (arg === "--keep-backend") {
      options.keepBackend = true;
    } else if (arg === "--allow-existing-api-writes") {
      options.allowExistingApiWrites = true;
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
  console.log(`AI ACQ V24 authenticated stateful correlation QA

Default: start an isolated backend with a temporary SQLite DB, log in as a seeded QA client, create a real lead and outbound task, then run V22 with the bearer token.
  npm run qa:v24 -- --repeat 2

Use an existing API without writes:
  npm run qa:v24 -- --no-start-backend --api http://127.0.0.1:8017/api

Permit stateful writes against an existing API only after explicit confirmation:
  npm run qa:v24 -- --no-start-backend --allow-existing-api-writes --auth-username <user> --auth-password <password>
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

function redact(value, key = "") {
  if (typeof value === "string") {
    if (/password|token|secret|authorization|cookie|key/i.test(key)) return value ? "[redacted]" : "";
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

function traceContext(runId) {
  const traceId = randomBytes(16).toString("hex");
  const spanId = randomBytes(8).toString("hex");
  return {
    runId,
    traceId,
    spanId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V24`,
  };
}

async function freePort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(preferred, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : preferred;
      server.close(() => resolve(port));
    });
  });
}

function pythonBin() {
  return path.join(BACKEND_ROOT, ".venv", "bin", "python");
}

async function appendLog(file, chunk) {
  await fs.appendFile(file, chunk.toString(), "utf8").catch(() => {});
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function backendEnv(options, artifactDir, dbPath) {
  return {
    ...process.env,
    DATABASE_URL: `sqlite:///${dbPath}`,
    BROWSER_PROFILE_ROOT: path.join(artifactDir, "browser-profiles"),
    DM_BROWSER_PROFILE_ROOT: path.join(artifactDir, "dm-browser-profiles"),
    VOICE_SAMPLE_STORAGE_ROOT: path.join(artifactDir, "voice-samples"),
    VOICE_OUTPUT_STORAGE_ROOT: path.join(artifactDir, "voice-outputs"),
    INITIAL_CLIENT_USERNAME: options.authUsername,
    INITIAL_CLIENT_PASSWORD: options.authPassword,
    INITIAL_CLIENT_DISPLAY_NAME: "V24 QA Client",
    AUTH_SECRET_KEY: `v24-${randomUUID()}`,
    ASTERISK_LIVE_CALL_ENABLED: "false",
    ASTERISK_BULK_CALL_ENABLED: "false",
    DM_BROWSER_LIVE_SEND_ENABLED: "false",
    COMMENT_INTERCEPT_LIVE_SYNC_ENABLED: "false",
  };
}

function runMigration(artifactDir, env) {
  const python = pythonBin();
  const result = spawnSync(python, ["-m", "alembic", "upgrade", "head"], {
    cwd: BACKEND_ROOT,
    env,
    encoding: "utf8",
    timeout: 120000,
    maxBuffer: 12 * 1024 * 1024,
  });
  return {
    command: `${python} -m alembic upgrade head`,
    exitCode: result.status,
    stdout: String(result.stdout || "").slice(-6000),
    stderr: String(result.stderr || "").slice(-6000),
    dbPath: path.join(artifactDir, "v24-backend.db"),
  };
}

async function apiRequest(api, method, endpoint, correlation, token = "", body = undefined, timeoutMs = 30000) {
  const startedAt = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const headers = {
    Accept: "application/json",
    "X-AI-ACQ-QA-Correlation-Id": correlation.runId,
    "X-Request-ID": correlation.runId,
    traceparent: correlation.traceparent,
    baggage: correlation.baggage,
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  try {
    const response = await fetch(`${api}${endpoint}`, {
      method,
      signal: controller.signal,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let parsedBody = null;
    try {
      parsedBody = text ? JSON.parse(text) : null;
    } catch {
      parsedBody = { raw: text.slice(0, 1000) };
    }
    const responseHeaders = {
      correlationId: response.headers.get("x-ai-acq-qa-correlation-id") || "",
      requestId: response.headers.get("x-request-id") || "",
      traceparent: response.headers.get("traceparent") || "",
      traceId: response.headers.get("x-ai-acq-trace-id") || "",
      spanId: response.headers.get("x-ai-acq-span-id") || "",
    };
    return {
      endpoint,
      method,
      ok: response.ok,
      status: response.status,
      durationMs: Date.now() - startedAt,
      headers: responseHeaders,
      body: parsedBody,
      assertions: {
        correlationEchoed: responseHeaders.correlationId === correlation.runId,
        requestIdEchoed: responseHeaders.requestId === correlation.runId,
        traceparentEchoed: responseHeaders.traceparent === correlation.traceparent,
        traceIdEchoed: responseHeaders.traceId === correlation.traceId,
        spanIdEchoed: responseHeaders.spanId === correlation.spanId,
      },
    };
  } catch (error) {
    return {
      endpoint,
      method,
      ok: false,
      status: 0,
      durationMs: Date.now() - startedAt,
      error: error.name === "AbortError" ? "request timeout" : error.message,
      headers: {},
      body: null,
      assertions: {},
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function probeHealth(api, timeoutMs = 3000) {
  const correlation = traceContext("health-probe");
  const response = await apiRequest(api, "GET", "/health", correlation, "", undefined, timeoutMs);
  return { ok: response.ok, status: response.status, error: response.error };
}

async function waitForHealth(api, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await probeHealth(api, 2500);
    if (last.ok) return last;
    await sleep(400);
  }
  return last || { ok: false, status: 0, error: "timeout" };
}

async function startBackend(options, artifactDir) {
  const port = options.backendPort || await freePort(0);
  const api = `http://127.0.0.1:${port}/api`;
  const dbPath = path.join(artifactDir, "v24-backend.db");
  const env = backendEnv(options, artifactDir, dbPath);
  const migration = runMigration(artifactDir, env);
  if (migration.exitCode !== 0) {
    return { started: false, api, port, migration, error: "migration failed", child: null };
  }

  const stdoutLog = path.join(artifactDir, "backend.stdout.log");
  const stderrLog = path.join(artifactDir, "backend.stderr.log");
  const python = pythonBin();
  const child = spawn(python, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)], {
    cwd: BACKEND_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => appendLog(stdoutLog, chunk));
  child.stderr.on("data", (chunk) => appendLog(stderrLog, chunk));
  const health = await waitForHealth(api, Math.min(options.timeoutMs, 60000));
  if (!health.ok) {
    child.kill("SIGTERM");
    return {
      started: false,
      api,
      port,
      migration,
      child: null,
      logs: { stdout: stdoutLog, stderr: stderrLog },
      error: health.error || `health HTTP ${health.status}`,
    };
  }
  return { started: true, api, port, migration, child, logs: { stdout: stdoutLog, stderr: stderrLog }, health };
}

async function runAuthFlow(api, options, correlation) {
  const login = await apiRequest(
    api,
    "POST",
    "/auth/login",
    correlation,
    "",
    { identifier: options.authUsername, password: options.authPassword },
    Math.min(options.timeoutMs, 30000),
  );
  const token = login.body?.accessToken || login.body?.access_token || "";
  const me = token
    ? await apiRequest(api, "GET", "/auth/me", correlation, token, undefined, Math.min(options.timeoutMs, 30000))
    : null;
  const user = me?.body || null;
  return {
    login,
    me,
    token,
    user,
    assertions: {
      loginAccepted: login.ok,
      tokenIssued: Boolean(token),
      meAccepted: Boolean(me?.ok),
      usernameMatches: user?.username === options.authUsername,
      loginCorrelationEchoed: Object.values(login.assertions || {}).every(Boolean),
      meCorrelationEchoed: me ? Object.values(me.assertions || {}).every(Boolean) : false,
    },
  };
}

function listLength(response) {
  return Array.isArray(response?.body) ? response.body.length : null;
}

function containsId(response, id) {
  return Array.isArray(response?.body) && response.body.some((item) => item?.id === id);
}

async function runStatefulFlow(api, options, correlation, auth) {
  if (!auth.token) {
    return { skipped: true, reason: "missing auth token", status: "fail", steps: {}, assertions: {} };
  }
  if (options.noStartBackend && !options.allowExistingApiWrites) {
    return {
      skipped: true,
      reason: "existing API writes require --allow-existing-api-writes",
      status: "warn",
      steps: {},
      assertions: { existingApiWriteGuarded: true },
    };
  }

  const runSuffix = correlation.runId.slice(0, 8);
  const source = `V24 QA ${runSuffix}`;
  const phone = `1390000${String(Math.floor(Math.random() * 10000)).padStart(4, "0")}`;
  const leadPayload = {
    name: `V24真实流程测试商户-${runSuffix}`,
    platform: "高德",
    city: "南昌",
    category: "本地生活",
    phone,
    contactName: "测试负责人",
    contactTitle: "店长",
    platformUrl: `https://example.test/v24/${runSuffix}`,
    source,
    intentScore: 88,
    status: "待外呼",
    followUpStatus: "未跟进",
    remark: "V24 isolated stateful QA lead; do not call.",
  };

  const beforeLeads = await apiRequest(api, "GET", "/leads", correlation, auth.token);
  const beforeTasks = await apiRequest(api, "GET", "/outbound/tasks", correlation, auth.token);
  const beforeRecords = await apiRequest(api, "GET", "/outbound/records", correlation, auth.token);
  const createLead = await apiRequest(api, "POST", "/leads", correlation, auth.token, leadPayload);
  const lead = createLead.body || {};
  const afterLeads = await apiRequest(api, "GET", `/leads?source=${encodeURIComponent(source)}`, correlation, auth.token);
  const taskPayload = {
    name: `V24真实外呼任务-${runSuffix}`,
    leadIds: lead.id ? [lead.id] : ["missing-lead-id"],
    concurrency: 1,
  };
  const createTask = lead.id
    ? await apiRequest(api, "POST", "/outbound/tasks", correlation, auth.token, taskPayload)
    : { ok: false, status: 0, endpoint: "/outbound/tasks", method: "POST", error: "lead create did not return id", body: null, assertions: {} };
  const task = createTask.body || {};
  const afterTasks = await apiRequest(api, "GET", "/outbound/tasks", correlation, auth.token);
  const afterRecords = await apiRequest(api, "GET", "/outbound/records", correlation, auth.token);
  const correlatedSteps = [beforeLeads, beforeTasks, beforeRecords, createLead, afterLeads, createTask, afterTasks, afterRecords];
  const echoed = correlatedSteps.filter((step) => Object.values(step.assertions || {}).every(Boolean)).length;

  const assertions = {
    leadCreated: Boolean(createLead.ok && lead.id),
    leadOwnerBoundToLoginUser: lead.ownerUserId === auth.user?.id && lead.createdByUserId === auth.user?.id,
    leadVisibleAfterCreate: containsId(afterLeads, lead.id),
    taskCreated: Boolean(createTask.ok && task.id),
    taskUsesCreatedLead: task.targetCount === 1 && task.channel === "call",
    taskWaitsForExplicitStart: task.status === "待启动",
    taskVisibleAfterCreate: containsId(afterTasks, task.id),
    noCallRecordSideEffect: beforeRecords.ok && afterRecords.ok && listLength(beforeRecords) === listLength(afterRecords),
    correlationEchoedOnStateSteps: echoed === correlatedSteps.length,
  };
  const failed = Object.entries(assertions).filter(([, value]) => !value).map(([name]) => name);
  return {
    skipped: false,
    source,
    status: failed.length ? "fail" : "pass",
    counts: {
      beforeLeads: listLength(beforeLeads),
      afterLeads: listLength(afterLeads),
      beforeTasks: listLength(beforeTasks),
      afterTasks: listLength(afterTasks),
      beforeRecords: listLength(beforeRecords),
      afterRecords: listLength(afterRecords),
      correlationEchoed: echoed,
      correlationTotal: correlatedSteps.length,
    },
    created: {
      leadId: lead.id || "",
      taskId: task.id || "",
      ownerUserId: lead.ownerUserId || "",
      createdByUserId: lead.createdByUserId || "",
      taskStatus: task.status || "",
    },
    steps: {
      beforeLeads,
      beforeTasks,
      beforeRecords,
      createLead,
      afterLeads,
      createTask,
      afterTasks,
      afterRecords,
    },
    assertions,
    failed,
  };
}

async function runPropagationChecks(api, correlation, token) {
  const endpoints = [
    ["/health", ""],
    ["/auth/me", token],
    ["/leads", token],
    ["/outbound/tasks", token],
    ["/collections/tasks", token],
  ];
  const checks = [];
  for (const [endpoint, authToken] of endpoints) {
    checks.push(await apiRequest(api, "GET", endpoint, correlation, authToken));
  }
  const passed = checks.filter((check) => Object.values(check.assertions || {}).every(Boolean)).length;
  return {
    checks,
    passed,
    total: checks.length,
    status: passed === checks.length ? "pass" : passed > 0 ? "warn" : "fail",
  };
}

function runV22(options, artifactDir, api, correlation, authToken) {
  const args = [
    "scripts/correlation-v22-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    path.join(artifactDir, "v22"),
    "--api",
    api,
  ];
  if (authToken) args.push("--auth-token", authToken);
  if (options.fromReport) args.push("--from-report", options.fromReport);
  if (options.batch) args.push("--batch");
  if (options.live) args.push("--live");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: {
      ...process.env,
      AI_ACQ_QA_CORRELATION_ID: correlation.runId,
      AI_ACQ_QA_TRACEPARENT: correlation.traceparent,
      AI_ACQ_QA_AUTH_TOKEN: authToken,
    },
    encoding: "utf8",
    maxBuffer: 80 * 1024 * 1024,
    timeout: 18 * 60 * 1000,
  });
  let report = null;
  let parseError = null;
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }
  const redactedArgs = args.map((arg, index) => (args[index - 1] === "--auth-token" ? "[redacted]" : arg));
  return {
    command: `${process.execPath} ${redactedArgs.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-4000),
    stderrTail: String(result.stderr || "").slice(-4000),
  };
}

function boolScore(value, points) {
  return value ? points : 0;
}

function evaluate(report) {
  const backendReady = report.backend.mode === "temporary" ? report.backend.started : report.backend.health?.ok;
  const authAssertions = report.auth?.assertions || {};
  const stateAssertions = report.stateful?.assertions || {};
  const authPassed = Object.values(authAssertions).every(Boolean);
  const stateSkippedGuard = report.stateful?.skipped && report.stateful?.assertions?.existingApiWriteGuarded;
  const statePassed = !report.stateful?.skipped && Object.values(stateAssertions).every(Boolean);
  const propagation = report.propagation || { passed: 0, total: 1, status: "fail" };
  const v22 = report.v22?.summary || {};
  const v22AuthProbeOk = Boolean(report.v22?.probes?.auth?.ok);
  const authBrokenEdgeStillTop = report.v22?.summary?.topBrokenEdge?.from === "backend_api"
    && report.v22?.summary?.topBrokenEdge?.to === "auth_account";
  const v22Authenticated = v22AuthProbeOk && !authBrokenEdgeStillTop;

  const dimensions = {
    backendRuntime: {
      status: backendReady ? "pass" : "fail",
      score: boolScore(backendReady, 10),
      detail: report.backend.mode === "temporary" ? `temporary backend started=${report.backend.started}` : `existing API health=${report.backend.health?.ok}`,
    },
    authenticatedSession: {
      status: authPassed ? "pass" : "fail",
      score: boolScore(authAssertions.loginAccepted, 5)
        + boolScore(authAssertions.tokenIssued, 5)
        + boolScore(authAssertions.meAccepted, 5)
        + boolScore(authAssertions.usernameMatches, 3)
        + boolScore(authAssertions.meCorrelationEchoed, 2),
      detail: `login=${authAssertions.loginAccepted}, token=${authAssertions.tokenIssued}, me=${authAssertions.meAccepted}, user=${authAssertions.usernameMatches}`,
    },
    statefulBusinessFlow: {
      status: statePassed ? "pass" : stateSkippedGuard ? "warn" : "fail",
      score: statePassed
        ? 30
        : stateSkippedGuard
          ? 12
          : Object.values(stateAssertions).filter(Boolean).length * 3,
      detail: statePassed
        ? `lead=${report.stateful.created.leadId}, task=${report.stateful.created.taskId}`
        : report.stateful?.reason || `failed=${(report.stateful?.failed || []).join(", ")}`,
    },
    correlationPropagation: {
      status: propagation.status,
      score: Math.round((propagation.passed / Math.max(1, propagation.total)) * 15),
      detail: `header echo checks passed ${propagation.passed}/${propagation.total}`,
    },
    v22AuthenticatedChain: {
      status: v22Authenticated && v22.canClaimToolingReady ? "pass" : v22Authenticated ? "warn" : "fail",
      score: boolScore(v22AuthProbeOk, 6)
        + boolScore(!authBrokenEdgeStillTop, 4)
        + boolScore(v22.canClaimToolingReady, 6)
        + Math.min(4, Math.round(Number(v22.runtimeReadinessScore || 0) / 25)),
      detail: `V22 authProbe=${v22AuthProbeOk}, topBroken=${v22.topBrokenEdge?.from || ""}->${v22.topBrokenEdge?.to || ""}, tooling=${v22.canClaimToolingReady}`,
    },
    speed: {
      status: report.v22Execution?.durationMs && report.v22Execution.durationMs < 60000 ? "pass" : "warn",
      score: report.v22Execution?.durationMs && report.v22Execution.durationMs < 60000 ? 5 : 3,
      detail: report.v22Execution?.durationMs ? `${report.v22Execution.durationMs}ms` : "V22 skipped or unavailable",
    },
  };
  const score = Object.values(dimensions).reduce((sum, item) => sum + item.score, 0);
  const hardFailure = !backendReady || !authPassed || (!statePassed && !stateSkippedGuard) || report.v22Execution?.parseError;
  return {
    status: hardFailure ? "fail" : v22.canClaimRealBusinessReady ? "pass" : "warn",
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: backendReady && authPassed && statePassed && v22.canClaimToolingReady,
      canClaimRealBusinessReady: Boolean(v22.canClaimRealBusinessReady) && statePassed,
      liveActionsStillGated: true,
      authNoLongerTopBrokenEdge: v22Authenticated,
      statefulWritesIsolated: report.backend.mode === "temporary",
    },
    nextBrokenEdge: v22.topBrokenEdge || null,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V24 Authenticated Stateful Correlation QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Correlation: ${report.correlation.runId}`);
  lines.push(`API: ${report.target.api}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Auth And State");
  lines.push(`- login user: ${report.target.authUsername}`);
  lines.push(`- lead: ${report.stateful?.created?.leadId || ""}`);
  lines.push(`- task: ${report.stateful?.created?.taskId || ""}`);
  lines.push(`- state status: ${report.stateful?.status || report.stateful?.reason || "missing"}`);
  lines.push("");
  lines.push("## Next Broken Edge");
  if (report.summary.nextBrokenEdge) {
    const edge = report.summary.nextBrokenEdge;
    lines.push(`- ${edge.from} -> ${edge.to}: ${edge.status}; ${edge.action || edge.evidence || ""}`);
  } else {
    lines.push("- none");
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V24 report: ${report.artifacts.report}`);
  lines.push(`- V22 report: ${report.v22?.artifacts?.report || ""}`);
  lines.push(`- V22 correlation: ${report.v22?.artifacts?.markdown || ""}`);
  if (report.backend.logs?.stdout) lines.push(`- Backend stdout: ${report.backend.logs.stdout}`);
  if (report.backend.logs?.stderr) lines.push(`- Backend stderr: ${report.backend.logs.stderr}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const correlation = traceContext(randomUUID());
  let backend = {
    mode: options.noStartBackend ? "existing" : "temporary",
    started: false,
    api: options.api,
    child: null,
    health: null,
    logs: null,
  };

  try {
    if (options.noStartBackend) {
      backend.health = await probeHealth(options.api, 5000);
    } else {
      backend = { ...backend, ...(await startBackend(options, artifactDir)) };
    }

    const api = backend.api || options.api;
    const report = {
      version: "V24",
      generatedAt: new Date().toISOString(),
      project: "ai_acq/frontend",
      target: {
        api,
        repeat: options.repeat,
        intervalMs: options.intervalMs,
        batch: options.batch,
        live: options.live,
        noStartBackend: options.noStartBackend,
        allowExistingApiWrites: options.allowExistingApiWrites,
        authUsername: options.authUsername,
        passThrough: options.passThrough,
      },
      researchBasis: [
        "Playwright authenticated testing patterns reuse a real login token/state before exercising protected workflows.",
        "API tests should share request context, authentication, and setup/teardown data so failures identify the blocked service boundary.",
        "Trace context and correlation headers should be asserted through protected and state-changing endpoints, not only public health checks.",
      ],
      correlation,
      backend: { ...backend, child: undefined },
      auth: null,
      stateful: null,
      propagation: { checks: [], passed: 0, total: 0, status: "fail" },
      v22Execution: null,
      v22: null,
      evaluation: null,
      summary: null,
      artifacts: {
        root: artifactDir,
        report: path.join(artifactDir, "report.json"),
        markdown: path.join(artifactDir, "correlation.md"),
      },
    };

    if (backend.started || options.noStartBackend) {
      report.auth = await runAuthFlow(api, options, correlation);
      report.stateful = await runStatefulFlow(api, options, correlation, report.auth);
      report.propagation = await runPropagationChecks(api, correlation, report.auth.token);
    }

    if (!options.skipV22) {
      report.v22Execution = runV22(options, artifactDir, api, correlation, report.auth?.token || "");
      report.v22 = report.v22Execution.report;
    }

    report.evaluation = evaluate(report);
    report.summary = {
      status: report.evaluation.status,
      score: report.evaluation.score,
      canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
      canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
      authNoLongerTopBrokenEdge: report.evaluation.readinessDecision.authNoLongerTopBrokenEdge,
      statefulWritesIsolated: report.evaluation.readinessDecision.statefulWritesIsolated,
      propagationPassed: report.propagation.passed,
      propagationTotal: report.propagation.total,
      statefulStatus: report.stateful?.status || "missing",
      nextBrokenEdge: report.evaluation.nextBrokenEdge,
      v22Report: report.v22?.artifacts?.report || "",
    };

    await writeJson(report.artifacts.report, report);
    await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

    if (options.json) {
      console.log(JSON.stringify(redact(report), null, 2));
    } else {
      console.log(`V24 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
      console.log(`Auth top broken fixed: ${report.summary.authNoLongerTopBrokenEdge}`);
      console.log(`Stateful flow: ${report.summary.statefulStatus}`);
      console.log(`Report: ${report.artifacts.report}`);
      console.log(`Correlation: ${report.artifacts.markdown}`);
    }

    process.exitCode = report.summary.status === "fail" ? 1 : 0;
  } finally {
    if (backend.child && !options.keepBackend) {
      backend.child.kill("SIGTERM");
      await sleep(300);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
