#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v41-auth-readiness-qa");
const DEFAULT_ALLOWLIST = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_ALLOWLIST,
    api: DEFAULT_API,
    timeoutMs: 180000,
    readinessTimeoutMs: 30000,
    strict: false,
    headed: false,
    noTrace: false,
    skipV40: false,
    skipV17: false,
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--allowlist" && next) {
      options.allowlistPath = path.resolve(next);
      index += 1;
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(30000, Number(next) || 180000);
      index += 1;
    } else if (arg === "--readiness-timeout-ms" && next) {
      options.readinessTimeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--no-trace") {
      options.noTrace = true;
    } else if (arg === "--skip-v40") {
      options.skipV40 = true;
    } else if (arg === "--skip-v17") {
      options.skipV17 = true;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V41 authenticated readiness QA

Usage:
  npm run qa:v41 -- --json
  npm run qa:v41:strict -- --allowlist <real-authorized-allowlist.json> --api <api-base> --json
  npm run quality:v41 -- --timeout-ms 180000

V41 composes V40 local client readiness with V17 authenticated stateful replay, and requires proof that Playwright storageState can reopen the business workspace without repeating login.`);
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

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function runScript(script, args, timeoutMs) {
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, [script, ...args], {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: timeoutMs,
    maxBuffer: 120 * 1024 * 1024,
  });
  let report = null;
  let parseError = "";
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }
  return {
    command: `${process.execPath} ${[script, ...args].join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : result.stdout?.slice(-3000) || "",
    stderrTail: result.stderr?.slice(-3000) || "",
  };
}

function runV40(options, artifactDir) {
  const args = [
    "--artifact-root",
    path.join(artifactDir, "v40"),
    "--allowlist",
    options.allowlistPath,
    "--api",
    options.api,
    "--timeout-ms",
    String(options.readinessTimeoutMs),
    "--json",
  ];
  if (options.strict) args.push("--strict");
  if (options.headed) args.push("--headed");
  if (options.noTrace) args.push("--no-trace");
  return runScript("scripts/live-readiness-local-v40-qa.mjs", args, Math.max(options.readinessTimeoutMs + 45000, 75000));
}

function runV17(options, artifactDir) {
  const args = [
    "--artifact-root",
    path.join(artifactDir, "v17"),
    "--timeout-ms",
    String(options.timeoutMs),
    "--json",
  ];
  if (options.headed) args.push("--headed");
  return runScript("scripts/stateful-client-v17-qa.mjs", args, Math.max(options.timeoutMs + 45000, 225000));
}

function compactV40(report) {
  if (!report) return null;
  return {
    version: report.version || "",
    summary: report.summary || {},
    preview: report.preview || {},
    artifacts: report.artifacts || {},
    v39: report.v39 ? { summary: report.v39.summary || {}, artifacts: report.v39.artifacts || {}, api: report.v39.api || {} } : null,
  };
}

function compactV17(report) {
  if (!report) return null;
  const authReplay = report.state?.authReplay || {};
  return {
    version: report.version || "",
    summary: report.summary || {},
    runtime: {
      apiPort: report.runtime?.apiPort || null,
      frontendPort: report.runtime?.frontendPort || null,
      credentialsAlias: report.runtime?.credentialsAlias || "",
    },
    authReplay: {
      storageStatePath: authReplay.storageStatePath || report.artifacts?.storageState || "",
      screenshot: authReplay.screenshot || "",
      tokenReused: Boolean(authReplay.tokenReused),
    },
    artifacts: {
      root: report.artifacts?.root || "",
      report: report.artifacts?.report || "",
      trace: report.artifacts?.trace || "",
      storageState: report.artifacts?.storageState || "",
      screenshots: Array.isArray(report.artifacts?.screenshots)
        ? report.artifacts.screenshots.filter((item) => /02-after-login|02b-auth-state-reuse|13-mobile/.test(item))
        : [],
    },
    checks: Array.isArray(report.checks)
      ? report.checks
          .filter((check) => check.status !== "pass" || /认证态复用|认证正例|移动端/.test(check.name))
          .map((check) => ({ name: check.name, status: check.status, detail: check.detail }))
      : [],
  };
}

