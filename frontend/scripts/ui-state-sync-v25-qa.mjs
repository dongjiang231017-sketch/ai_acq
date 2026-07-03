#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v25-ui-state-sync-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms"]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    timeoutMs: 180000,
    json: false,
    batch: false,
    headed: false,
    skipV24: false,
    skipV17: false,
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
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--skip-v24") {
      options.skipV24 = true;
    } else if (arg === "--skip-v17") {
      options.skipV17 = true;
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
  console.log(`AI ACQ V25 UI state-sync correlation QA

Default: run V24 authenticated API/stateful correlation, then run V17 browser UI stateful replay with the same correlation id injected into browser API requests.
  npm run qa:v25 -- --repeat 2

Batch readiness composition:
  npm run qa:v25:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
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
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V25`,
  };
}

function runNodeScript(script, args, artifactDir, correlation, timeoutMs) {
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, [script, ...args], {
    cwd: FRONTEND_ROOT,
    env: {
      ...process.env,
      AI_ACQ_QA_CORRELATION_ID: correlation.runId,
      AI_ACQ_QA_TRACEPARENT: correlation.traceparent,
    },
    encoding: "utf8",
    maxBuffer: 100 * 1024 * 1024,
    timeout: timeoutMs,
  });
  let report = null;
  let parseError = null;
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }
  return {
    command: `${process.execPath} ${[script, ...args].join(" ")}`,
    artifactDir,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-5000),
    stderrTail: String(result.stderr || "").slice(-5000),
  };
}

function runV24(options, artifactDir, correlation) {
  const args = [
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    artifactDir,
  ];
  if (options.batch) args.push("--batch");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));
  return runNodeScript("scripts/correlation-v24-qa.mjs", args, artifactDir, correlation, 22 * 60 * 1000);
}

function runV17(options, artifactDir, correlation) {
  const args = [
    "--json",
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    artifactDir,
  ];
  if (options.headed) args.push("--headed");
  return runNodeScript("scripts/stateful-client-v17-qa.mjs", args, artifactDir, correlation, 20 * 60 * 1000);
}

function countChecks(report, pattern, status = "pass") {
  return (report?.checks || []).filter((check) => pattern.test(check.name || "") && (!status || check.status === status)).length;
}

