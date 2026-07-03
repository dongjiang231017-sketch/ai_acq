#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v34-live-evidence-qa");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";
const V33_SCRIPT = path.join("scripts", "live-acceptance-v33-qa.mjs");

const ownOptionsWithValue = new Set(["--artifact-root", "--from-report", "--api", "--timeout-ms", "--allowlist"]);
const passThroughWithValue = new Set([
  "--url",
  "--cdp",
  "--desktop-app",
  "--cdp-port",
  "--max-calls",
  "--max-sends",
  "--interval-ms",
  "--batch-call-mode",
  "--username",
  "--password",
  "--phone",
  "--caller-id",
  "--merchant-name",
  "--city",
  "--category",
  "--contact-name",
  "--platform",
  "--platform-url",
  "--collection-provider",
  "--collection-keyword",
  "--collection-target",
  "--comment-platform",
  "--comment-source-url",
  "--dm-message",
]);

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    api: DEFAULT_API,
    timeoutMs: 180000,
    allowlistPath: "",
    json: false,
    planOnly: false,
    requireLive: false,
    liveBatch: false,
    confirmRealData: false,
    confirmLiveCall: false,
    confirmLiveDm: false,
    confirmLiveBatch: false,
    confirmProductionWrite: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      if (arg === "--api") {
        options.api = next.replace(/\/$/, "");
        options.passThrough.push(arg, options.api);
      }
      if (arg === "--timeout-ms") {
        options.timeoutMs = Math.max(10000, Number(next) || 180000);
        options.passThrough.push(arg, String(options.timeoutMs));
      }
      if (arg === "--allowlist") {
        options.allowlistPath = path.resolve(next);
        options.passThrough.push(arg, options.allowlistPath);
      }
      index += 1;
    } else if (passThroughWithValue.has(arg) && next) {
      options.passThrough.push(arg, next);
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--plan-only") {
      options.planOnly = true;
      options.passThrough.push(arg);
    } else if (arg === "--require-live") {
      options.requireLive = true;
      options.passThrough.push(arg);
    } else if (arg === "--live-batch") {
      options.liveBatch = true;
      options.passThrough.push(arg);
    } else if (arg === "--confirm-real-data") {
      options.confirmRealData = true;
      options.passThrough.push(arg);
    } else if (arg === "--confirm-live-call") {
      options.confirmLiveCall = true;
      options.passThrough.push(arg);
    } else if (arg === "--confirm-live-dm" || arg === "--confirm-live-send") {
      options.confirmLiveDm = true;
      options.passThrough.push(arg);
    } else if (arg === "--confirm-live-batch") {
      options.confirmLiveBatch = true;
      options.passThrough.push(arg);
    } else if (arg === "--confirm-production-write") {
      options.confirmProductionWrite = true;
      options.passThrough.push(arg);
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      options.passThrough.push(arg);
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V34 live evidence blocker QA

Safe readiness:
  npm run qa:v34:plan -- --json --allowlist qa/v33-real-live-allowlist.example.json

Strict live evidence diagnosis after exact approval:
  npm run qa:v34:live-batch -- --allowlist <real-allowlist.json> --max-calls 1 --max-sends 1 \\
    --confirm-real-data --confirm-live-call --confirm-live-send \\
    --confirm-live-batch --confirm-production-write

V34 wraps V33 and adds a runtime blocker graph for backend, telephony, AMI, trunk, cellular preflight, media, DM gateway/account, and persistence evidence.
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function maskPhone(value) {
  const digits = String(value || "").replace(/\D/g, "");
  if (digits.length < 7) return value ? "[phone-provided]" : "";
  return `${digits.slice(0, 3)}****${digits.slice(-4)}`;
}

function isSensitiveKey(key) {
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/i.test(String(key || ""));
}

function redact(value, key = "") {
  if (typeof value === "string") {
    if (isSensitiveKey(key)) return value ? "[redacted]" : "";
    return value
      .replace(/\b1[3-9]\d{9}\b/g, (match) => maskPhone(match))
      .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[token-redacted]");
  }
  if (Array.isArray(value)) return value.map((item) => redact(item, key));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([itemKey, item]) => [itemKey, redact(item, itemKey)]));
  }
  return value;
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
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

