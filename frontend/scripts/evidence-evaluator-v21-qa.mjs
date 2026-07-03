#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v21-evidence-eval-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--from-report", "--mode"]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    json: false,
    batch: false,
    live: false,
    skipV20: false,
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
      if (arg === "--mode") options.live = next === "live";
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--live") {
      options.live = true;
    } else if (arg === "--skip-v20") {
      options.skipV20 = true;
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
  console.log(`AI ACQ V21 evidence evaluator QA

Default: run V20, then evaluate tooling, UI resilience, artifact evidence, real-flow readiness, and next fix queue.
  npm run qa:v21 -- --repeat 2

Batch readiness:
  npm run qa:v21:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1

Evaluate an existing V20 report:
  npm run qa:v21 -- --from-report .playwright-cli/v20-locator-healing-qa/<run>/report.json
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

async function exists(file) {
  if (!file) return false;
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
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

function runV20(options, artifactDir) {
  const args = [
    "scripts/ui-locator-v20-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--artifact-root",
    path.join(artifactDir, "v20"),
  ];
  if (options.batch) args.push("--batch");
  if (options.live) args.push("--live");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
    timeout: 14 * 60 * 1000,
  });
  const durationMs = Date.now() - startedAt;

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
    durationMs,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-4000),
    stderrTail: String(result.stderr || "").slice(-4000),
  };
}

function blockerLayer(category) {
  const map = {
    backend_api: "backend_service",
    auth: "auth_account",
    confirmations: "operator_approval",
    real_data: "test_data",
    allowlist: "safety_allowlist",
    dm_gateway: "platform_dm",
    collection_provider: "lead_provider",
    ami: "telephony_ami",
    trunk: "telephony_trunk",
    preflight: "telephony_preflight",
    live_call_switch: "telephony_switch",
    bulk_switch: "batch_switch",
    media_bridge: "audio_bridge",
    asr_tts_llm: "ai_runtime",
    backend_events: "event_persistence",
    ui_runtime: "frontend_runtime",
    unknown: "manual_triage",
  };
  return map[category] || "manual_triage";
}

function actionFor(category) {
  const map = {
    backend_api: "Start or repair backend API; verify AI_ACQ_API_URL, port, proxy, and /api/health before rerunning V21.",
    auth: "Provide a real customer account or enable an isolated seeded account path for this test run.",
    confirmations: "Add explicit real-data/live-call/live-send/live-batch/production-write flags only for approved live actions.",
    real_data: "Provide city, category, merchant/contact/phone or configured collection source; avoid placeholder data.",
    allowlist: "Replace placeholder allowlist entries with authorized test contacts and keep max call/send caps.",
    dm_gateway: "Switch DM gateway to browser live-send, log in a supported platform account, and verify quota/risk state.",
    collection_provider: "Configure provider keys or a valid logged-in browser session; verify collected raw records before outbound actions.",
    ami: "Check Asterisk AMI host/port/credentials/manager.conf and firewall.",
    trunk: "Check PJSIP endpoint/contact, SIP gateway registration, route and line availability.",
    media_bridge: "Start AudioSocket/realtime bridge and verify dialplan routes answered calls into the bridge.",
    ui_runtime: "Open V20 trace/screenshots and inspect console/network/page errors before treating it as a product bug.",
    unknown: "Inspect nested V19/V18 checks and add a classifier if the same signature repeats.",
  };
  return map[category] || "Inspect nested evidence and add a targeted verifier before editing product code.";
}

async function artifactEvidence(v20Report) {
  const trace = v20Report?.healing?.artifacts?.trace;
  const screenshots = v20Report?.healing?.artifacts?.screenshots || [];
  const candidates = v20Report?.healing?.artifacts?.candidates;
  const nestedV19 = v20Report?.v19?.artifacts?.report;
  return {
    trace,
    traceExists: await exists(trace),
    screenshots,
    screenshotCount: screenshots.length,
    screenshotsExist: (await Promise.all(screenshots.map((item) => exists(item)))).filter(Boolean).length,
    candidates,
    candidatesExists: await exists(candidates),
    nestedV19,
    nestedV19Exists: await exists(nestedV19),
  };
}

function grade(status) {
  if (status === "pass") return 1;
  if (status === "warn") return 0.55;
  return 0;
}

function buildFixQueue(blockers) {
  return blockers.map((category, index) => ({
    rank: index + 1,
    category,
    layer: blockerLayer(category),
    action: actionFor(category),
  }));
}

async function evaluateV20(v20Report, execution) {
  const healing = v20Report?.healing?.summary || {};
  const v19 = v20Report?.v19?.summary || null;
  const artifacts = await artifactEvidence(v20Report);
  const persistentBlockers = v20Report?.summary?.persistentBlockers || v19?.persistentBlockers || [];

  const toolingIntegrity = execution?.parseError || !v20Report
    ? { status: "fail", score: 0, detail: execution?.parseError || "missing V20 report" }
    : healing.status === "pass"
      ? { status: "pass", score: 25, detail: "V20 report parsed and locator-healing contract passed" }
      : { status: "fail", score: 5, detail: "locator-healing contract failed" };

  const uiResilience = healing.status === "pass"
    ? {
        status: "pass",
        score: Math.min(20, 10 + Number(healing.healedEvents || 0) * 2),
        detail: `${healing.healedEvents || 0} healed events, ${healing.primarySelectorMisses || 0} primary selector misses recovered`,
      }
    : { status: "fail", score: 0, detail: "UI selector recovery did not pass" };

  const evidenceCompleteness = artifacts.traceExists && artifacts.screenshotCount > 0 && artifacts.screenshotsExist === artifacts.screenshotCount
    ? {
        status: artifacts.nestedV19 && !artifacts.nestedV19Exists ? "warn" : "pass",
        score: artifacts.nestedV19 && !artifacts.nestedV19Exists ? 14 : 20,
        detail: `trace=${artifacts.traceExists}, screenshots=${artifacts.screenshotsExist}/${artifacts.screenshotCount}, candidates=${artifacts.candidatesExists}, nestedV19=${artifacts.nestedV19Exists}`,
      }
    : { status: "fail", score: 5, detail: "missing trace or screenshot evidence" };

  const realFlowReadiness = {
    status: v19?.status || "skipped",
    score: Math.round(20 * grade(v19?.status || "warn")),
    detail: persistentBlockers.length ? `blocked by ${persistentBlockers.join(", ")}` : "no persistent blockers reported",
  };

  const speed = {
    status: execution?.durationMs && execution.durationMs < 45000 ? "pass" : "warn",
    score: execution?.durationMs && execution.durationMs < 45000 ? 15 : 8,
    detail: execution?.durationMs ? `${execution.durationMs}ms` : "existing report evaluation",
  };

  const dimensions = { toolingIntegrity, uiResilience, evidenceCompleteness, realFlowReadiness, speed };
  const score = Object.values(dimensions).reduce((sum, item) => sum + item.score, 0);
  const status = toolingIntegrity.status === "fail" || evidenceCompleteness.status === "fail" || uiResilience.status === "fail"
    ? "fail"
    : realFlowReadiness.status === "pass" && evidenceCompleteness.status === "pass"
      ? "pass"
      : "warn";

  return {
    status,
    score,
    dimensions,
    artifacts,
    fixQueue: buildFixQueue(persistentBlockers),
    readinessDecision: {
      canClaimToolingReady: toolingIntegrity.status === "pass" && uiResilience.status === "pass" && evidenceCompleteness.status !== "fail",
      canClaimRealBusinessReady: realFlowReadiness.status === "pass" && persistentBlockers.length === 0,
      liveActionsStillGated: true,
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push(`# V21 Evidence Evaluation`);
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push("");
  lines.push(`## Dimensions`);
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push(`## Next Fix Queue`);
  if (!report.evaluation.fixQueue.length) {
    lines.push("- No persistent blockers reported.");
  } else {
    for (const item of report.evaluation.fixQueue) {
      lines.push(`- ${item.rank}. ${item.category} [${item.layer}]: ${item.action}`);
    }
  }
  lines.push("");
  lines.push(`## Artifacts`);
  lines.push(`- V21 report: ${report.artifacts.report}`);
  lines.push(`- V20 report: ${report.v20?.artifacts?.report || report.target.fromReport || ""}`);
  lines.push(`- Trace: ${report.evaluation.artifacts.trace || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V21",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      live: options.live,
      fromReport: options.fromReport,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Use user-visible locators and resilient traces for UI failures.",
      "Keep retries and repeated runs as flake signals, not hidden passes.",
      "Treat artifacts and cross-layer evidence as first-class debugging data.",
    ],
    v20Execution: null,
    v20: null,
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "evaluation.md"),
    },
  };

  if (options.fromReport) {
    report.v20 = await readJson(options.fromReport);
    report.v20Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV20) {
    report.v20Execution = runV20(options, artifactDir);
    report.v20 = report.v20Execution.report;
  }

  report.evaluation = await evaluateV20(report.v20, report.v20Execution);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    nextFixCount: report.evaluation.fixQueue.length,
  };
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V21 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    if (report.evaluation.fixQueue.length) {
      console.log(`Next fix: ${report.evaluation.fixQueue[0].category} -> ${report.evaluation.fixQueue[0].action}`);
    }
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Evaluation: ${report.artifacts.markdown}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
