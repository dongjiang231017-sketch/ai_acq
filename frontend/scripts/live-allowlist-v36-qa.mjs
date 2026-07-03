#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v36-live-allowlist-qa");
const DEFAULT_TEMPLATE = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");

const PLACEHOLDER_RE = /REPLACE_WITH|请替换|example\.com|<[^>]+>|\[.+\]/i;

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_TEMPLATE,
    writeTemplate: "",
    maxCalls: 1,
    maxSends: 1,
    strict: false,
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
    } else if (arg === "--write-template" && next) {
      options.writeTemplate = path.resolve(next);
      index += 1;
    } else if (arg === "--max-calls" && next) {
      options.maxCalls = Math.max(1, Number(next) || 1);
      index += 1;
    } else if (arg === "--max-sends" && next) {
      options.maxSends = Math.max(1, Number(next) || 1);
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
  console.log(`AI ACQ V36 real live allowlist QA

Usage:
  npm run qa:v36 -- --allowlist <real-authorized-allowlist.json> --json
  npm run qa:v36:template -- --write-template qa/my-real-allowlist.json
  npm run qa:v36:strict -- --allowlist <real-authorized-allowlist.json>

V36 validates real-live test data before V35/V34/V33. It never dials, sends, or writes.`);
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
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function hasPlaceholder(value) {
  return typeof value === "string" && (!value.trim() || PLACEHOLDER_RE.test(value));
}

function digits(value) {
  return String(value || "").replace(/\D/g, "");
}

function isDialablePhone(value) {
  const count = digits(value).length;
  return count >= 7 && count <= 15 && !hasPlaceholder(value);
}

function maskPhone(value) {
  const raw = String(value || "");
  const only = digits(raw);
  if (only.length < 7) return raw ? "[invalid-phone]" : "";
  return `${only.slice(0, 3)}****${only.slice(-4)}`;
}

function maskText(value, keep = 8) {
  const text = String(value || "");
  if (!text) return "";
  if (hasPlaceholder(text)) return "[placeholder]";
  if (text.length <= keep) return `${text.slice(0, 2)}***`;
  return `${text.slice(0, keep)}...`;
}

function pushIssue(list, level, pathName, message) {
  list.push({ level, path: pathName, message });
}

function validateRecipient(recipient, index, report) {
  const issues = [];
  const pathPrefix = `recipients[${index}]`;
  for (const key of ["merchantName", "city", "category"]) {
    if (hasPlaceholder(recipient?.[key])) pushIssue(issues, "fail", `${pathPrefix}.${key}`, "required real value is missing or placeholder");
  }

  const callEnabled = Boolean(recipient?.call?.enabled);
  const dmEnabled = Boolean(recipient?.dm?.enabled);
  if (!callEnabled && !dmEnabled) pushIssue(issues, "fail", pathPrefix, "at least one of call.enabled or dm.enabled must be true");

  if (callEnabled) {
    if (!isDialablePhone(recipient?.phone)) pushIssue(issues, "fail", `${pathPrefix}.phone`, "call recipient needs a real dialable phone");
    if (recipient?.call?.consent !== true) pushIssue(issues, "fail", `${pathPrefix}.call.consent`, "call consent must be true for live call QA");
    if (hasPlaceholder(recipient?.call?.consentEvidenceAlias)) pushIssue(issues, "warn", `${pathPrefix}.call.consentEvidenceAlias`, "store a consent evidence alias, not raw proof");
  }

  if (dmEnabled) {
    if (hasPlaceholder(recipient?.dm?.platform)) pushIssue(issues, "fail", `${pathPrefix}.dm.platform`, "DM platform is required");
    if (hasPlaceholder(recipient?.dm?.platformUrl)) pushIssue(issues, "warn", `${pathPrefix}.dm.platformUrl`, "platform URL is recommended for precise target matching");
    if (hasPlaceholder(recipient?.dm?.message)) pushIssue(issues, "fail", `${pathPrefix}.dm.message`, "approved DM message is required");
    if (recipient?.dm?.consent !== true) pushIssue(issues, "fail", `${pathPrefix}.dm.consent`, "DM consent must be true for live send QA");
    if (hasPlaceholder(recipient?.dm?.consentEvidenceAlias)) pushIssue(issues, "warn", `${pathPrefix}.dm.consentEvidenceAlias`, "store a consent evidence alias, not raw proof");
  }

  report.preview.recipients.push({
    index,
    merchantName: maskText(recipient?.merchantName),
    city: hasPlaceholder(recipient?.city) ? "[placeholder]" : recipient?.city || "",
    category: hasPlaceholder(recipient?.category) ? "[placeholder]" : recipient?.category || "",
    phone: maskPhone(recipient?.phone),
    callEnabled,
    dmEnabled,
    platform: hasPlaceholder(recipient?.dm?.platform) ? "[placeholder]" : recipient?.dm?.platform || "",
    hasDmMessage: Boolean(recipient?.dm?.message && !hasPlaceholder(recipient?.dm?.message)),
  });

  for (const issue of issues) report.issues.push(issue);
  return {
    callReady: callEnabled && !issues.some((issue) => issue.level === "fail" && issue.path.includes(`${pathPrefix}.phone`)) && recipient?.call?.consent === true,
    dmReady:
      dmEnabled &&
      !hasPlaceholder(recipient?.dm?.platform) &&
      !hasPlaceholder(recipient?.dm?.message) &&
      recipient?.dm?.consent === true,
  };
}

function validateAllowlist(data, options, report) {
  if (!data || typeof data !== "object") {
    pushIssue(report.issues, "fail", "$", "allowlist must be a JSON object");
    return;
  }

  const recipients = Array.isArray(data.recipients) ? data.recipients : [];
  if (recipients.length === 0) pushIssue(report.issues, "fail", "recipients", "at least one recipient is required");

  const budget = data.budget || {};
  const maxCalls = Number(budget.maxCalls || options.maxCalls);
  const maxSends = Number(budget.maxSends || options.maxSends);
  const intervalMs = Number(budget.intervalMs || 0);
  if (!Number.isFinite(maxCalls) || maxCalls < 1) pushIssue(report.issues, "fail", "budget.maxCalls", "maxCalls must be >= 1");
  if (!Number.isFinite(maxSends) || maxSends < 1) pushIssue(report.issues, "fail", "budget.maxSends", "maxSends must be >= 1");
  if (!Number.isFinite(intervalMs) || intervalMs < 3000) pushIssue(report.issues, "warn", "budget.intervalMs", "intervalMs should be at least 3000 for live batch pacing");

  const confirmations = data.confirmations || {};
  for (const key of ["realDataApproved", "liveCallApproved", "liveSendApproved", "productionWriteApproved"]) {
    if (confirmations[key] !== true) pushIssue(report.issues, "fail", `confirmations.${key}`, "confirmation must be true before strict live QA");
  }

  let callReadyCount = 0;
  let dmReadyCount = 0;
  recipients.forEach((recipient, index) => {
    const result = validateRecipient(recipient, index, report);
    if (result.callReady) callReadyCount += 1;
    if (result.dmReady) dmReadyCount += 1;
  });

  if (callReadyCount < 1) pushIssue(report.issues, "fail", "recipients.call", "at least one call-ready recipient is required");
  if (dmReadyCount < 1) pushIssue(report.issues, "fail", "recipients.dm", "at least one DM-ready recipient is required");

  report.counts = {
    recipients: recipients.length,
    callReady: callReadyCount,
    dmReady: dmReadyCount,
    maxCalls,
    maxSends,
    intervalMs,
  };
}

function summarize(report, options) {
  const failures = report.issues.filter((issue) => issue.level === "fail").length;
  const warnings = report.issues.filter((issue) => issue.level === "warn").length;
  const strictReady = failures === 0;
  const status = strictReady ? (warnings ? "warn" : "pass") : options.strict ? "fail" : "warn";
  const score = Math.max(0, 100 - failures * 10 - warnings * 3);
  const allowlistArg = options.allowlistPath ? options.allowlistPath : "<real-authorized-allowlist.json>";
  report.summary = {
    status,
    score,
    strictReady,
    failures,
    warnings,
    nextCommand: `cd frontend && npm run qa:v35:live-batch -- --allowlist ${allowlistArg} --max-calls ${report.counts.maxCalls || options.maxCalls} --max-sends ${report.counts.maxSends || options.maxSends} --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json`,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V36 Real Live Allowlist QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Strict ready: ${report.summary.strictReady}`);
  lines.push(`Next command: \`${report.summary.nextCommand}\``);
  lines.push("");
  lines.push("## Issues");
  for (const issue of report.issues) lines.push(`- ${issue.level.toUpperCase()} ${issue.path}: ${issue.message}`);
  lines.push("");
  lines.push("## Redacted Preview");
  for (const recipient of report.preview.recipients) {
    lines.push(`- #${recipient.index} ${recipient.merchantName} ${recipient.city}/${recipient.category} phone=${recipient.phone} call=${recipient.callEnabled} dm=${recipient.dmEnabled} platform=${recipient.platform}`);
  }
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.writeTemplate) {
    await fs.mkdir(path.dirname(options.writeTemplate), { recursive: true });
    await fs.copyFile(DEFAULT_TEMPLATE, options.writeTemplate);
  }

  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V36",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      allowlist: options.allowlistPath,
      strict: options.strict,
    },
    researchBasis: [
      "JSON Schema style validation is used to make real live input explicit before execution.",
      "Privacy and messaging/calling compliance guidance motivates consent flags, data minimization, redaction, caps, and pacing before live outreach tests.",
    ],
    issues: [],
    counts: {},
    preview: {
      recipients: [],
    },
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "allowlist.md"),
      template: DEFAULT_TEMPLATE,
      copiedTemplate: options.writeTemplate || "",
    },
    summary: {},
  };

  try {
    const data = await readJson(options.allowlistPath);
    validateAllowlist(data, options, report);
  } catch (error) {
    pushIssue(report.issues, "fail", "allowlist", error.message);
  }

  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  const output = JSON.stringify(report, null, 2);
  if (options.json) {
    console.log(output);
  } else {
    console.log(`V36 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 strictReady=${report.summary.strictReady}`);
    console.log(`Failures: ${report.summary.failures}; warnings: ${report.summary.warnings}`);
    console.log(`Next: ${report.summary.nextCommand}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