function addCheck(report, name, status, detail, data = undefined) {
  report.checks.push({ name, status, detail, data });
}

async function readAllowlistPhone(file) {
  if (!file) return "";
  try {
    const raw = JSON.parse(await fs.readFile(file, "utf8"));
    const rows = Array.isArray(raw) ? raw : [...(raw.calls || []), ...(raw.sends || []), ...(raw.recipients || [])];
    const found = rows.find((row) => String(row.phone || row.mobile || row.tel || "").replace(/\D/g, "").length >= 7);
    return String(found?.phone || found?.mobile || found?.tel || "").trim();
  } catch {
    return "";
  }
}

async function fetchJson(report, key, endpoint, timeoutMs = 7000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const url = `${report.target.api}${endpoint}`;
  try {
    const response = await fetch(url, {
      headers: {
        Accept: "application/json",
        "X-AI-ACQ-QA-Correlation-Id": report.correlation.runId,
        "X-Request-ID": report.correlation.runId,
        traceparent: report.correlation.traceparent,
        baggage: report.correlation.baggage,
      },
      signal: controller.signal,
    });
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text.slice(0, 1000) };
    }
    report.runtime.probes[key] = { endpoint, status: response.status, ok: response.ok, body };
  } catch (error) {
    report.runtime.probes[key] = { endpoint, status: "error", ok: false, error: error.message };
  } finally {
    clearTimeout(timer);
  }
  return report.runtime.probes[key];
}

async function collectRuntimeEvidence(report, options) {
  const phone = await readAllowlistPhone(options.allowlistPath);
  report.runtime.allowlistProbePhone = maskPhone(phone);
  const endpoints = [
    ["health", "/health"],
    ["telephonyConfig", "/outbound/telephony/config"],
    ["telephonyHealth", "/outbound/telephony/health"],
    ["realtimePipeline", "/outbound/realtime/pipeline"],
    ["liveEvents", "/outbound/realtime/live-events?limit=80"],
    ["callRecords", "/outbound/records"],
    ["dmConfig", "/direct-messages/config"],
    ["dmAccounts", "/direct-messages/accounts"],
    ["dmConversations", "/direct-messages/conversations"],
    ["dmMessages", "/direct-messages/messages"],
  ];
  if (phone) endpoints.splice(3, 0, ["telephonyPreflight", `/outbound/telephony/preflight?phone=${encodeURIComponent(phone)}`]);
  for (const [key, endpoint] of endpoints) {
    await fetchJson(report, key, endpoint);
  }
}

function checkProbe(report, key) {
  return report.runtime.probes[key] || { ok: false, status: "missing", body: null };
}

function pushBlocker(report, layer, status, detail, data = undefined) {
  const blocker = { layer, status, detail, data };
  report.blockers.push(blocker);
  report.graph.nodes.push(blocker);
  return blocker;
}

