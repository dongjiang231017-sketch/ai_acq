#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v43-auth-semantic-qa");
const DEFAULT_BASELINE = path.join(FRONTEND_ROOT, "qa", "v43-auth-semantic-baseline.json");
const REQUIRED_TERMS = ["AI外呼系统", "在线坐席", "商家线索库", "任务列表", "话术流程", "通话记录", "重拨规则", "实时监听"];
const CORE_TERMS = ["AI外呼系统", "在线坐席", "商家线索库", "任务列表"];

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    baselinePath: DEFAULT_BASELINE,
    timeoutMs: 180000,
    readinessTimeoutMs: 30000,
    strict: false,
    updateBaseline: false,
    fromReport: "",
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--baseline" && next) {
      options.baselinePath = path.resolve(next);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(30000, Number(next) || 180000);
      index += 1;
    } else if (arg === "--readiness-timeout-ms" && next) {
      options.readinessTimeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--from-report" && next) {
      options.fromReport = path.resolve(next);
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
    } else if (arg === "--update-baseline") {
      options.updateBaseline = true;
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
  console.log(`AI ACQ V43 authenticated semantic regression QA

Usage:
  npm run qa:v43 -- --json
  npm run qa:v43:update-baseline -- --json
  npm run qa:v43 -- --from-report <v42-report.json> --json

V43 runs or reads V42, extracts the authenticated business-workspace ARIA snapshot, computes a local semantic fingerprint, and compares it with a baseline without executing live calls or sends.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await mkdirp(path.dirname(file));
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function sha256(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function runV42(options, artifactDir) {
  if (options.fromReport) {
    return {
      command: `read ${options.fromReport}`,
      exitCode: 0,
      signal: null,
      durationMs: 0,
      parseError: "",
      report: JSON.parse(fsSync.readFileSync(options.fromReport, "utf8")),
      stdoutTail: "",
      stderrTail: "",
    };
  }
  const args = [
    "scripts/auth-visual-v42-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v42"),
    "--timeout-ms",
    String(options.timeoutMs),
    "--readiness-timeout-ms",
    String(options.readinessTimeoutMs),
    "--json",
  ];
  if (options.strict) args.push("--strict");
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: Math.max(options.timeoutMs + 90000, 270000),
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
    command: `${process.execPath} ${args.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : result.stdout?.slice(-3000) || "",
    stderrTail: result.stderr?.slice(-3000) || "",
  };
}

function readJsonIfExists(file) {
  return file && fsSync.existsSync(file) ? JSON.parse(fsSync.readFileSync(file, "utf8")) : null;
}

function findAriaSnapshot(v42Report) {
  const direct = v42Report?.v41?.v17?.authReplay?.ariaSnapshot || "";
  if (direct) return { path: direct, source: "v42.v41.v17.authReplay" };
  const fullV17 = readJsonIfExists(v42Report?.v41?.v17?.artifacts?.report || "");
  const fromFull = fullV17?.state?.authReplay?.ariaSnapshot || "";
  if (fromFull) return { path: fromFull, source: "nested-v17-report" };
  const fromArtifacts = Array.isArray(fullV17?.artifacts?.ariaSnapshots)
    ? fullV17.artifacts.ariaSnapshots.find((item) => /02b-auth-state-reuse-dashboard\.aria\.yml$/.test(item)) || fullV17.artifacts.ariaSnapshots[0]
    : "";
  return fromArtifacts ? { path: fromArtifacts, source: "nested-v17-artifacts" } : { path: "", source: "" };
}

function normalizeSnapshot(text) {
  return text
    .replace(/\bv17_client_[a-z0-9]+\b/gi, "v17_client_*")
    .replace(/\bV17隔离([^\s"']*)-[a-z0-9]+\b/g, "V17隔离$1-*")
    .replace(/\b[a-f0-9]{16,}\b/gi, "<hex-id>")
    .replace(/\b\d{2,4}-\d{1,2}-\d{1,2}\b/g, "<date>")
    .replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, "<time>")
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.trim())
    .join("\n");
}

function roleFromLine(line) {
  const match = line.match(/^\s*-\s+([a-zA-Z][\w-]*)\b/);
  return match?.[1] || "";
}

function analyzeSnapshot(snapshotText) {
  const normalized = normalizeSnapshot(snapshotText);
  const lines = normalized.split("\n").filter(Boolean);
  const roleCounts = {};
  for (const line of lines) {
    const role = roleFromLine(line);
    if (role) roleCounts[role] = (roleCounts[role] || 0) + 1;
  }
  const lineHashes = lines.map((line) => sha256(line).slice(0, 16)).sort();
  const presentTerms = REQUIRED_TERMS.filter((term) => normalized.includes(term));
  const missingTerms = REQUIRED_TERMS.filter((term) => !normalized.includes(term));
  const missingCoreTerms = CORE_TERMS.filter((term) => !normalized.includes(term));
  return {
    normalizedHash: sha256(normalized),
    lineHashes,
    lineCount: lines.length,
    charCount: normalized.length,
    roleCounts,
    requiredTerms: REQUIRED_TERMS,
    presentTerms,
    missingTerms,
    missingCoreTerms,
  };
}

function jaccard(left, right) {
  const leftSet = new Set(left || []);
  const rightSet = new Set(right || []);
  if (!leftSet.size && !rightSet.size) return 1;
  let intersection = 0;
  for (const item of leftSet) {
    if (rightSet.has(item)) intersection += 1;
  }
  return Number((intersection / Math.max(1, leftSet.size + rightSet.size - intersection)).toFixed(3));
}

function addIssue(issues, severity, code, detail) {
  issues.push({ severity, code, detail });
}

function inspectSemantic(metrics, baseline, options) {
  const issues = [];
  if (metrics.lineCount < 24 || metrics.charCount < 800) {
    addIssue(issues, "high", "AUTH_SEMANTIC_SNAPSHOT_TOO_SMALL", `lines=${metrics.lineCount}, chars=${metrics.charCount}`);
  }
  if ((metrics.roleCounts.heading || 0) < 1) {
    addIssue(issues, "high", "AUTH_SEMANTIC_HEADING_MISSING", "no heading role detected");
  }
  if ((metrics.roleCounts.button || 0) < 6) {
    addIssue(issues, "high", "AUTH_SEMANTIC_BUTTONS_MISSING", `buttons=${metrics.roleCounts.button || 0}`);
  }
  if (metrics.missingCoreTerms.length) {
    addIssue(issues, "high", "AUTH_SEMANTIC_CORE_TERMS_MISSING", metrics.missingCoreTerms.join(", "));
  } else if (metrics.missingTerms.length) {
    addIssue(issues, "medium", "AUTH_SEMANTIC_TERMS_MISSING", metrics.missingTerms.join(", "));
  }
  if (!baseline) {
    addIssue(issues, options.strict ? "high" : "medium", "AUTH_SEMANTIC_BASELINE_MISSING", "run qa:v43:update-baseline after reviewing the ARIA snapshot");
    return issues;
  }
  const similarity = jaccard(metrics.lineHashes, baseline.metrics?.lineHashes || []);
  if (similarity < 0.55) {
    addIssue(issues, "high", "AUTH_SEMANTIC_LINE_DRIFT_HIGH", `jaccard=${similarity}`);
  } else if (similarity < 0.72) {
    addIssue(issues, "medium", "AUTH_SEMANTIC_LINE_DRIFT_MEDIUM", `jaccard=${similarity}`);
  }
  if (metrics.lineCount < baseline.metrics.lineCount * 0.55) {
    addIssue(issues, "high", "AUTH_SEMANTIC_STRUCTURE_COLLAPSED", `lines ${baseline.metrics.lineCount}->${metrics.lineCount}`);
  }
  const baselineButtons = baseline.metrics.roleCounts?.button || 0;
  if (baselineButtons && (metrics.roleCounts.button || 0) < baselineButtons * 0.55) {
    addIssue(issues, "high", "AUTH_SEMANTIC_ACTIONS_COLLAPSED", `buttons ${baselineButtons}->${metrics.roleCounts.button || 0}`);
  }
  return issues;
}

function summarize(report, options) {
  const high = report.semantic.issues.filter((issue) => issue.severity === "high").length;
  const medium = report.semantic.issues.filter((issue) => issue.severity === "medium").length;
  const low = report.semantic.issues.filter((issue) => issue.severity === "low").length;
  const v42Ready = Boolean(report.v42?.summary?.status === "pass" && report.v42?.summary?.visualReady);
  const baselineReady = Boolean(report.semantic.baseline?.path);
  const score = Math.max(0, 100 - high * 35 - medium * 12 - low * 4);
  const status = !v42Ready || high > 0 || (options.strict && medium > 0) ? "fail" : medium > 0 ? "warn" : "pass";
  report.summary = {
    status,
    score,
    firstBlocker: !v42Ready ? "v42_authenticated_visual" : high > 0 || (options.strict && medium > 0) ? report.semantic.issues[0]?.code || "semantic_regression" : "",
    semanticReady: high === 0,
    baselineReady,
    v42Ready,
    high,
    medium,
    low,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V43 Authenticated Semantic QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`V42 report: ${report.v42?.artifacts?.report || "n/a"}`);
  lines.push(`ARIA snapshot: ${report.semantic.snapshot || "n/a"}`);
  lines.push(`Baseline: ${report.semantic.baseline?.path || "n/a"}`);
  lines.push(`Metrics: ${JSON.stringify({ lineCount: report.semantic.metrics.lineCount, roles: report.semantic.metrics.roleCounts, similarity: report.semantic.similarity })}`);
  if (report.semantic.issues.length) {
    lines.push("");
    lines.push("## Issues");
    for (const issue of report.semantic.issues) lines.push(`- ${issue.severity} ${issue.code}: ${issue.detail}`);
  }
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Semantic baseline stores derived metrics and line hashes only, not storageState or tokens.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const v42Run = runV42(options, artifactDir);
  const v42 = v42Run.report;
  const snapshotInfo = findAriaSnapshot(v42);
  if (!snapshotInfo.path) throw new Error("V42/V41 report does not include an authenticated ARIA snapshot");
  const snapshotText = fsSync.readFileSync(snapshotInfo.path, "utf8");
  const metrics = analyzeSnapshot(snapshotText);
  let baseline = readJsonIfExists(options.baselinePath);
  if (options.updateBaseline) {
    baseline = {
      version: "V43-auth-semantic-baseline/v1",
      generatedAt: new Date().toISOString(),
      metrics,
    };
    await writeJson(options.baselinePath, baseline);
  }
  const issues = inspectSemantic(metrics, baseline, options);
  const similarity = baseline?.metrics?.lineHashes ? jaccard(metrics.lineHashes, baseline.metrics.lineHashes) : null;
  const report = {
    version: "V43",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      baseline: options.baselinePath,
      strict: options.strict,
      updateBaseline: options.updateBaseline,
      fromReport: options.fromReport,
    },
    researchBasis: [
      "Playwright ARIA snapshot guidance supports comparing accessibility-tree YAML for page structure regressions.",
      "Playwright authentication guidance supports storageState reuse for authenticated tests.",
      "Playwright visual comparison guidance motivates pairing semantic checks with screenshot evidence.",
    ],
    v42Run: {
      command: v42Run.command,
      exitCode: v42Run.exitCode,
      durationMs: v42Run.durationMs,
      parseError: v42Run.parseError,
      stdoutTail: v42Run.stdoutTail,
      stderrTail: v42Run.stderrTail,
    },
    v42: v42
      ? {
          summary: v42.summary || {},
          artifacts: v42.artifacts || {},
          v41: v42.v41
            ? {
                summary: v42.v41.summary || {},
                artifacts: v42.v41.artifacts || {},
                v17: v42.v41.v17
                  ? {
                      summary: v42.v41.v17.summary || {},
                      authReplay: v42.v41.v17.authReplay || {},
                      artifacts: v42.v41.v17.artifacts || {},
                    }
                  : null,
              }
            : null,
        }
      : null,
    semantic: {
      snapshot: snapshotInfo.path,
      snapshotSource: snapshotInfo.source,
      metrics,
      baseline: baseline ? { path: options.baselinePath, generatedAt: baseline.generatedAt || "" } : null,
      similarity,
      issues,
    },
    liveActionsExecuted: false,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "auth-semantic.md"),
      baseline: options.baselinePath,
    },
    summary: {},
  };
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V43 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`ARIA snapshot: ${report.semantic.snapshot}`);
    console.log(`Baseline: ${report.semantic.baseline?.path || "n/a"}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
