#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v27-collector-stateful-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    timeoutMs: 180000,
    fromReport: "",
    json: false,
    batch: false,
    skipV26: false,
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
    } else if (arg === "--skip-v26") {
      options.skipV26 = true;
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
  console.log(`AI ACQ V27 collector stateful UI coverage QA

Default: run V26, then prove the 线索采集 module has a real UI create/read journey:
  npm run qa:v27 -- --repeat 2

Evaluate an existing V26 report:
  npm run qa:v27 -- --from-report .playwright-cli/v26-coverage-matrix-qa/<run>/report.json

Batch composition keeps live calls/sends gated and only checks safe coverage evidence:
  npm run qa:v27:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
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

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/.test(normalized);
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

function runV26(options, artifactDir) {
  const args = [
    "scripts/coverage-matrix-v26-qa.mjs",
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

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 140 * 1024 * 1024,
    timeout: 30 * 60 * 1000,
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

function checkByName(report, pattern) {
  return (report?.checks || []).find((check) => pattern.test(`${check.name || ""} ${check.detail || ""}`)) || null;
}

function checksByName(report, pattern) {
  return (report?.checks || []).filter((check) => pattern.test(`${check.name || ""} ${check.detail || ""}`));
}

function collectionApiResponses(v17) {
  return (v17?.browser?.apiResponses || []).filter((item) => /\/api\/collections\//.test(item.url || ""));
}

function routeRow(v26, method, routePath) {
  return (v26?.coverage?.routes?.rows || []).find((item) => item.method === method && item.path === routePath) || null;
}

function moduleRow(v26, key) {
  return (v26?.coverage?.modules || []).find((item) => item.key === key || item.name === "线索采集") || null;
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

async function extractCollectorEvidence(v26) {
  const v25 = v26?.v25 || {};
  const v17 = v25?.v17 || {};
  const collectorModule = moduleRow(v26, "collector");
  const collectionResponses = collectionApiResponses(v17);
  const echoedCollectionResponses = collectionResponses.filter((item) => item.correlationEchoed === true);
  const createRoute = routeRow(v26, "POST", "/collections/tasks");
  const listRoute = routeRow(v26, "GET", "/collections/tasks");
  const runRoute = routeRow(v26, "POST", "/collections/tasks/:param/run");
  const runRows = (v26?.coverage?.routes?.rows || []).filter((item) => /^\/collections\/tasks\/:param\/run$/.test(item.path || ""));
  const uiCreated = checkByName(v17, /线索采集任务创建后队列出现/);
  const apiCreated = checkByName(v17, /线索采集任务写入隔离数据库/);
  const ownerScoped = checkByName(v17, /采集任务归属当前用户/);
  const noProviderRun = checkByName(v17, /采集任务只创建不运行/);
  const noLeadSideEffect = checkByName(v17, /采集创建不产生线索副作用/);
  const safetyChecks = checksByName(v17, /安全门控/);
  const screenshots = v17?.artifacts?.screenshots || [];
  const trace = v17?.artifacts?.trace || "";
  const traceExists = await pathExists(trace);
  const collectorScreenshot = screenshots.find((item) => /collection-task-created/.test(item)) || "";
  const collectorScreenshotExists = await pathExists(collectorScreenshot);

  return {
    module: collectorModule,
    routes: {
      listTasks: listRoute,
      createTask: createRoute,
      runTask: runRoute,
      dangerousRunCovered: runRows.some((item) => item.covered),
    },
    uiReplay: {
      createdTaskName: v17?.state?.created?.collectionTaskName || "",
      createdTaskId: v17?.state?.created?.collectionTaskId || "",
      uiCreated,
      apiCreated,
      ownerScoped,
      noProviderRun,
      noLeadSideEffect,
      safetyChecks,
    },
    correlation: {
      collectionApiResponses: collectionResponses.length,
      echoedCollectionResponses: echoedCollectionResponses.length,
      sample: echoedCollectionResponses.slice(0, 5),
    },
    artifacts: {
      v26Report: v26?.artifacts?.report || "",
      v26Matrix: v26?.artifacts?.matrix || "",
      v25Report: v25?.artifacts?.report || "",
      v17Report: v17?.artifacts?.report || "",
      trace,
      traceExists,
      collectorScreenshot,
      collectorScreenshotExists,
      screenshots: screenshots.length,
    },
  };
}

function evaluate(report) {
  const evidence = report.collectorEvidence;
  const dimensions = {
    v26ToolingEvidence: {
      status: report.v26?.summary?.canClaimToolingReady ? "pass" : "fail",
      score: report.v26?.summary?.canClaimToolingReady ? 15 : 0,
      detail: `V26 toolingReady=${Boolean(report.v26?.summary?.canClaimToolingReady)}`,
    },
    collectorMatrixStatus: {
      status: evidence.module?.status === "stateful-ui" ? "pass" : "fail",
      score: evidence.module?.status === "stateful-ui" ? 20 : 0,
      detail: `collector status=${evidence.module?.status || "missing"}, read=${evidence.module?.coveredReadRoutes || 0}/${evidence.module?.readRoutes || 0}, safeMutations=${evidence.module?.coveredSafeMutations || 0}`,
    },
    routeCoverage: {
      status: evidence.routes.createTask?.covered && evidence.routes.listTasks?.covered ? "pass" : "fail",
      score: evidence.routes.createTask?.covered && evidence.routes.listTasks?.covered ? 15 : 0,
      detail: `GET /collections/tasks=${Boolean(evidence.routes.listTasks?.covered)}, POST /collections/tasks=${Boolean(evidence.routes.createTask?.covered)}`,
    },
    uiStatefulReplay: {
      status: evidence.uiReplay.uiCreated?.status === "pass" && evidence.uiReplay.apiCreated?.status === "pass" ? "pass" : "fail",
      score: evidence.uiReplay.uiCreated?.status === "pass" && evidence.uiReplay.apiCreated?.status === "pass" ? 15 : 0,
      detail: `task=${evidence.uiReplay.createdTaskName || "missing"}, ui=${evidence.uiReplay.uiCreated?.status || "missing"}, api=${evidence.uiReplay.apiCreated?.status || "missing"}`,
    },
    ownershipAndIsolation: {
      status: evidence.uiReplay.ownerScoped?.status === "pass" ? "pass" : "fail",
      score: evidence.uiReplay.ownerScoped?.status === "pass" ? 10 : 0,
      detail: evidence.uiReplay.ownerScoped?.detail || "owner/createdBy evidence missing",
    },
    noProviderSideEffects: {
      status: evidence.uiReplay.noProviderRun?.status === "pass"
        && evidence.uiReplay.noLeadSideEffect?.status === "pass"
        && !evidence.routes.dangerousRunCovered
        ? "pass"
        : "fail",
      score: evidence.uiReplay.noProviderRun?.status === "pass"
        && evidence.uiReplay.noLeadSideEffect?.status === "pass"
        && !evidence.routes.dangerousRunCovered
        ? 15
        : 0,
      detail: `noRun=${evidence.uiReplay.noProviderRun?.status || "missing"}, noLeadSideEffect=${evidence.uiReplay.noLeadSideEffect?.status || "missing"}, runRouteCovered=${evidence.routes.dangerousRunCovered}`,
    },
    traceAndCorrelation: {
      status: evidence.artifacts.traceExists
        && evidence.artifacts.collectorScreenshotExists
        && evidence.correlation.echoedCollectionResponses >= 2
        ? "pass"
        : "warn",
      score: evidence.artifacts.traceExists
        ? Math.min(10, 4 + Math.min(4, evidence.correlation.echoedCollectionResponses) + (evidence.artifacts.collectorScreenshotExists ? 2 : 0))
        : 0,
      detail: `trace=${evidence.artifacts.traceExists}, screenshot=${evidence.artifacts.collectorScreenshotExists}, collectionEcho=${evidence.correlation.echoedCollectionResponses}/${evidence.correlation.collectionApiResponses}`,
    },
    nextJourneyAdvanced: {
      status: report.v26?.summary?.nextJourney?.module !== "线索采集" ? "pass" : "warn",
      score: report.v26?.summary?.nextJourney?.module !== "线索采集" ? 5 : 2,
      detail: `next=${report.v26?.summary?.nextJourney?.module || "none"}`,
    },
  };

  const score = Math.min(100, Object.values(dimensions).reduce((sum, item) => sum + item.score, 0));
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  const collectorStatefulReady = !hardFailure;

  return {
    status: hardFailure ? "fail" : report.v26?.summary?.canClaimRealBusinessReady ? "pass" : "warn",
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure && Boolean(report.v26?.summary?.canClaimToolingReady),
      canClaimCollectorStatefulUi: collectorStatefulReady,
      canClaimBroadBusinessCoverage: Boolean(report.v26?.summary?.canClaimBroadBusinessCoverage),
      canClaimRealBusinessReady: Boolean(report.v26?.summary?.canClaimRealBusinessReady),
      liveActionsStillGated: true,
      nextJourney: report.v26?.summary?.nextJourney || null,
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V27 Collector Stateful UI QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Collector stateful UI ready: ${report.summary.canClaimCollectorStatefulUi}`);
  lines.push(`Broad business coverage: ${report.summary.canClaimBroadBusinessCoverage}`);
  lines.push(`Real business ready: ${report.summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Collector Evidence");
  lines.push(`- Created task: ${report.collectorEvidence.uiReplay.createdTaskName || ""}`);
  lines.push(`- Created task id: ${report.collectorEvidence.uiReplay.createdTaskId || ""}`);
  lines.push(`- Matrix status: ${report.collectorEvidence.module?.status || "missing"}`);
  lines.push(`- GET /collections/tasks covered: ${Boolean(report.collectorEvidence.routes.listTasks?.covered)}`);
  lines.push(`- POST /collections/tasks covered: ${Boolean(report.collectorEvidence.routes.createTask?.covered)}`);
  lines.push(`- Provider run route covered: ${report.collectorEvidence.routes.dangerousRunCovered}`);
  lines.push(`- Collection API correlation echo: ${report.collectorEvidence.correlation.echoedCollectionResponses}/${report.collectorEvidence.correlation.collectionApiResponses}`);
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V27 report: ${report.artifacts.report}`);
  lines.push(`- V27 markdown: ${report.artifacts.markdown}`);
  lines.push(`- V26 report: ${report.collectorEvidence.artifacts.v26Report}`);
  lines.push(`- V26 matrix: ${report.collectorEvidence.artifacts.v26Matrix}`);
  lines.push(`- V25 report: ${report.collectorEvidence.artifacts.v25Report}`);
  lines.push(`- V17 report: ${report.collectorEvidence.artifacts.v17Report}`);
  lines.push(`- V17 trace: ${report.collectorEvidence.artifacts.trace}`);
  lines.push(`- Collector screenshot: ${report.collectorEvidence.artifacts.collectorScreenshot}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const startedAt = Date.now();

  const report = {
    version: "V27",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV26: options.skipV26,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Playwright recommends isolated browser contexts, user-facing locators, trace artifacts, and API state assertions for durable end-to-end testing.",
      "OpenTelemetry and W3C Trace Context patterns make UI, API, and backend evidence comparable through shared correlation ids and traceparent headers.",
      "A broad coverage matrix should promote the highest-risk uncovered journey into a dedicated stateful UI gate before claiming product-wide testing strength.",
    ],
    v26Execution: null,
    v26: null,
    collectorEvidence: null,
    durationMs: 0,
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "collector.md"),
    },
  };

  if (options.fromReport) {
    report.v26 = await readJson(options.fromReport);
    report.v26Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV26) {
    report.v26Execution = runV26(options, path.join(artifactDir, "v26"));
    report.v26 = report.v26Execution.report;
  }

  if (!report.v26) {
    report.v26 = { summary: { canClaimToolingReady: false }, coverage: { modules: [], routes: { rows: [] } } };
  }

  report.collectorEvidence = await extractCollectorEvidence(report.v26);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimCollectorStatefulUi: report.evaluation.readinessDecision.canClaimCollectorStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v26Report: report.v26?.artifacts?.report || options.fromReport || "",
    v17Trace: report.collectorEvidence.artifacts.trace,
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V27 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} collectorStateful=${report.summary.canClaimCollectorStatefulUi} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    if (report.summary.nextJourney) {
      console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    }
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Collector evidence: ${report.artifacts.markdown}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