function classifyBlockers(report, options) {
  const v33 = report.v33 || {};
  const liveContractIssues = v33.liveContract?.blockingIssues || [];
  pushBlocker(
    report,
    "real_data_allowlist",
    liveContractIssues.length === 0 ? "pass" : options.requireLive ? "fail" : "warn",
    liveContractIssues.length ? liveContractIssues.join(" | ") : "allowlist/input contract ready",
  );

  const confirmations = v33.target?.confirmations || {};
  const missingConfirmations = [];
  if (!confirmations.realData) missingConfirmations.push("realData");
  if (!confirmations.liveCall) missingConfirmations.push("liveCall");
  if (!confirmations.liveDm) missingConfirmations.push("liveDm");
  if (v33.target?.liveBatch && !confirmations.liveBatch) missingConfirmations.push("liveBatch");
  if (!confirmations.productionWrite) missingConfirmations.push("productionWrite");
  pushBlocker(
    report,
    "confirmations",
    missingConfirmations.length === 0 ? "pass" : options.requireLive ? "fail" : "warn",
    missingConfirmations.length ? `missing=${missingConfirmations.join(",")}` : "all required confirmation flags present",
  );

  const health = checkProbe(report, "health");
  pushBlocker(report, "backend_api", health.ok ? "pass" : "fail", `GET /health -> ${health.status}`, health);

  const telephonyConfig = checkProbe(report, "telephonyConfig").body || {};
  pushBlocker(
    report,
    "telephony_live_switch",
    telephonyConfig.gatewayMode === "asterisk" && telephonyConfig.asteriskLiveCallEnabled ? "pass" : options.requireLive ? "fail" : "warn",
    `gatewayMode=${telephonyConfig.gatewayMode || "missing"}, asteriskLiveCallEnabled=${telephonyConfig.asteriskLiveCallEnabled}`,
  );

  const telephonyHealth = checkProbe(report, "telephonyHealth").body || {};
  pushBlocker(
    report,
    "ami_auth",
    telephonyHealth.authenticated ? "pass" : options.requireLive ? "fail" : "warn",
    `authenticated=${telephonyHealth.authenticated}, amiReachable=${telephonyHealth.amiReachable}`,
  );
  pushBlocker(
    report,
    "trunk_reachable",
    telephonyHealth.trunkReachable === true ? "pass" : options.requireLive ? "fail" : "warn",
    `trunkReachable=${telephonyHealth.trunkReachable}, trunkStatus=${telephonyHealth.trunkStatus || "missing"}`,
  );

  const preflight = checkProbe(report, "telephonyPreflight").body || {};
  pushBlocker(
    report,
    "phone_preflight",
    preflight.readyForSingleNumberTest ? "pass" : options.requireLive ? "fail" : "warn",
    preflight.nextStep || (report.runtime.allowlistProbePhone ? "phone preflight missing/not ready" : "no allowlist phone to preflight"),
    preflight.steps,
  );

  const pipeline = checkProbe(report, "realtimePipeline").body || {};
  pushBlocker(
    report,
    "media_bridge",
    pipeline.readyForAsteriskMedia ? "pass" : options.requireLive ? "fail" : "warn",
    `readyForAsteriskMedia=${pipeline.readyForAsteriskMedia}, mode=${pipeline.mode || "missing"}, bridge=${pipeline.bridgeMode || "missing"}`,
  );

  const dmConfig = checkProbe(report, "dmConfig").body || {};
  pushBlocker(
    report,
    "dm_live_switch",
    dmConfig.gatewayMode === "browser" && dmConfig.browserLiveSendEnabled ? "pass" : options.requireLive ? "fail" : "warn",
    `gatewayMode=${dmConfig.gatewayMode || "missing"}, browserLiveSendEnabled=${dmConfig.browserLiveSendEnabled}`,
  );
  const dmAccounts = checkProbe(report, "dmAccounts").body;
  const usableAccounts = Array.isArray(dmAccounts)
    ? dmAccounts.filter((account) => account.status === "可用" && account.sessionStatus === "已登录")
    : [];
  pushBlocker(
    report,
    "dm_logged_account",
    usableAccounts.length > 0 ? "pass" : options.requireLive ? "fail" : "warn",
    usableAccounts.length ? usableAccounts.map((account) => `${account.platform}/${account.accountName}`).join(", ") : "no usable logged-in platform personal account",
  );

  pushBlocker(
    report,
    "v33_real_call_evidence",
    v33.summary?.canClaimRealCallAcceptance ? "pass" : options.requireLive ? "fail" : "warn",
    `canClaimRealCallAcceptance=${Boolean(v33.summary?.canClaimRealCallAcceptance)}`,
    v33.evidence?.call || [],
  );
  pushBlocker(
    report,
    "v33_real_dm_evidence",
    v33.summary?.canClaimRealDmAcceptance ? "pass" : options.requireLive ? "fail" : "warn",
    `canClaimRealDmAcceptance=${Boolean(v33.summary?.canClaimRealDmAcceptance)}`,
    v33.evidence?.dm || [],
  );
  pushBlocker(
    report,
    "v33_real_live_acceptance",
    v33.summary?.canClaimRealLiveAcceptance ? "pass" : options.requireLive ? "fail" : "warn",
    `canClaimRealLiveAcceptance=${Boolean(v33.summary?.canClaimRealLiveAcceptance)}`,
  );

  report.graph.edges = [
    ["real_data_allowlist", "confirmations"],
    ["confirmations", "backend_api"],
    ["backend_api", "telephony_live_switch"],
    ["telephony_live_switch", "ami_auth"],
    ["ami_auth", "trunk_reachable"],
    ["trunk_reachable", "phone_preflight"],
    ["phone_preflight", "media_bridge"],
    ["media_bridge", "v33_real_call_evidence"],
    ["backend_api", "dm_live_switch"],
    ["dm_live_switch", "dm_logged_account"],
    ["dm_logged_account", "v33_real_dm_evidence"],
    ["v33_real_call_evidence", "v33_real_live_acceptance"],
    ["v33_real_dm_evidence", "v33_real_live_acceptance"],
  ].map(([from, to]) => ({ from, to }));
}