function evaluate(report) {
  const v24Summary = report.v24?.summary || {};
  const v17Summary = report.v17?.summary || {};
  const v17ApiResponses = report.v17?.browser?.apiResponses || [];
  const echoedUiResponses = v17ApiResponses.filter((item) => item.correlationEchoed === true).length;
  const uiTraceExists = Boolean(report.v17?.artifacts?.trace);
  const screenshots = report.v17?.artifacts?.screenshots || [];
  const v17ConsoleClean = Number(v17Summary.consoleErrors || 0) === 0
    && Number(v17Summary.pageErrors || 0) === 0
    && Number(v17Summary.failedRequests || 0) === 0;
  const uiStateChecks = countChecks(report.v17, /UI 状态流|API 对账|安全门控/, "pass");

  const dimensions = {
    authenticatedApiState: {
      status: v24Summary.statefulStatus === "pass" && v24Summary.authNoLongerTopBrokenEdge ? "pass" : "fail",
      score: v24Summary.statefulStatus === "pass" && v24Summary.authNoLongerTopBrokenEdge ? 25 : 0,
      detail: `V24 stateful=${v24Summary.statefulStatus}, authFixed=${v24Summary.authNoLongerTopBrokenEdge}`,
    },
    browserUiReplay: {
      status: v17Summary.status && v17Summary.status !== "fail" && uiStateChecks >= 4 ? "pass" : "fail",
      score: v17Summary.status && v17Summary.status !== "fail" ? Math.min(25, uiStateChecks * 5) : 0,
      detail: `V17 status=${v17Summary.status || "missing"}, stateChecks=${uiStateChecks}`,
    },
    uiApiCorrelation: {
      status: echoedUiResponses >= 5 ? "pass" : echoedUiResponses > 0 ? "warn" : "fail",
      score: echoedUiResponses >= 5 ? 20 : echoedUiResponses > 0 ? 12 : 0,
      detail: `UI API responses echoed correlation ${echoedUiResponses}/${v17ApiResponses.length}`,
    },
    traceAndScreenshots: {
      status: uiTraceExists && screenshots.length >= 4 ? "pass" : "warn",
      score: uiTraceExists ? Math.min(15, 5 + screenshots.length * 2) : 0,
      detail: `trace=${uiTraceExists}, screenshots=${screenshots.length}`,
    },
    cleanRuntime: {
      status: v17ConsoleClean ? "pass" : "fail",
      score: v17ConsoleClean ? 10 : 0,
      detail: `console=${v17Summary.consoleErrors || 0}, page=${v17Summary.pageErrors || 0}, failedRequests=${v17Summary.failedRequests || 0}`,
    },
    speed: {
      status: report.durationMs < 90000 ? "pass" : "warn",
      score: report.durationMs < 90000 ? 5 : 3,
      detail: `${report.durationMs}ms`,
    },
  };

  const score = Object.values(dimensions).reduce((sum, item) => sum + item.score, 0);
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  return {
    status: hardFailure ? "fail" : v24Summary.canClaimRealBusinessReady ? "pass" : "warn",
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure && Boolean(v24Summary.canClaimToolingReady),
      canClaimRealBusinessReady: Boolean(v24Summary.canClaimRealBusinessReady),
      liveActionsStillGated: true,
      uiStateSyncReady: !hardFailure,
    },
    nextBrokenEdge: v24Summary.nextBrokenEdge || null,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V25 UI State-Sync Correlation QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Correlation: ${report.correlation.runId}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V25 report: ${report.artifacts.report}`);
  lines.push(`- V24 report: ${report.v24?.artifacts?.report || ""}`);
  lines.push(`- V17 report: ${report.v17?.artifacts?.report || ""}`);
  lines.push(`- V17 trace: ${report.v17?.artifacts?.trace || ""}`);
  lines.push("");
  lines.push("## Next Broken Edge");
  if (report.summary.nextBrokenEdge) {
    const edge = report.summary.nextBrokenEdge;
    lines.push(`- ${edge.from} -> ${edge.to}: ${edge.status}; ${edge.action || edge.evidence || ""}`);
  } else {
    lines.push("- none");
  }
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const startedAt = Date.now();
  const correlation = traceContext(randomUUID());
  const report = {
    version: "V25",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      skipV24: options.skipV24,
      skipV17: options.skipV17,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Playwright authentication and API testing patterns should be combined with browser trace evidence for protected workflows.",
      "Trace context is most useful when the browser's API requests, backend responses, and state assertions share the same correlation id.",
      "UI state-sync testing should prove that backend-created or UI-created business state is visible to the user without triggering live external actions.",
    ],
    correlation,
    v24Execution: null,
    v24: null,
    v17Execution: null,
    v17: null,
    durationMs: 0,
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "correlation.md"),
    },
  };

  if (!options.skipV24) {
    report.v24Execution = runV24(options, path.join(artifactDir, "v24"), correlation);
    report.v24 = report.v24Execution.report;
  }
  if (!options.skipV17) {
    report.v17Execution = runV17(options, path.join(artifactDir, "v17"), correlation);
    report.v17 = report.v17Execution.report;
  }

  report.durationMs = Date.now() - startedAt;
  report.evaluation = evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    uiStateSyncReady: report.evaluation.readinessDecision.uiStateSyncReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextBrokenEdge: report.evaluation.nextBrokenEdge,
    v24Report: report.v24?.artifacts?.report || "",
    v17Report: report.v17?.artifacts?.report || "",
    v17Trace: report.v17?.artifacts?.trace || "",
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V25 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`UI state sync ready: ${report.summary.uiStateSyncReady}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Correlation: ${report.artifacts.markdown}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
