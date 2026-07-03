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
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v23-correlated-backend-qa");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

const ownOptionsWithValue = new Set([
  "--repeat",
  "--interval-ms",
  "--artifact-root",
  "--from-report",
  "--api",
  "--timeout-ms",
  "--mode",
  "--backend-port",
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
    json: false,
    batch: false,
    live: false,
    skipV22: false,
    noStartBackend: false,
    keepBackend: false,
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
  console.log(`AI ACQ V23 correlated backend QA

Default: start an isolated local backend with a temporary SQLite DB, verify correlation header propagation, then run V22 through that backend.
  npm run qa:v23 -- --repeat 2

Use an existing API instead of starting a temporary backend:
  npm run qa:v23 -- --no-start-backend --api http://127.0.0.1:8017/api

Batch readiness:
  npm run qa:v23:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1
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

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
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
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V23`,
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
  const venvPython = path.join(BACKEND_ROOT, ".venv", "bin", "python");
  return venvPython;
}

async function appendLog(file, chunk) {
  await fs.appendFile(file, chunk.toString(), "utf8").catch(() => {});
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function probeHealth(api, timeoutMs = 3000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${api}/health`, { signal: controller.signal, headers: { Accept: "application/json" } });
    return { ok: response.ok, status: response.status };
  } catch (error) {
    return { ok: false, status: 0, error: error.name === "AbortError" ? "timeout" : error.message };
  } finally {
    clearTimeout(timeout);
  }
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
    dbPath: path.join(artifactDir, "v23-backend.db"),
  };
}

async function startBackend(options, artifactDir) {
  const port = options.backendPort || await freePort(0);
  const api = `http://127.0.0.1:${port}/api`;
  const dbPath = path.join(artifactDir, "v23-backend.db");
  const env = {
    ...process.env,
    DATABASE_URL: `sqlite:///${dbPath}`,
    BROWSER_PROFILE_ROOT: path.join(artifactDir, "browser-profiles"),
    DM_BROWSER_PROFILE_ROOT: path.join(artifactDir, "dm-browser-profiles"),
    VOICE_SAMPLE_STORAGE_ROOT: path.join(artifactDir, "voice-samples"),
    VOICE_OUTPUT_STORAGE_ROOT: path.join(artifactDir, "voice-outputs"),
    INITIAL_CLIENT_USERNAME: "v23_client",
    INITIAL_CLIENT_PASSWORD: "v23-client-password",
    INITIAL_CLIENT_DISPLAY_NAME: "V23 QA Client",
    ASTERISK_LIVE_CALL_ENABLED: "false",
    ASTERISK_BULK_CALL_ENABLED: "false",
  };
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

async function correlationProbe(api, endpoint, correlation) {
  const response = await fetch(`${api}${endpoint}`, {
    headers: {
      Accept: "application/json",
      "X-AI-ACQ-QA-Correlation-Id": correlation.runId,
      "X-Request-ID": correlation.runId,
      traceparent: correlation.traceparent,
      baggage: correlation.baggage,
    },
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text.slice(0, 1000) };
  }
  const headers = {
    correlationId: response.headers.get("x-ai-acq-qa-correlation-id") || "",
    requestId: response.headers.get("x-request-id") || "",
    traceparent: response.headers.get("traceparent") || "",
    traceId: response.headers.get("x-ai-acq-trace-id") || "",
    spanId: response.headers.get("x-ai-acq-span-id") || "",
  };
  return {
    endpoint,
    ok: response.ok,
    status: response.status,
    headers,
    body,
    assertions: {
      correlationEchoed: headers.correlationId === correlation.runId,
      requestIdEchoed: headers.requestId === correlation.runId,
      traceparentEchoed: headers.traceparent === correlation.traceparent,
      traceIdEchoed: headers.traceId === correlation.traceId,
      spanIdEchoed: headers.spanId === correlation.spanId,
    },
  };
}

async function runPropagationChecks(api, correlation) {
  const endpoints = ["/health", "/outbound/telephony/config", "/outbound/realtime/pipeline", "/direct-messages/config"];
  const checks = [];
  for (const endpoint of endpoints) {
    try {
      checks.push(await correlationProbe(api, endpoint, correlation));
    } catch (error) {
      checks.push({ endpoint, ok: false, status: 0, error: error.message, assertions: {} });
    }
  }
  const passed = checks.filter((check) => Object.values(check.assertions || {}).every(Boolean)).length;
  return {
    checks,
    passed,
    total: checks.length,
    status: passed === checks.length ? "pass" : passed > 0 ? "warn" : "fail",
  };
}

function runV22(options, artifactDir, api, correlation) {
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
    },
    encoding: "utf8",
    maxBuffer: 70 * 1024 * 1024,
    timeout: 18 * 60 * 1000,
  });
  let report = null;
  let parseError = null;
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }
  return {
    command: `${process.execPath} ${args.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-4000),
    stderrTail: String(result.stderr || "").slice(-4000),
  };
}

function evaluate(report) {
  const propagation = report.propagation;
  const v22Summary = report.v22?.summary || {};
  const backendReady = report.backend.mode === "temporary" ? report.backend.started : report.backend.health?.ok;
  const propagationScore = Math.round((propagation.passed / Math.max(1, propagation.total)) * 35);
  const backendScore = backendReady ? 15 : 0;
  const v22ToolingScore = v22Summary.canClaimToolingReady ? 30 : 10;
  const v22RuntimeScore = Math.min(15, Math.round((Number(v22Summary.runtimeReadinessScore || 0) / 100) * 15));
  const speedScore = report.v22Execution?.durationMs && report.v22Execution.durationMs < 60000 ? 5 : 3;
  const score = propagationScore + backendScore + v22ToolingScore + v22RuntimeScore + speedScore;
  const status = !backendReady || propagation.status === "fail" || report.v22Execution?.parseError
    ? "fail"
    : v22Summary.canClaimRealBusinessReady
      ? "pass"
      : "warn";
  return {
    status,
    score,
    dimensions: {
      backendRuntime: {
        status: backendReady ? "pass" : "fail",
        score: backendScore,
        detail: report.backend.mode === "temporary" ? `temporary backend started=${report.backend.started}` : `existing API health=${report.backend.health?.ok}`,
      },
      correlationPropagation: {
        status: propagation.status,
        score: propagationScore,
        detail: `header echo checks passed ${propagation.passed}/${propagation.total}`,
      },
      v22Tooling: {
        status: v22Summary.canClaimToolingReady ? "pass" : "fail",
        score: v22ToolingScore,
        detail: `V22 status=${v22Summary.status}, score=${v22Summary.score}`,
      },
      runtimeReadiness: {
        status: v22Summary.runtimeReadinessScore > 0 ? "warn" : "fail",
        score: v22RuntimeScore,
        detail: `V22 runtimeReadinessScore=${v22Summary.runtimeReadinessScore ?? "missing"}`,
      },
      speed: {
        status: speedScore === 5 ? "pass" : "warn",
        score: speedScore,
        detail: report.v22Execution?.durationMs ? `${report.v22Execution.durationMs}ms` : "existing report evaluation",
      },
    },
    readinessDecision: {
      canClaimToolingReady: backendReady && propagation.status === "pass" && Boolean(v22Summary.canClaimToolingReady),
      canClaimRealBusinessReady: Boolean(v22Summary.canClaimRealBusinessReady),
      liveActionsStillGated: true,
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V23 Correlated Backend QA");
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
  lines.push("## Propagation Checks");
  for (const check of report.propagation.checks) {
    const ok = Object.values(check.assertions || {}).every(Boolean);
    lines.push(`- ${check.endpoint}: ${ok ? "pass" : "fail"} HTTP ${check.status || 0}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V23 report: ${report.artifacts.report}`);
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
      version: "V23",
      generatedAt: new Date().toISOString(),
      project: "ai_acq/frontend",
      target: {
        api,
        repeat: options.repeat,
        intervalMs: options.intervalMs,
        batch: options.batch,
        live: options.live,
        noStartBackend: options.noStartBackend,
        passThrough: options.passThrough,
      },
      researchBasis: [
        "Distributed tracing is only useful when request context is propagated across service boundaries.",
        "QA correlation should be asserted by runtime response headers, not only by generated report IDs.",
        "A temporary isolated backend makes the correlation contract deterministic without touching production data or live devices.",
      ],
      correlation,
      backend: { ...backend, child: undefined },
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
      report.propagation = await runPropagationChecks(api, correlation);
    }

    if (!options.skipV22) {
      report.v22Execution = runV22(options, artifactDir, api, correlation);
      report.v22 = report.v22Execution.report;
    }

    report.evaluation = evaluate(report);
    report.summary = {
      status: report.evaluation.status,
      score: report.evaluation.score,
      canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
      canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
      propagationPassed: report.propagation.passed,
      propagationTotal: report.propagation.total,
      v22Report: report.v22?.artifacts?.report || "",
    };

    await writeJson(report.artifacts.report, report);
    await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

    if (options.json) {
      console.log(JSON.stringify(redact(report), null, 2));
    } else {
      console.log(`V23 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
      console.log(`Propagation: ${report.summary.propagationPassed}/${report.summary.propagationTotal}`);
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