function firstBlocker(report, options) {
  const priority = [
    "real_data_allowlist",
    "confirmations",
    "backend_api",
    "telephony_live_switch",
    "ami_auth",
    "trunk_reachable",
    "phone_preflight",
    "media_bridge",
    "dm_live_switch",
    "dm_logged_account",
    "v33_real_call_evidence",
    "v33_real_dm_evidence",
    "v33_real_live_acceptance",
  ];
  const byPriority = (status) => priority.map((layer) => report.blockers.find((item) => item.layer === layer && item.status === status)).find(Boolean);
  return byPriority("fail") || byPriority(options.requireLive ? "fail" : "warn") || null;
}

function nextActionFor(blocker) {
  if (!blocker) return "Run strict V33 live acceptance with the approved real allowlist and preserve the trace/report.";
  const map = {
    real_data_allowlist: "Replace placeholder data with an approved real allowlist containing authorized call and private-message recipients.",
    confirmations: "Add the exact confirmation flags for the approved live side effects before running strict live mode.",
    backend_api: "Start or repair the target backend/API, then rerun V34 plan before any live action.",
    telephony_live_switch: "Configure Asterisk gateway mode and enable the single-number live-call switch for the approved test window.",
    ami_auth: "Fix AMI reachability/credentials on the target Asterisk service.",
    trunk_reachable: "Register and verify the Dinstar/UC100 trunk before dialing.",
    phone_preflight: "Run phone-level preflight with the approved number and fix the first failed step.",
    media_bridge: "Start or repair the AudioSocket/realtime media bridge before claiming AI conversation acceptance.",
    dm_live_switch: "Switch DM gateway to browser live-send mode and enable the approved live-send switch.",
    dm_logged_account: "Log in a supported platform personal account and verify it is 可用/已登录.",
    v33_real_call_evidence: "Run strict V33 live call flow and require gateway, cellular, media, human speech, AI speech, and conversation evidence.",
    v33_real_dm_evidence: "Run strict V33 live private-message flow and require send-start plus conversation/message persistence.",
    v33_real_live_acceptance: "Rerun V33 strict live until both real call and real private-message evidence pass.",
  };
  return map[blocker.layer] || blocker.detail;
}

function summarize(report, options) {
  const blocker = firstBlocker(report, options);
  const failures = report.blockers.filter((item) => item.status === "fail").length;
  const warnings = report.blockers.filter((item) => item.status === "warn").length;
  const status = options.requireLive && failures > 0 ? "fail" : failures > 0 || warnings > 0 ? "warn" : "pass";
  const score = Math.max(0, 100 - failures * 12 - warnings * 5);
  report.summary = {
    status,
    score,
    canClaimRealLiveAcceptance: Boolean(report.v33?.summary?.canClaimRealLiveAcceptance) && !blocker,
    canClaimRealCallAcceptance: Boolean(report.v33?.summary?.canClaimRealCallAcceptance),
    canClaimRealDmAcceptance: Boolean(report.v33?.summary?.canClaimRealDmAcceptance),
    firstBlocker: blocker,
    nextAction: nextActionFor(blocker),
    v33Report: report.v33?.artifacts?.report || report.v33ReportPath || "",
    v18Report: report.v33?.summary?.v18Report || "",
  };
}

