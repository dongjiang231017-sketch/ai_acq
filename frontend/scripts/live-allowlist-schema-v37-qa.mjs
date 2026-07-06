#!/usr/bin/env node
import Ajv2020 from "ajv/dist/2020.js";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v37-live-allowlist-schema-qa");
const DEFAULT_ALLOWLIST = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");
const DEFAULT_SCHEMA = path.join(FRONTEND_ROOT, "qa", "v37-real-live-allowlist.schema.json");
const PLACEHOLDER_RE = /REPLACE_WITH|请替换|example\.com|<[^>]+>|\[.+\]/i;

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_ALLOWLIST,
    schemaPath: DEFAULT_SCHEMA,
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
    } else if (arg === "--schema" && next) {
      options.schemaPath = path.resolve(next);
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
  console.log(`AI ACQ V37 real live allowlist schema QA

Usage:
  npm run qa:v37 -- --allowlist <real-authorized-allowlist.json> --json
  npm run qa:v37:strict -- --allowlist <real-authorized-allowlist.json> --json

V37 validates the live QA allowlist against a JSON Schema 2020-12 contract with Ajv. It never dials, sends, or writes.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function digits(value) {
  return String(value || "").replace(/\D/g, "");
}

function hasPlaceholder(value) {
  return typeof value === "string" && (!value.trim() || PLACEHOLDER_RE.test(value));
}

function maskPhone(value) {
  const only = digits(value);
  if (only.length < 7) return value ? "[invalid-phone]" : "";
  return `${only.slice(0, 3)}****${only.slice(-4)}`;
}

function maskText(value) {
  const text = String(value || "");
  if (!text) return "";
  if (hasPlaceholder(text)) return "[placeholder]";
  if (text.length <= 8) return `${text.slice(0, 2)}***`;
  return `${text.slice(0, 8)}...`;
}

function pointerToPath(pointer) {
  if (!pointer) return "$";
  return pointer
    .split("/")
    .filter(Boolean)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"))
    .reduce((acc, part) => (/^\d+$/.test(part) ? `${acc}[${part}]` : `${acc}.${part}`), "$");
}

function formatSchemaError(error) {
  const pathName = pointerToPath(error.instancePath);
  const params = error.params ? JSON.stringify(error.params) : "";
  let message = error.message || "schema validation failed";
  if (error.keyword === "not") message = "placeholder or empty value is not allowed";
  if (error.keyword === "const" && error.params?.allowedValue === true) message = "must be explicitly true";
  if (error.keyword === "pattern" && String(error.schemaPath || "").includes("/phone/")) message = "phone must be dialable";
  if (error.keyword === "contains" && String(error.schemaPath || "").includes("allOf/0")) message = "at least one call-ready recipient is required";
  if (error.keyword === "contains" && String(error.schemaPath || "").includes("allOf/1")) message = "at least one DM-ready recipient is required";
  return {
    level: "fail",
    path: pathName,
    keyword: error.keyword,
    schemaPath: error.schemaPath,
    message: `${message}${params && message === error.message ? ` ${params}` : ""}`,
  };
}

function buildPreview(data) {
  const recipients = Array.isArray(data?.recipients) ? data.recipients : [];
  return {
    recipients: recipients.map((recipient, index) => ({
      index,
      merchantName: maskText(recipient?.merchantName),
      city: hasPlaceholder(recipient?.city) ? "[placeholder]" : recipient?.city || "",
      category: hasPlaceholder(recipient?.category) ? "[placeholder]" : recipient?.category || "",
      phone: maskPhone(recipient?.phone),
      callEnabled: Boolean(recipient?.call?.enabled),
      dmEnabled: Boolean(recipient?.dm?.enabled),
      platform: hasPlaceholder(recipient?.dm?.platform) ? "[placeholder]" : recipient?.dm?.platform || "",
      hasDmMessage: Boolean(recipient?.dm?.message && !hasPlaceholder(recipient?.dm?.message)),
    })),
  };
}

function buildCounts(data) {
  const recipients = Array.isArray(data?.recipients) ? data.recipients : [];
  return {
    recipients: recipients.length,
    callEnabled: recipients.filter((recipient) => recipient?.call?.enabled === true).length,
    dmEnabled: recipients.filter((recipient) => recipient?.dm?.enabled === true).length,
    maxCalls: Number(data?.budget?.maxCalls || 0),
    maxSends: Number(data?.budget?.maxSends || 0),
    intervalMs: Number(data?.budget?.intervalMs || 0),
  };
}

function summarize(report, options) {
  const failures = report.issues.filter((issue) => issue.level === "fail").length;
  const schemaReady = failures === 0;
  const status = schemaReady ? "pass" : options.strict ? "fail" : "warn";
  const score = Math.max(0, 100 - failures * 5);
  report.summary = {
    status,
    score,
    schemaReady,
    failures,
    schemaErrors: failures,
    nextV36Command: `cd frontend && npm run qa:v36:strict -- --allowlist ${options.allowlistPath} --json`,
    nextV35Command: `cd frontend && npm run qa:v35:live-batch -- --allowlist ${options.allowlistPath} --max-calls ${report.counts.maxCalls || 1} --max-sends ${report.counts.maxSends || 1} --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json`,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V37 Real Live Allowlist Schema QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Schema ready: ${report.summary.schemaReady}`);
  lines.push(`Next V36 command: \`${report.summary.nextV36Command}\``);
  lines.push(`Next V35 command: \`${report.summary.nextV35Command}\``);
  lines.push("");
  lines.push("## Schema Issues");
  if (report.issues.length === 0) lines.push("- none");
  for (const issue of report.issues) lines.push(`- ${issue.keyword} ${issue.path}: ${issue.message}`);
  lines.push("");
  lines.push("## Redacted Preview");
  for (const recipient of report.preview.recipients) {
    lines.push(`- #${recipient.index} ${recipient.merchantName} ${recipient.city}/${recipient.category} phone=${recipient.phone} call=${recipient.callEnabled} dm=${recipient.dmEnabled} platform=${recipient.platform}`);
  }
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await fs.mkdir(artifactDir, { recursive: true });

  const report = {
    version: "V37",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      allowlist: options.allowlistPath,
      schema: options.schemaPath,
      strict: options.strict,
    },
    researchBasis: [
      "JSON Schema 2020-12 gives the live-test input package a reusable machine-readable contract.",
      "Ajv validates the contract locally before V36/V35/V34/V33 can consider live actions.",
      "Trace-context and Playwright evidence remain downstream proof layers; V37 only proves the allowlist contract.",
    ],
    engine: {
      name: "ajv",
      dialect: "JSON Schema 2020-12",
      allErrors: true,
      strict: false,
    },
    issues: [],
    counts: {},
    preview: {
      recipients: [],
    },
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "schema.md"),
      schema: options.schemaPath,
    },
    summary: {},
  };

  let allowlist = {};
  try {
    const schema = await readJson(options.schemaPath);
    allowlist = await readJson(options.allowlistPath);
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    const validate = ajv.compile(schema);
    const valid = validate(allowlist);
    if (!valid) report.issues.push(...(validate.errors || []).map(formatSchemaError));
  } catch (error) {
    report.issues.push({
      level: "fail",
      path: "$",
      keyword: "runtime",
      schemaPath: "",
      message: error.message,
    });
  }

  report.counts = buildCounts(allowlist);
  report.preview = buildPreview(allowlist);
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V37 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 schemaReady=${report.summary.schemaReady}`);
    console.log(`Schema errors: ${report.summary.schemaErrors}`);
    console.log(`Next V36: ${report.summary.nextV36Command}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
