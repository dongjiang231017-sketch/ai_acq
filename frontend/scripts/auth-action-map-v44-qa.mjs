#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v44-auth-action-map-qa");
const DEFAULT_CONTRACT = path.join(FRONTEND_ROOT, "qa", "v44-auth-action-contract.json");

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
  console.log(`AI ACQ V44 authenticated action-map QA

Usage:
  npm run qa:v44 -- --json
  npm run qa:v44 -- --from-report <v43-report.json> --json

V44 runs or reads V43, parses the authenticated business-workspace ARIA snapshot into a Playwright-MCP-style action map, and verifies critical user intents against a project contract without live calls or private-message sends.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|storageState)/i.test(normalized);
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

function runV43(options, artifactDir) {
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
    "scripts/auth-semantic-v43-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v43"),
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
    timeout: Math.max(options.timeoutMs + 120000, 300000),
    maxBuffer: 140 * 1024 * 1024,
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

function normalizeSnapshot(text) {
  return text
    .replace(/\bv17_client_[a-z0-9]+\b/gi, "v17_client_*")
    .replace(/\bV17隔离([^\s"']*)-[a-z0-9]+\b/g, "V17隔离$1-*")
    .replace(/\b[a-f0-9]{16,}\b/gi, "<hex-id>")
    .replace(/\b\d{2,4}[/-]\d{1,2}[/-]\d{1,2}\b/g, "<date>")
    .replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, "<time>");
}

function unescapeName(name) {
  return String(name || "").replace(/\\"/g, '"').trim();
}

function parseNodeLine(line) {
  const trimmed = line.trim();
  const match = trimmed.match(/^-\s+([a-zA-Z][\w-]*)(?:\s+"((?:\\"|[^"])*)")?(.*)$/);
  if (!match) return null;
  const tail = match[3] || "";
  const ref = tail.match(/\[ref=([^\]]+)\]/)?.[1] || "";
  const placeholder = line.match(/\/placeholder:\s*(.+)$/)?.[1]?.trim() || "";
  return {
    role: match[1],
    name: unescapeName(match[2] || placeholder),
    ref,
    disabled: /\[disabled\]/.test(tail),
    cursor: /\[cursor=pointer\]/.test(tail),
    line: trimmed,
  };
}

function extractActionMap(snapshotText) {
  const normalized = normalizeSnapshot(snapshotText);
  const lines = normalized.split("\n").filter((line) => line.trim());
  const roles = {};
  const buttons = [];
  const textboxes = [];
  const headings = [];
  const navigation = [];
  const articles = [];
  const actionableRoles = new Set(["button", "textbox", "checkbox", "combobox", "link", "menuitem", "tab"]);
  const allActions = [];
  let lastNode = null;

  for (const line of lines) {
    const placeholder = line.match(/\/placeholder:\s*(.+)$/)?.[1]?.trim() || "";
    if (placeholder && lastNode?.role === "textbox" && !lastNode.name) {
      lastNode.name = placeholder;
      continue;
    }
    const node = parseNodeLine(line);
    if (!node) continue;
    roles[node.role] = (roles[node.role] || 0) + 1;
    if (actionableRoles.has(node.role)) allActions.push(node);
    if (node.role === "button") buttons.push(node);
    if (node.role === "textbox") textboxes.push(node);
    if (node.role === "heading") headings.push(node);
    if (node.role === "navigation") navigation.push(node);
    if (node.role === "article") articles.push(node);
    lastNode = node;
  }

  return {
    lineCount: lines.length,
    charCount: normalized.length,
    roles,
    actions: allActions,
    buttons,
    enabledButtons: buttons.filter((button) => !button.disabled),
    disabledButtons: buttons.filter((button) => button.disabled),
    textboxes,
    headings,
    navigation,
    articles,
    text: normalized,
  };
}

function matchesName(name, expected) {
  const value = String(name || "");
  if (expected?.startsWith("/") && expected.endsWith("/")) {
    try {
      return new RegExp(expected.slice(1, -1)).test(value);
    } catch {
      return value.includes(expected);
    }
  }
  return value.includes(String(expected || ""));
}

function findAction(actionMap, expected, role = "button", enabledOnly = true) {
  const source = role === "any" ? actionMap.actions : actionMap.actions.filter((action) => action.role === role);
  return source.find((action) => matchesName(action.name, expected) && (!enabledOnly || !action.disabled)) || null;
}

function addIssue(issues, severity, code, detail, data = {}) {
  issues.push({ severity, code, detail, data });
}

function evaluateFlow(flow, actionMap) {
  const issues = [];
  const presentTerms = [];
  const missingTerms = [];
  for (const term of flow.requiredTerms || []) {
    if (actionMap.text.includes(term)) presentTerms.push(term);
    else missingTerms.push(term);
  }
  if (missingTerms.length) {
    addIssue(issues, "high", "FLOW_TERMS_MISSING", `${flow.key}: ${missingTerms.join(", ")}`, { missingTerms });
  }

  const matchedActions = [];
  const missingActions = [];
  for (const action of flow.requiredActions || []) {
    const found = findAction(actionMap, action, "button", true);
    if (found) matchedActions.push({ expected: action, actual: found.name, ref: found.ref });
    else missingActions.push(action);
  }
  if (missingActions.length) {
    addIssue(issues, "high", "FLOW_ENABLED_ACTIONS_MISSING", `${flow.key}: ${missingActions.join(", ")}`, { missingActions });
  }

  const matchedTextboxes = [];
  const missingTextboxes = [];
  for (const textbox of flow.requiredTextboxes || []) {
    const found = findAction(actionMap, textbox, "textbox", false);
    if (found) matchedTextboxes.push({ expected: textbox, actual: found.name, ref: found.ref });
    else missingTextboxes.push(textbox);
  }
  if (missingTextboxes.length) {
    addIssue(issues, "high", "FLOW_TEXTBOXES_MISSING", `${flow.key}: ${missingTextboxes.join(", ")}`, { missingTextboxes });
  }

  const minEnabledButtons = Number(flow.minEnabledButtons || 0);
  const flowButtonMatches = actionMap.enabledButtons.filter((button) =>
    [...(flow.requiredTerms || []), ...(flow.requiredActions || [])].some((term) => matchesName(button.name, term)),
  );
  if (minEnabledButtons && flowButtonMatches.length < minEnabledButtons) {
    addIssue(issues, "medium", "FLOW_ACTION_COUNT_LOW", `${flow.key}: enabledMatches=${flowButtonMatches.length}, min=${minEnabledButtons}`, {
      enabledMatches: flowButtonMatches.length,
      minEnabledButtons,
    });
  }

  const allowedDisabled = [];
  const unexpectedDisabled = [];
  for (const button of actionMap.disabledButtons) {
    const allowed = (flow.allowedDisabledActions || []).some((name) => matchesName(button.name, name));
    const relevant = [...(flow.requiredTerms || []), ...(flow.requiredActions || []), ...(flow.allowedDisabledActions || [])].some((term) =>
      matchesName(button.name, term),
    );
    if (allowed) allowedDisabled.push({ name: button.name, ref: button.ref });
    else if (relevant) unexpectedDisabled.push({ name: button.name, ref: button.ref });
  }
  if (unexpectedDisabled.length) {
    addIssue(issues, "medium", "FLOW_UNEXPECTED_DISABLED_ACTION", `${flow.key}: ${unexpectedDisabled.map((item) => item.name).join(", ")}`, {
      unexpectedDisabled,
    });
  }

  return {
    key: flow.key,
    title: flow.title || flow.key,
    status: issues.some((issue) => issue.severity === "high") ? "fail" : issues.length ? "warn" : "pass",
    presentTerms,
    missingTerms,
    matchedActions,
    missingActions,
    matchedTextboxes,
    missingTextboxes,
    allowedDisabled,
    issues,
  };
}

function evaluateGlobalContract(contract, actionMap) {
  const issues = [];
  const roleMinimums = contract.roleMinimums || {};
  for (const [role, minimum] of Object.entries(roleMinimums)) {
    const actual = role === "enabledButton" ? actionMap.enabledButtons.length : actionMap.roles[role] || 0;
    if (actual < minimum) {
      addIssue(issues, "high", "ROLE_MINIMUM_NOT_MET", `${role}: ${actual}<${minimum}`, { role, actual, minimum });
    }
  }
  const requiredGlobalTerms = contract.globalRequiredTerms || [];
  const missingGlobalTerms = requiredGlobalTerms.filter((term) => !actionMap.text.includes(term));
  if (missingGlobalTerms.length) {
    addIssue(issues, "high", "GLOBAL_TERMS_MISSING", missingGlobalTerms.join(", "), { missingGlobalTerms });
  }
  return issues;
}

function summarize(report, options) {
  const high = report.contract.issues.filter((issue) => issue.severity === "high").length;
  const medium = report.contract.issues.filter((issue) => issue.severity === "medium").length;
  const low = report.contract.issues.filter((issue) => issue.severity === "low").length;
  const failedFlows = report.contract.flows.filter((flow) => flow.status === "fail").length;
  const warnedFlows = report.contract.flows.filter((flow) => flow.status === "warn").length;
  const v43Ready = Boolean(report.v43?.summary?.status === "pass" && report.v43?.summary?.semanticReady);
  const actionMapReady = v43Ready && high === 0 && (!options.strict || medium === 0);
  report.summary = {
    status: !v43Ready || high > 0 || (options.strict && medium > 0) ? "fail" : medium > 0 ? "warn" : "pass",
    score: Math.max(0, 100 - failedFlows * 22 - warnedFlows * 8 - high * 18 - medium * 6 - low * 2),
    firstBlocker: !v43Ready ? "v43_authenticated_semantic" : high > 0 || (options.strict && medium > 0) ? report.contract.issues[0]?.code || "action_map_contract" : "",
    actionMapReady,
    v43Ready,
    flows: report.contract.flows.length,
    passedFlows: report.contract.flows.filter((flow) => flow.status === "pass").length,
    failedFlows,
    warnedFlows,
    high,
    medium,
    low,
    enabledActions: report.actionMap.counts.enabledActions,
    disabledActions: report.actionMap.counts.disabledActions,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V44 Authenticated Action Map QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`V43 report: ${report.v43?.artifacts?.report || "n/a"}`);
  lines.push(`ARIA snapshot: ${report.source.ariaSnapshot || "n/a"}`);
  lines.push(`Contract: ${report.target.contractPath}`);
  lines.push(`Actions: enabled=${report.summary.enabledActions}, disabled=${report.summary.disabledActions}`);
  lines.push("");
  lines.push("## Flows");
  for (const flow of report.contract.flows) {
    lines.push(`- ${flow.status.toUpperCase()} ${flow.key}: actions=${flow.matchedActions.length}, terms=${flow.presentTerms.length}`);
  }
  if (report.contract.issues.length) {
    lines.push("");
    lines.push("## Issues");
    for (const issue of report.contract.issues) lines.push(`- ${issue.severity} ${issue.code}: ${issue.detail}`);
  }
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Action map is derived from authenticated ARIA/accessibility structure; storageState and tokens are not copied into the V44 report.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  if (!fsSync.existsSync(options.contractPath)) {
    throw new Error(`V44 contract not found: ${options.contractPath}`);
  }
  const contract = readJson(options.contractPath);
  const v43Run = runV43(options, artifactDir);
  const v43 = v43Run.report;
  const ariaSnapshot = v43?.semantic?.snapshot || "";
  if (!ariaSnapshot || !fsSync.existsSync(ariaSnapshot)) {
    throw new Error("V43 report does not include a readable authenticated ARIA snapshot");
  }

  const snapshotText = fsSync.readFileSync(ariaSnapshot, "utf8");
  const actionMapRaw = extractActionMap(snapshotText);
  const globalIssues = evaluateGlobalContract(contract, actionMapRaw);
  const flows = (contract.flows || []).map((flow) => evaluateFlow(flow, actionMapRaw));
  const issues = [...globalIssues, ...flows.flatMap((flow) => flow.issues.map((issue) => ({ ...issue, flow: flow.key })))];
  const actionMapArtifact = path.join(artifactDir, "agent-action-map.json");
  const report = {
    version: "V44",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      contractPath: options.contractPath,
      strict: options.strict,
      fromReport: options.fromReport,
    },
    researchBasis: [
      "Playwright MCP uses structured accessibility snapshots so agents can interact with roles, names, and refs instead of screenshots.",
      "Playwright ARIA snapshots provide a stable accessibility-tree representation for semantic regression checks.",
      "Playwright authentication guidance supports storageState reuse for authenticated browser workflows.",
    ],
    source: {
      ariaSnapshot,
      v43Report: v43?.artifacts?.report || options.fromReport || "",
    },
    v43Run: {
      command: v43Run.command,
      exitCode: v43Run.exitCode,
      durationMs: v43Run.durationMs,
      parseError: v43Run.parseError,
      stdoutTail: v43Run.stdoutTail,
      stderrTail: v43Run.stderrTail,
    },
    v43: v43
      ? {
          summary: v43.summary || {},
          artifacts: v43.artifacts || {},
          semantic: {
            metrics: v43.semantic?.metrics
              ? {
                  lineCount: v43.semantic.metrics.lineCount,
                  charCount: v43.semantic.metrics.charCount,
                  roleCounts: v43.semantic.metrics.roleCounts,
                  presentTerms: v43.semantic.metrics.presentTerms,
                  missingTerms: v43.semantic.metrics.missingTerms,
                }
              : {},
            similarity: v43.semantic?.similarity ?? null,
          },
        }
      : null,
    actionMap: {
      counts: {
        lines: actionMapRaw.lineCount,
        chars: actionMapRaw.charCount,
        roles: actionMapRaw.roles,
        actions: actionMapRaw.actions.length,
        enabledActions: actionMapRaw.actions.filter((action) => !action.disabled).length,
        disabledActions: actionMapRaw.actions.filter((action) => action.disabled).length,
        buttons: actionMapRaw.buttons.length,
        textboxes: actionMapRaw.textboxes.length,
        headings: actionMapRaw.headings.length,
        navigation: actionMapRaw.navigation.length,
      },
      enabledActions: actionMapRaw.actions
        .filter((action) => !action.disabled)
        .map((action) => ({ role: action.role, name: action.name, ref: action.ref })),
      disabledActions: actionMapRaw.actions
        .filter((action) => action.disabled)
        .map((action) => ({ role: action.role, name: action.name, ref: action.ref })),
      headings: actionMapRaw.headings.map((heading) => ({ name: heading.name, ref: heading.ref })),
    },
    contract: {
      version: contract.version || "",
      issues,
      flows,
    },
    liveActionsExecuted: false,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "auth-action-map.md"),
      actionMap: actionMapArtifact,
      contract: options.contractPath,
    },
    summary: {},
  };

  summarize(report, options);
  await writeJson(actionMapArtifact, report.actionMap);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V44 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Action map: ${report.artifacts.actionMap}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
