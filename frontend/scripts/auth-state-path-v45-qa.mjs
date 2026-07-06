#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v45-auth-state-path-qa");
const DEFAULT_CONTRACT = path.join(FRONTEND_ROOT, "qa", "v45-auth-state-path-contract.json");

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    contractPath: DEFAULT_CONTRACT,
    timeoutMs: 180000,
    readinessTimeoutMs: 30000,
    strict: false,
    fromReport: "",
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--contract" && next) {
      options.contractPath = path.resolve(next);
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
  console.log(`AI ACQ V45 authenticated state-path trace QA

Usage:
  npm run qa:v45 -- --json
  npm run qa:v45 -- --from-report <v44-report.json> --json

V45 runs or reads V44, follows the nested authenticated V17 evidence, and verifies that each critical business state has matching UI checks, API-created isolated data, screenshots, and a replayable Playwright trace. It does not execute live calls, private-message sends, account changes, or production writes.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|storageState|accessToken)/i.test(normalized);
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

async function writeJson(file, value) {
  await mkdirp(path.dirname(file));
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

function readJson(file) {
  return JSON.parse(fsSync.readFileSync(file, "utf8"));
}

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function runV44(options, artifactDir) {
  if (options.fromReport) {
    return {
      command: `read ${options.fromReport}`,
      exitCode: 0,
      signal: null,
      durationMs: 0,
      parseError: "",
      report: readJson(options.fromReport),
      stdoutTail: "",
      stderrTail: "",
    };
  }
  const args = [
    "scripts/auth-action-map-v44-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v44"),
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
    timeout: Math.max(options.timeoutMs + 150000, 360000),
    maxBuffer: 180 * 1024 * 1024,
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

function addIssue(issues, severity, code, detail, data = {}) {
  issues.push({ severity, code, detail, data });
}

function existingFile(file) {
  return Boolean(file && fsSync.existsSync(file) && fsSync.statSync(file).isFile());
}

function deriveReportFromSnapshot(snapshotPath) {
  if (!snapshotPath) return "";
  return path.join(path.dirname(snapshotPath), "report.json");
}

function resolveV17Report(v44) {
  const candidates = [];
  const add = (file) => {
    if (file && !candidates.includes(file)) candidates.push(file);
  };

  add(deriveReportFromSnapshot(v44?.source?.ariaSnapshot));
  if (v44?.source?.v43Report && existingFile(v44.source.v43Report)) {
    const v43 = readJson(v44.source.v43Report);
    add(deriveReportFromSnapshot(v43?.semantic?.snapshot));
    add(v43?.v42?.v41?.v17?.artifacts?.report);
    add(v43?.v42?.artifacts?.v17Report);
    if (v43?.v42?.artifacts?.report && existingFile(v43.v42.artifacts.report)) {
      const v42 = readJson(v43.v42.artifacts.report);
      add(v42?.v41?.v17?.artifacts?.report);
      add(deriveReportFromSnapshot(v42?.v41?.v17?.authReplay?.ariaSnapshot));
    }
  }

  const found = candidates.find(existingFile);
  if (!found) {
    throw new Error(`Unable to resolve nested V17 report from V44 report; tried ${candidates.filter(Boolean).join(", ") || "no candidates"}`);
  }
  return found;
}

function tracePathFor(v17, v17ReportPath) {
  const direct = v17?.artifacts?.trace || "";
  if (existingFile(direct)) return direct;
  const derived = path.join(path.dirname(v17ReportPath), "trace.zip");
  if (existingFile(derived)) return derived;
  return direct || derived;
}

function basenameSet(files) {
  return new Set((files || []).map((file) => path.basename(file)));
}

function screenshotExists(v17, filename) {
  const match = (v17?.artifacts?.screenshots || []).find((file) => path.basename(file) === filename);
  return Boolean(match && existingFile(match));
}

function browserApiCount(v17) {
  return Array.isArray(v17?.browser?.apiResponses) ? v17.browser.apiResponses.length : 0;
}

function analyzeTrace(tracePath) {
  const inventory = {
    path: tracePath,
    exists: existingFile(tracePath),
    fileSize: 0,
    unzipAvailable: false,
    entries: 0,
    resources: 0,
    traceBytes: 0,
    networkBytes: 0,
    stackBytes: 0,
    totalListedBytes: 0,
    hasTrace: false,
    hasNetwork: false,
    hasStacks: false,
    error: "",
  };
  if (!inventory.exists) {
    inventory.error = "trace.zip not found";
    return inventory;
  }
  inventory.fileSize = fsSync.statSync(tracePath).size;
  const result = spawnSync("unzip", ["-l", tracePath], {
    cwd: FRONTEND_ROOT,
    encoding: "utf8",
    timeout: 30000,
    maxBuffer: 60 * 1024 * 1024,
  });
  if (result.status !== 0) {
    inventory.error = result.stderr?.slice(-1000) || result.stdout?.slice(-1000) || "unzip failed";
    return inventory;
  }
  inventory.unzipAvailable = true;
  for (const line of result.stdout.split("\n")) {
    const match = line.match(/^\s*(\d+)\s+\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}\s+(.+)$/);
    if (!match) continue;
    const bytes = Number(match[1]) || 0;
    const name = match[2].trim();
    inventory.entries += 1;
    inventory.totalListedBytes += bytes;
    if (name.startsWith("resources/")) inventory.resources += 1;
    if (name === "trace.trace") {
      inventory.hasTrace = true;
      inventory.traceBytes = bytes;
    }
    if (name === "trace.network") {
      inventory.hasNetwork = true;
      inventory.networkBytes = bytes;
    }
    if (name === "trace.stacks") {
      inventory.hasStacks = true;
      inventory.stackBytes = bytes;
    }
  }
  return inventory;
}

function evaluateActionMap(v44, contract) {
  const issues = [];
  const flows = v44?.contract?.flows || [];
  const flowByKey = new Map(flows.map((flow) => [flow.key, flow]));
  for (const key of contract.requiredActionMapFlows || []) {
    const flow = flowByKey.get(key);
    if (!flow) addIssue(issues, "high", "ACTION_FLOW_MISSING", `V44 action-map flow missing: ${key}`, { key });
    else if (flow.status !== "pass") addIssue(issues, "high", "ACTION_FLOW_NOT_PASSING", `V44 action-map flow not passing: ${key}`, { key, status: flow.status });
  }
  if (v44?.summary?.status !== "pass" || !v44?.summary?.actionMapReady) {
    addIssue(issues, "high", "V44_NOT_READY", "V44 authenticated action map is not ready", { summary: v44?.summary || {} });
  }
  return {
    issues,
    flows: (contract.requiredActionMapFlows || []).map((key) => {
      const flow = flowByKey.get(key);
      return { key, status: flow?.status || "missing", matchedActions: flow?.matchedActions?.length || 0 };
    }),
  };
}

function evaluateCleanRuntime(v17, expectedCleanRuntime) {
  const issues = [];
  const actual = {
    failures: Number(v17?.summary?.failures || 0),
    warnings: Number(v17?.summary?.warnings || 0),
    consoleErrors: Number(v17?.summary?.consoleErrors || 0),
    pageErrors: Number(v17?.summary?.pageErrors || 0),
    failedRequests: Number(v17?.summary?.failedRequests || 0),
    blockedMutations: Number(v17?.summary?.blockedMutations || 0),
  };
  for (const [key, expected] of Object.entries(expectedCleanRuntime || {})) {
    if (actual[key] !== expected) {
      addIssue(issues, "high", "RUNTIME_NOT_CLEAN", `${key}: ${actual[key]} !== ${expected}`, { key, actual: actual[key], expected });
    }
  }
  if ((v17?.browser?.failedRequests || []).length) {
    addIssue(issues, "high", "BROWSER_FAILED_REQUESTS", "Browser captured failed requests", { count: v17.browser.failedRequests.length });
  }
  if ((v17?.browser?.blockedMutations || []).length) {
    addIssue(issues, "high", "BROWSER_BLOCKED_MUTATIONS", "Browser captured blocked mutations", { count: v17.browser.blockedMutations.length });
  }
  return { actual, issues };
}

function evaluateNode(node, v17) {
  const issues = [];
  const passedChecks = new Set((v17?.checks || []).filter((check) => check.status === "pass").map((check) => check.name));
  const created = v17?.state?.created || {};

  const missingChecks = (node.requiredChecks || []).filter((check) => !passedChecks.has(check));
  if (missingChecks.length) addIssue(issues, "high", "NODE_CHECKS_MISSING", `${node.key}: ${missingChecks.join(", ")}`, { missingChecks });

  const missingScreenshots = (node.requiredScreenshots || []).filter((screenshot) => !screenshotExists(v17, screenshot));
  if (missingScreenshots.length) addIssue(issues, "high", "NODE_SCREENSHOTS_MISSING", `${node.key}: ${missingScreenshots.join(", ")}`, { missingScreenshots });

  const missingCreatedKeys = (node.requiredCreatedKeys || []).filter((key) => created[key] === undefined || created[key] === null || created[key] === "");
  if (missingCreatedKeys.length) addIssue(issues, "high", "NODE_CREATED_KEYS_MISSING", `${node.key}: ${missingCreatedKeys.join(", ")}`, { missingCreatedKeys });

  return {
    key: node.key,
    title: node.title || node.key,
    status: issues.some((issue) => issue.severity === "high") ? "fail" : issues.length ? "warn" : "pass",
    checks: {
      required: (node.requiredChecks || []).length,
      matched: (node.requiredChecks || []).length - missingChecks.length,
      missing: missingChecks,
    },
    screenshots: {
      required: (node.requiredScreenshots || []).length,
      matched: (node.requiredScreenshots || []).length - missingScreenshots.length,
      missing: missingScreenshots,
    },
    createdKeys: {
      required: (node.requiredCreatedKeys || []).length,
      matched: (node.requiredCreatedKeys || []).length - missingCreatedKeys.length,
      missing: missingCreatedKeys,
      values: Object.fromEntries((node.requiredCreatedKeys || []).filter((key) => created[key]).map((key) => [key, created[key]])),
    },
    issues,
  };
}

function evaluateMinimums(contract, v17, traceInventory) {
  const issues = [];
  const screenshots = v17?.artifacts?.screenshots || [];
  const minimums = contract.minimums || {};
  const actuals = {
    checks: (v17?.checks || []).filter((check) => check.status === "pass").length,
    screenshots: screenshots.filter(existingFile).length,
    browserApiResponses: browserApiCount(v17),
    traceEntries: traceInventory.entries,
    traceResources: traceInventory.resources,
    traceBytes: traceInventory.totalListedBytes || traceInventory.fileSize,
  };
  for (const [key, minimum] of Object.entries(minimums)) {
    if ((actuals[key] || 0) < minimum) {
      addIssue(issues, "high", "MINIMUM_NOT_MET", `${key}: ${actuals[key] || 0}<${minimum}`, { key, actual: actuals[key] || 0, minimum });
    }
  }
  if (!traceInventory.exists) addIssue(issues, "high", "TRACE_MISSING", "Playwright trace.zip is missing", { tracePath: traceInventory.path });
  if (!traceInventory.hasTrace) addIssue(issues, "high", "TRACE_BODY_MISSING", "trace.trace is missing from trace.zip", { tracePath: traceInventory.path });
  if (!traceInventory.hasNetwork) addIssue(issues, "high", "TRACE_NETWORK_MISSING", "trace.network is missing from trace.zip", { tracePath: traceInventory.path });
  return { actuals, issues };
}

function summarize(report, options) {
  const allIssues = [
    ...report.v44Gate.issues,
    ...report.runtime.issues,
    ...report.minimums.issues,
    ...report.statePath.nodes.flatMap((node) => node.issues.map((issue) => ({ ...issue, node: node.key }))),
  ];
  const high = allIssues.filter((issue) => issue.severity === "high").length;
  const medium = allIssues.filter((issue) => issue.severity === "medium").length;
  const failedNodes = report.statePath.nodes.filter((node) => node.status === "fail").length;
  const warnedNodes = report.statePath.nodes.filter((node) => node.status === "warn").length;
  const v17Ready = report.v17.summary.status === "pass";
  const statePathReady = Boolean(v17Ready && report.v44.summary.status === "pass" && high === 0 && (!options.strict || medium === 0));
  report.issues = allIssues;
  report.summary = {
    status: !statePathReady ? "fail" : medium > 0 ? "warn" : "pass",
    score: Math.max(0, 100 - failedNodes * 18 - warnedNodes * 6 - high * 12 - medium * 4),
    firstBlocker: !v17Ready ? "v17_stateful_business_flow" : high > 0 || (options.strict && medium > 0) ? allIssues[0]?.code || "state_path_contract" : "",
    statePathReady,
    v44Ready: report.v44.summary.status === "pass" && Boolean(report.v44.summary.actionMapReady),
    v17Ready,
    nodes: report.statePath.nodes.length,
    passedNodes: report.statePath.nodes.filter((node) => node.status === "pass").length,
    failedNodes,
    warnedNodes,
    high,
    medium,
    checks: report.minimums.actuals.checks,
    screenshots: report.minimums.actuals.screenshots,
    browserApiResponses: report.minimums.actuals.browserApiResponses,
    traceEntries: report.minimums.actuals.traceEntries,
    traceResources: report.minimums.actuals.traceResources,
    traceBytes: report.minimums.actuals.traceBytes,
    liveActionsExecuted: false,
    noLiveSideEffects: report.runtime.issues.length === 0,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V45 Authenticated State-Path Trace QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`V44 report: ${report.source.v44Report || "n/a"}`);
  lines.push(`V17 report: ${report.source.v17Report || "n/a"}`);
  lines.push(`Trace: ${report.source.trace || "n/a"}`);
  lines.push(`Contract: ${report.target.contractPath}`);
  lines.push("");
  lines.push("## Coverage");
  lines.push(`- State nodes: ${report.summary.passedNodes}/${report.summary.nodes}`);
  lines.push(`- Passed checks: ${report.summary.checks}`);
  lines.push(`- Screenshots: ${report.summary.screenshots}`);
  lines.push(`- Browser API responses: ${report.summary.browserApiResponses}`);
  lines.push(`- Trace entries/resources/bytes: ${report.summary.traceEntries}/${report.summary.traceResources}/${report.summary.traceBytes}`);
  lines.push("");
  lines.push("## State Path");
  for (const node of report.statePath.nodes) {
    lines.push(`- ${node.status.toUpperCase()} ${node.key}: checks=${node.checks.matched}/${node.checks.required}, screenshots=${node.screenshots.matched}/${node.screenshots.required}, created=${node.createdKeys.matched}/${node.createdKeys.required}`);
  }
  if (report.issues.length) {
    lines.push("");
    lines.push("## Issues");
    for (const issue of report.issues) lines.push(`- ${issue.severity} ${issue.code}: ${issue.detail}`);
  }
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- Uses isolated authenticated test data already produced by V17.");
  lines.push("- Requires UI checks, API state, screenshots, and Playwright trace evidence to agree.");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Storage state and access tokens are not copied into the V45 report.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  if (!existingFile(options.contractPath)) throw new Error(`V45 contract not found: ${options.contractPath}`);
  const contract = readJson(options.contractPath);
  const v44Run = runV44(options, artifactDir);
  if (!v44Run.report) throw new Error(`V44 did not produce a parseable report: ${v44Run.parseError || "unknown parse error"}`);
  const v44 = v44Run.report;
  const v17ReportPath = resolveV17Report(v44);
  const v17 = readJson(v17ReportPath);
  const tracePath = tracePathFor(v17, v17ReportPath);

  const traceInventory = analyzeTrace(tracePath);
  const v44Gate = evaluateActionMap(v44, contract);
  const runtime = evaluateCleanRuntime(v17, contract.expectedCleanRuntime);
  const minimums = evaluateMinimums(contract, v17, traceInventory);
  const nodes = (contract.nodes || []).map((node) => evaluateNode(node, v17));

  const stateModel = {
    version: contract.version,
    generatedAt: new Date().toISOString(),
    nodes: nodes.map((node, index) => ({
      index,
      key: node.key,
      title: node.title,
      status: node.status,
      evidence: {
        checks: `${node.checks.matched}/${node.checks.required}`,
        screenshots: `${node.screenshots.matched}/${node.screenshots.required}`,
        createdKeys: `${node.createdKeys.matched}/${node.createdKeys.required}`,
      },
    })),
    transitions: nodes.slice(1).map((node, index) => ({
      from: nodes[index].key,
      to: node.key,
      status: nodes[index].status === "pass" && node.status === "pass" ? "covered" : "blocked",
    })),
  };

  const report = {
    version: "V45",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      contractPath: options.contractPath,
      strict: options.strict,
      fromReport: options.fromReport,
    },
    researchBasis: [
      "Playwright trace viewer stores timeline, DOM snapshots, console, network, and source evidence for debugging and CI failure analysis.",
      "Playwright project-dependency/global-setup guidance supports producing authenticated setup traces and reusable storage state.",
      "Model-based testing practices verify coverage as business state transitions, not only isolated clicks.",
    ],
    source: {
      v44Report: v44?.artifacts?.report || options.fromReport || "",
      v17Report: v17ReportPath,
      trace: tracePath,
      screenshots: (v17?.artifacts?.screenshots || []).map((file) => path.basename(file)),
      ariaSnapshots: (v17?.artifacts?.ariaSnapshots || []).map((file) => path.basename(file)),
    },
    v44Run: {
      command: v44Run.command,
      exitCode: v44Run.exitCode,
      durationMs: v44Run.durationMs,
      parseError: v44Run.parseError,
      stdoutTail: v44Run.stdoutTail,
      stderrTail: v44Run.stderrTail,
    },
    v44: {
      summary: v44.summary || {},
      artifacts: v44.artifacts || {},
    },
    v17: {
      summary: v17.summary || {},
      artifacts: {
        report: v17?.artifacts?.report || v17ReportPath,
        trace: tracePath,
        screenshots: (v17?.artifacts?.screenshots || []).map((file) => path.basename(file)),
        ariaSnapshots: (v17?.artifacts?.ariaSnapshots || []).map((file) => path.basename(file)),
      },
      created: v17?.state?.created || {},
      checkCount: (v17?.checks || []).length,
      screenshotCount: (v17?.artifacts?.screenshots || []).length,
      browserApiResponses: browserApiCount(v17),
    },
    v44Gate,
    runtime,
    minimums,
    trace: traceInventory,
    statePath: {
      model: stateModel,
      nodes,
      screenshotBasenames: [...basenameSet(v17?.artifacts?.screenshots || [])],
    },
    liveActionsExecuted: false,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "auth-state-path.md"),
      model: path.join(artifactDir, "state-path-model.json"),
      traceInventory: path.join(artifactDir, "trace-inventory.json"),
      contract: options.contractPath,
    },
    issues: [],
    summary: {},
  };

  summarize(report, options);
  await writeJson(report.artifacts.model, stateModel);
  await writeJson(report.artifacts.traceInventory, traceInventory);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V45 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  if (report.summary.status === "fail") process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