function runV33(report, options, artifactDir) {
  const args = [
    V33_SCRIPT,
    "--json",
    "--artifact-root",
    path.join(artifactDir, "v33"),
    "--timeout-ms",
    String(options.timeoutMs),
    ...options.passThrough.filter((arg) => arg !== "--json"),
  ];
  if (!options.requireLive && !args.includes("--plan-only")) args.push("--plan-only");
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 220 * 1024 * 1024,
    timeout: Math.max(options.timeoutMs + 30000, 90000),
  });
  report.v33Execution = {
    command: `${process.execPath} ${args.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    stdoutTail: result.stdout?.slice(-5000) || "",
    stderrTail: result.stderr?.slice(-5000) || "",
  };
  try {
    report.v33 = parseJsonOutput(result.stdout);
  } catch (error) {
    report.v33Execution.parseError = error.message;
    const reportPath = result.stdout?.match(/Report:\s*(.+report\.json)/)?.[1]?.trim();
    if (reportPath) report.v33 = JSON.parse(fsSync.readFileSync(reportPath, "utf8"));
  }
  if (!report.v33) throw new Error(`V33 report missing; exit=${result.status}; ${report.v33Execution.parseError || ""}`);
  report.v33ReportPath = report.v33?.artifacts?.report || "";
}

function makeCorrelation() {
  const random = Math.random().toString(16).slice(2, 18).padEnd(16, "0");
  const runId = `v34-live-evidence-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V34`,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V34 Live Evidence Blocker QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Real live acceptance: ${report.summary.canClaimRealLiveAcceptance}`);
  lines.push(`First blocker: ${report.summary.firstBlocker?.layer || "none"}`);
  lines.push(`Next action: ${report.summary.nextAction}`);
  lines.push("");
  lines.push("## Blockers");
  for (const blocker of report.blockers) {
    lines.push(`- ${blocker.status.toUpperCase()} ${blocker.layer}: ${blocker.detail}`);
  }
  lines.push("");
  lines.push("## Runtime Probes");
  for (const [key, probe] of Object.entries(report.runtime.probes)) {
    lines.push(`- ${key}: ${probe.status} ${probe.endpoint}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V34 report: ${report.artifacts.report}`);
  lines.push(`- V34 markdown: ${report.artifacts.markdown}`);
  lines.push(`- Blocker graph: ${report.artifacts.graph}`);
  lines.push(`- Nested V33 report: ${report.summary.v33Report}`);
  lines.push(`- Nested V18 report: ${report.summary.v18Report}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V34",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      api: options.api,
      requireLive: options.requireLive,
      liveBatch: options.liveBatch,
      allowlist: options.allowlistPath || "",
    },
    researchBasis: [
      "Playwright traces are used as browser-side evidence for actions, DOM snapshots, screenshots, network, and console debugging.",
      "W3C Trace Context/OpenTelemetry propagation is used as the model for correlating frontend, API, telephony, and persistence probes.",
      "Asterisk AMI Originate plus CDR/CEL-style call records define the telephone-side evidence needed beyond a clicked button.",
    ],
    correlation: makeCorrelation(),
    runtime: {
      allowlistProbePhone: "",
      probes: {},
    },
    graph: {
      nodes: [],
      edges: [],
    },
    blockers: [],
    checks: [],
    v33Execution: null,
    v33ReportPath: "",
    v33: null,
    summary: {},
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "live-evidence.md"),
      graph: path.join(artifactDir, "blocker-graph.json"),
    },
  };

  try {
    if (options.fromReport) {
      report.v33 = await readJson(options.fromReport);
      report.v33ReportPath = options.fromReport;
      report.v33Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null };
    } else {
      runV33(report, options, artifactDir);
    }
    await collectRuntimeEvidence(report, options);
    classifyBlockers(report, options);
    for (const blocker of report.blockers) addCheck(report, `V34 blocker: ${blocker.layer}`, blocker.status, blocker.detail, blocker.data);
  } catch (error) {
    addCheck(report, "V34 QA runner", "fail", error.stack || error.message);
    pushBlocker(report, "v34_runner", "fail", error.message);
  }

  summarize(report, options);
  await writeJson(report.artifacts.graph, report.graph);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V34 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 realLive=${report.summary.canClaimRealLiveAcceptance}`);
    console.log(`First blocker: ${report.summary.firstBlocker?.layer || "none"}`);
    console.log(`Next action: ${report.summary.nextAction}`);
    console.log(`Report: ${report.artifacts.report}`);
  }

  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