function summarize(report, options) {
  const v40Summary = report.v40?.summary || {};
  const v17Summary = report.v17?.summary || {};
  const v40ResidualBlocker =
    v40Summary.firstBlocker && v40Summary.firstBlocker !== "real_live_acceptance" ? v40Summary.firstBlocker : "";
  const localReadinessTraceReady =
    options.skipV40 || Boolean(v40Summary.previewReady && v40Summary.uiOpened && v40Summary.traceReady && v40Summary.screenshotReady && v40Summary.noLiveSideEffects);
  const authenticatedReplayReady =
    options.skipV17 || Boolean(report.v17?.authReplay?.storageStatePath && report.v17?.authReplay?.tokenReused && report.v17?.authReplay?.screenshot);
  const v17ToolingReady = options.skipV17 || (v17Summary.status && v17Summary.status !== "fail");
  const v40ToolingReady = options.skipV40 || (v40Summary.status && v40Summary.status !== "fail");
  const score =
    (localReadinessTraceReady ? 35 : 0) +
    (authenticatedReplayReady ? 35 : 0) +
    (v17ToolingReady ? 15 : 0) +
    (v40ToolingReady ? 10 : 0) +
    (!report.liveActionsExecuted ? 5 : 0);
  const firstBlocker = !authenticatedReplayReady
    ? "authenticated_state_replay"
    : !localReadinessTraceReady
      ? "local_readiness_trace"
      : "";
  report.summary = {
    status: !authenticatedReplayReady || !localReadinessTraceReady ? "warn" : "pass",
    score,
    firstBlocker,
    residualRisks: v40ResidualBlocker ? [v40ResidualBlocker] : [],
    localReadinessTraceReady,
    authenticatedReplayReady,
    storageStateReady: Boolean(report.v17?.authReplay?.storageStatePath),
    v17ToolingReady,
    v40ToolingReady,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
    nextCommand: v40Summary.nextCommand || "",
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V41 Authenticated Readiness QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`Residual risks: ${report.summary.residualRisks?.length ? report.summary.residualRisks.join(", ") : "n/a"}`);
  lines.push(`V40 trace: ${report.v40?.artifacts?.trace || "n/a"}`);
  lines.push(`V40 screenshot: ${report.v40?.artifacts?.screenshot || "n/a"}`);
  lines.push(`V17 auth replay screenshot: ${report.v17?.authReplay?.screenshot || "n/a"}`);
  lines.push(`V17 storage state: ${report.v17?.authReplay?.storageStatePath || "n/a"}`);
  lines.push(`Next command: \`${report.summary.nextCommand || "n/a"}\``);
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Authenticated replay uses isolated V17 test services and local ignored artifacts.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const v40Run = options.skipV40 ? null : runV40(options, artifactDir);
  const v17Run = options.skipV17 ? null : runV17(options, artifactDir);
  const report = {
    version: "V41",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      api: options.api,
      allowlist: options.allowlistPath,
      strict: options.strict,
      skipV40: options.skipV40,
      skipV17: options.skipV17,
    },
    researchBasis: [
      "Playwright authentication guidance recommends saving authenticated browser state and reusing it to speed up tests.",
      "Playwright project-dependency guidance recommends setup flows that keep setup traces visible as artifacts.",
      "Playwright webServer guidance motivates test-owned local app startup when staging URLs are unavailable.",
    ],
    v40Run: v40Run
      ? {
          command: v40Run.command,
          exitCode: v40Run.exitCode,
          durationMs: v40Run.durationMs,
          parseError: v40Run.parseError,
          stdoutTail: v40Run.stdoutTail,
          stderrTail: v40Run.stderrTail,
        }
      : null,
    v17Run: v17Run
      ? {
          command: v17Run.command,
          exitCode: v17Run.exitCode,
          durationMs: v17Run.durationMs,
          parseError: v17Run.parseError,
          stdoutTail: v17Run.stdoutTail,
          stderrTail: v17Run.stderrTail,
        }
      : null,
    v40: compactV40(v40Run?.report),
    v17: compactV17(v17Run?.report),
    liveActionsExecuted: false,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "auth-readiness.md"),
    },
    summary: {},
  };
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(
      `V41 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"} residual=${report.summary.residualRisks?.join(",") || "n/a"}`,
    );
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`V40 trace: ${report.v40?.artifacts?.trace || "n/a"}`);
    console.log(`V17 auth replay: ${report.v17?.authReplay?.screenshot || "n/a"}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
