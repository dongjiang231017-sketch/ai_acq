#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v38-live-readiness-bundle-qa");
const DEFAULT_ALLOWLIST = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_ALLOWLIST,
    api: "",
    timeoutMs: 30000,
    strict: false,
    skipV35: false,
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
      options.api = next;
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
    } else if (arg === "--skip-v35") {
      options.skipV35 = true;
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
  console.log(`AI ACQ V38 live readiness bundle QA

Usage:
  npm run qa:v38 -- --json
  npm run qa:v38:strict -- --allowlist <real-authorized-allowlist.json> --api <api-base> --json

V38 composes V37 schema validation, V36 business allowlist validation, and V35 blocker director plan into one no-live-action bundle.`);
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

function makeTraceparent() {
  const bytes = randomBytes(24).toString("hex");
  return `00-${bytes.slice(0, 32)}-${bytes.slice(32, 48)}-01`;
}

function runNodeScript(script, args, options) {
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, [script, ...args], {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: Math.max(options.timeoutMs + 15000, 30000),
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
    report,
    parseError,
    stdoutTail: result.stdout?.slice(-2000) || "",
    stderrTail: result.stderr?.slice(-2000) || "",
  };
}

function statusWeight(status) {
  if (status === "pass") return 2;
  if (status === "warn") return 1;
  return 0;
}

function collectLayerStatus(name, run, readyKey) {
  const summary = run?.report?.summary || {};
  const status = summary.status || (run?.exitCode === 0 ? "pass" : "fail");
  let ready = readyKey ? Boolean(summary[readyKey]) : status !== "fail";
  if (readyKey === "directorReady") ready = Boolean(summary.firstBlocker || summary.status);
  return {
    name,
    status,
    score: summary.score ?? 0,
    ready,
    exitCode: run?.exitCode ?? null,
    durationMs: run?.durationMs ?? 0,
    report: run?.report?.artifacts?.report || run?.report?.summary?.latestV34Report || "",
    markdown: run?.report?.artifacts?.markdown || "",
    firstBlocker: summary.firstBlocker || "",
    nextCommand: summary.nextCommand || summary.rerunCommand || summary.nextV36Command || "",
  };
}

function compactNestedReport(report) {
  if (!report) return null;
  const summary = report.summary || {};
  const artifacts = report.artifacts || {};
  return {
    version: report.version || "",
    status: summary.status || "",
    score: summary.score ?? summary.readinessScore ?? 0,
    schemaReady: summary.schemaReady,
    strictReady: summary.strictReady,
    firstBlocker: summary.firstBlocker || "",
    nextCommand: summary.nextCommand || summary.rerunCommand || summary.nextV36Command || "",
    report: artifacts.report || summary.latestV34Report || "",
    markdown: artifacts.markdown || "",
  };
}

function summarize(report, options) {
  const layerStatuses = report.layers.map((layer) => layer.status);
  const hasFail = layerStatuses.includes("fail");
  const hasWarn = layerStatuses.includes("warn");
  const status = hasFail && options.strict ? "fail" : hasFail || hasWarn ? "warn" : "pass";
  const avgLayerScore =
      report.layers.length > 0 ? Math.round(report.layers.reduce((sum, layer) => sum + (Number(layer.score) || 0), 0) / report.layers.length) : 0;
  const readinessScore = Math.round(
    Math.min(100, avgLayerScore * 0.7 + (report.layers.reduce((sum, layer) => sum + statusWeight(layer.status), 0) / Math.max(1, report.layers.length * 2)) * 30),
  );
  const schemaReady = Boolean(report.nested?.v37?.schemaReady);
  const allowlistReady = Boolean(report.nested?.v36?.strictReady);
  const directorReady = Boolean(report.nested?.v35?.firstBlocker || report.nested?.v35?.status);
  const firstBlocker =
    !schemaReady
      ? "schema_contract"
      : !allowlistReady
        ? "allowlist_business_rules"
        : report.nested?.v35?.firstBlocker || "runtime_director_pending";
  const nextCommand =
    !schemaReady
      ? `cd frontend && npm run qa:v37:strict -- --allowlist ${options.allowlistPath} --json`
      : !allowlistReady
        ? `cd frontend && npm run qa:v36:strict -- --allowlist ${options.allowlistPath} --json`
        : report.nested?.v35?.nextCommand ||
          `cd frontend && npm run qa:v35:live-batch -- --allowlist ${options.allowlistPath} --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json`;

  report.summary = {
    status,
    readinessScore,
    schemaReady,
    allowlistReady,
    directorReady,
    firstBlocker,
    nextCommand,
    canProceedToLiveDirector: schemaReady && allowlistReady,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V38 Live Readiness Bundle QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Readiness score: ${report.summary.readinessScore}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker}`);
  lines.push(`Next command: \`${report.summary.nextCommand}\``);
  lines.push("");
  lines.push("## Layers");
  for (const layer of report.layers) {
    lines.push(`- ${layer.name}: ${layer.status}, ready=${layer.ready}, score=${layer.score}, report=${layer.report || "n/a"}`);
  }
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const correlationId = `v38-${nowSlug()}`;
  const traceparent = makeTraceparent();
  const sharedArgs = ["--allowlist", options.allowlistPath, "--json"];
  const strictArg = options.strict ? ["--strict"] : [];

  const v37 = runNodeScript("scripts/live-allowlist-schema-v37-qa.mjs", [...strictArg, ...sharedArgs], options);
  const v36 = runNodeScript("scripts/live-allowlist-v36-qa.mjs", [...strictArg, ...sharedArgs], options);
  let v35 = null;
  if (!options.skipV35) {
    const args = ["--plan-only", "--allowlist", options.allowlistPath, "--timeout-ms", String(options.timeoutMs), "--json"];
    if (options.api) args.push("--api", options.api);
    v35 = runNodeScript("scripts/live-blocker-director-v35-qa.mjs", args, options);
  }

  const report = {
    version: "V38",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      allowlist: options.allowlistPath,
      api: options.api || "",
      strict: options.strict,
      skipV35: options.skipV35,
    },
    researchBasis: [
      "Playwright APIRequestContext supports combining API checks with end-to-end evidence.",
      "OpenTelemetry context propagation motivates carrying correlation identity across readiness layers.",
      "JSON Schema recommended output patterns motivate one normalized bundle instead of scattered validator outputs.",
    ],
    correlation: {
      id: correlationId,
      traceparent,
      baggage: `ai-acq-qa-version=V38,allowlist=${path.basename(options.allowlistPath)}`,
    },
    commands: {
      v37: v37.command,
      v36: v36.command,
      v35: v35?.command || "",
    },
    nested: {
      v37: compactNestedReport(v37.report),
      v36: compactNestedReport(v36.report),
      v35: compactNestedReport(v35?.report),
    },
    layers: [
      collectLayerStatus("v37_schema_contract", v37, "schemaReady"),
      collectLayerStatus("v36_allowlist_business_rules", v36, "strictReady"),
    ],
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "bundle.md"),
    },
    diagnostics: {
      v37ParseError: v37.parseError,
      v36ParseError: v36.parseError,
      v35ParseError: v35?.parseError || "",
      v37StdoutTail: v37.report ? "" : v37.stdoutTail,
      v36StdoutTail: v36.report ? "" : v36.stdoutTail,
      v35StdoutTail: v35 && !v35.report ? v35.stdoutTail : "",
    },
    summary: {},
  };
  if (v35) report.layers.push(collectLayerStatus("v35_blocker_director_plan", v35, "directorReady"));

  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V38 QA ${report.summary.status.toUpperCase()} score=${report.summary.readinessScore}/100 blocker=${report.summary.firstBlocker}`);
    console.log(`Next: ${report.summary.nextCommand}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
