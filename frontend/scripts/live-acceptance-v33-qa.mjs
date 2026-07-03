#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v33-live-acceptance-qa");
const V18_SCRIPT = path.join("scripts", "live-business-v18-qa.mjs");

const optionsWithValue = new Set([
  "--url",
  "--api",
  "--cdp",
  "--desktop-app",
  "--cdp-port",
  "--timeout-ms",
  "--allowlist",
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

const ownOptionsWithValue = new Set(["--artifact-root", "--from-report"]);

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    timeoutMs: 180000,
    json: false,
    planOnly: false,
    requireLive: false,
    liveBatch: false,
    confirmRealData: false,
    confirmLiveCall: false,
    confirmLiveDm: false,
    confirmLiveComment: false,
    confirmLiveBatch: false,
    confirmProductionWrite: false,
    allowlistPath: "",
    maxCalls: 1,
    maxSends: 1,
    city: "",
    category: "",
    phone: "",
    merchantName: "",
    dmMessage: "",
    platform: "",
    forwardArgs: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(10000, Number(next) || 180000);
      index += 1;
    } else if (arg === "--allowlist" && next) {
      options.allowlistPath = path.resolve(next);
      options.forwardArgs.push(arg, path.resolve(next));
      index += 1;
    } else if (arg === "--max-calls" && next) {
      options.maxCalls = Math.max(0, Number(next) || 0);
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--max-sends" && next) {
      options.maxSends = Math.max(0, Number(next) || 0);
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--city" && next) {
      options.city = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--category" && next) {
      options.category = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--phone" && next) {
      options.phone = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--merchant-name" && next) {
      options.merchantName = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--dm-message" && next) {
      options.dmMessage = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--platform" && next) {
      options.platform = next;
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (optionsWithValue.has(arg) && next) {
      options.forwardArgs.push(arg, next);
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--plan-only") {
      options.planOnly = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--require-live") {
      options.requireLive = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--live-batch") {
      options.liveBatch = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-real-data") {
      options.confirmRealData = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-live-call") {
      options.confirmLiveCall = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-live-dm" || arg === "--confirm-live-send") {
      options.confirmLiveDm = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-live-comment") {
      options.confirmLiveComment = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-live-batch") {
      options.confirmLiveBatch = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--confirm-production-write") {
      options.confirmProductionWrite = true;
      options.forwardArgs.push(arg);
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      options.forwardArgs.push(arg);
    }
  }

  return options;
}

function printHelp() {
  console.log(`AI ACQ V33 real live acceptance QA

Safe readiness plan:
  npm run qa:v33:plan -- --json --allowlist qa/v33-real-live-allowlist.example.json

Strict live acceptance, after exact approval for the listed recipients:
  npm run qa:v33:live -- --allowlist qa/v33-real-live-allowlist.json \\
    --max-calls 1 --max-sends 1 --interval-ms 8000 --live-batch --batch-call-mode both \\
    --confirm-real-data --confirm-live-call --confirm-live-send \\
    --confirm-live-batch --confirm-production-write

V33 passes only when V18 evidence proves real data writes, a real accepted call with cellular/media/human/AI evidence, and a real private-message send with conversation/message evidence.
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

function normalizeChannels(raw) {
  const channels = raw.channels || raw.channel || [];
  if (Array.isArray(channels)) return channels.map((item) => String(item).trim()).filter(Boolean);
  if (typeof channels === "string") return channels.split(/[,\s]+/).map((item) => item.trim()).filter(Boolean);
  return [];
}

function hasPlaceholder(value) {
  return /REPLACE|请替换|example\.com|测试商家|真实商家A|真实商家B/i.test(String(value || ""));
}

async function inspectAllowlist(options) {
  const contract = {
    path: options.allowlistPath || "",
    exists: false,
    recipients: 0,
    callRecipients: 0,
    sendRecipients: 0,
    issues: [],
    preview: [],
  };
  if (!options.allowlistPath) {
    contract.issues.push("missing --allowlist for strongest real live acceptance");
    return contract;
  }
  try {
    const raw = JSON.parse(await fs.readFile(options.allowlistPath, "utf8"));
    contract.exists = true;
    const rows = Array.isArray(raw) ? raw : [...(raw.calls || []), ...(raw.sends || []), ...(raw.recipients || [])];
    contract.recipients = rows.length;
    rows.forEach((row, index) => {
      const channels = normalizeChannels(row);
      const inferredChannels = channels.length ? channels : [row.phone ? "call" : "", row.dmMessage || row.message ? "dm" : ""].filter(Boolean);
      const phone = String(row.phone || row.mobile || row.tel || "").trim();
      const platform = String(row.platform || "").trim();
      const message = String(row.dmMessage || row.message || "").trim();
      const name = String(row.name || row.merchantName || row.merchant || "").trim();
      if (inferredChannels.includes("call")) contract.callRecipients += 1;
      if (inferredChannels.includes("dm") || inferredChannels.includes("send")) contract.sendRecipients += 1;
      if (hasPlaceholder(name) || hasPlaceholder(phone) || hasPlaceholder(row.platformUrl) || hasPlaceholder(message)) {
        contract.issues.push(`recipient[${index}] still contains placeholder/example data`);
      }
      if ((inferredChannels.includes("call") || options.confirmLiveCall) && phone.replace(/\D/g, "").length < 7) {
        contract.issues.push(`recipient[${index}] call channel missing real dialable phone`);
      }
      if ((inferredChannels.includes("dm") || inferredChannels.includes("send")) && !message) {
        contract.issues.push(`recipient[${index}] dm channel missing dmMessage`);
      }
      if ((inferredChannels.includes("dm") || inferredChannels.includes("send")) && !["美团", "饿了么", "抖音"].includes(platform)) {
        contract.issues.push(`recipient[${index}] dm channel unsupported or missing platform=${platform || "missing"}`);
      }
      if (row.authorized !== true && row.consent !== true && row.testApproved !== true) {
        contract.issues.push(`recipient[${index}] missing authorized:true/consent:true/testApproved:true`);
      }
      contract.preview.push({
        index,
        channels: inferredChannels,
        name: name || `recipient-${index + 1}`,
        phone: maskPhone(phone),
        platform,
        hasMessage: Boolean(message),
        authorized: row.authorized === true || row.consent === true || row.testApproved === true,
      });
    });
    if (rows.length === 0) contract.issues.push("allowlist has no recipients");
    if (contract.callRecipients < 1) contract.issues.push("allowlist must include at least one call recipient");
    if (contract.sendRecipients < 1) contract.issues.push("allowlist must include at least one private-message recipient");
    if (options.maxCalls < 1) contract.issues.push("--max-calls must be >= 1 for V33 real call acceptance");
    if (options.maxSends < 1) contract.issues.push("--max-sends must be >= 1 for V33 real private-message acceptance");
  } catch (error) {
    contract.issues.push(`allowlist read/parse failed: ${error.message}`);
  }
  return contract;
}

function inspectSingleInputs(options) {
  const issues = [];
  if (!options.city.trim()) issues.push("missing --city");
  if (!options.category.trim()) issues.push("missing --category");
  if (!options.phone.trim() && !options.allowlistPath) issues.push("missing --phone or --allowlist with call recipient");
  if (!options.dmMessage.trim() && !options.allowlistPath) issues.push("missing --dm-message or --allowlist with dmMessage");
  if (hasPlaceholder(options.phone) || hasPlaceholder(options.merchantName) || hasPlaceholder(options.dmMessage)) {
    issues.push("single-flow inputs contain placeholder/example data");
  }
  return {
    city: Boolean(options.city.trim()),
    category: Boolean(options.category.trim()),
    phone: options.phone ? maskPhone(options.phone) : "",
    hasDmMessage: Boolean(options.dmMessage.trim()),
    issues,
  };
}

function statusForMissing(options) {
  return options.requireLive ? "fail" : "warn";
}

function addCheck(report, name, status, detail, data = undefined) {
  report.checks.push({ name, status, detail, data });
}

function checksMatching(v18, pattern) {
  return (v18?.checks || []).filter((check) => pattern.test(check.name));
}

function anyPass(v18, pattern) {
  return checksMatching(v18, pattern).some((check) => check.status === "pass");
}

function requirePass(v18, pattern, label) {
  const matches = checksMatching(v18, pattern);
  return {
    label,
    status: matches.some((check) => check.status === "pass") ? "pass" : "fail",
    detail: matches.length
      ? matches.map((check) => `${check.status}:${check.name}`).join(" | ")
      : "missing evidence",
  };
}

function evaluateLiveEvidence(report, options) {
  const v18 = report.v18;
  const missingStatus = statusForMissing(options);
  const addEvidence = (group, evidence) => {
    report.evidence[group].push(evidence);
    addCheck(report, evidence.label, evidence.status === "pass" ? "pass" : missingStatus, evidence.detail);
  };

  addEvidence("realData", requirePass(v18, /V18 真实数据: 必需数据齐备|V18\.2 受控批量: 白名单与预算/, "V33 真实数据: 输入/白名单可验收"));
  addEvidence("realData", requirePass(v18, /V18 真实写入确认/, "V33 真实数据: 写入确认"));
  addEvidence("realData", requirePass(v18, /V18 生产写入确认/, "V33 真实数据: 生产写入确认"));

  for (const item of [
    [/真实外呼 .*请求被网关接收/, "V33 真实拨号: 网关接受"],
    [/真实外呼 .*蜂窝侧确认/, "V33 真实拨号: 蜂窝侧确认"],
    [/真实外呼 .*媒体链路确认/, "V33 真实拨号: 媒体链路确认"],
    [/真实外呼 .*真人语音确认/, "V33 真实拨号: 真人语音确认"],
    [/真实外呼 .*AI 首句播出确认/, "V33 真实拨号: AI 播出确认"],
    [/真实外呼 .*对话验收通过/, "V33 真实拨号: 对话验收"],
  ]) {
    addEvidence("call", requirePass(v18, item[0], item[1]));
  }

  const dmStart = anyPass(v18, /真实私信: 真发送执行/) || anyPass(v18, /V18\.2 批量私信任务: 启动真实发送/);
  const dmEvidence = anyPass(v18, /真实私信: 会话\/消息证据/) || anyPass(v18, /V18\.2 批量私信任务: 消息记录落库/);
  addEvidence("dm", {
    label: "V33 真实私信: 发送动作执行",
    status: dmStart ? "pass" : "fail",
    detail: dmStart ? "V18 reported live DM send start" : "missing live DM send evidence",
  });
  addEvidence("dm", {
    label: "V33 真实私信: 会话/消息证据",
    status: dmEvidence ? "pass" : "fail",
    detail: dmEvidence ? "V18 reported conversation/message evidence" : "missing conversation/message evidence",
  });

  const tracePath = v18?.artifacts?.trace || "";
  const traceExists = tracePath && fsSync.existsSync(tracePath);
  addCheck(
    report,
    "V33 证据包: Playwright trace",
    traceExists || options.planOnly ? "pass" : missingStatus,
    traceExists ? tracePath : options.planOnly ? "plan-only does not record browser trace" : "missing trace.zip",
  );

  const criticalEvidence = [...report.evidence.realData, ...report.evidence.call, ...report.evidence.dm];
  const allCriticalPass = criticalEvidence.every((item) => item.status === "pass");
  const v18HadFailure = (v18?.checks || []).some((check) => check.status === "fail");
  const canClaimRealLiveAcceptance = allCriticalPass && !v18HadFailure;
  report.evaluation = {
    allCriticalPass,
    v18HadFailure,
    canClaimRealLiveAcceptance,
    canClaimRealCallAcceptance: report.evidence.call.every((item) => item.status === "pass"),
    canClaimRealDmAcceptance: report.evidence.dm.every((item) => item.status === "pass"),
    canClaimRealDataAcceptance: report.evidence.realData.every((item) => item.status === "pass"),
  };
}

function summarize(report, options) {
  const failures = report.checks.filter((check) => check.status === "fail").length;
  const warnings = report.checks.filter((check) => check.status === "warn").length;
  const strictLiveMissing = options.requireLive && !report.evaluation?.canClaimRealLiveAcceptance;
  const status = failures > 0 || strictLiveMissing ? "fail" : warnings > 0 ? "warn" : "pass";
  const score = Math.max(0, 100 - failures * 12 - warnings * 4);
  report.summary = {
    status,
    score,
    checks: report.checks.length,
    failures,
    warnings,
    canClaimRealLiveAcceptance: Boolean(report.evaluation?.canClaimRealLiveAcceptance),
    canClaimRealCallAcceptance: Boolean(report.evaluation?.canClaimRealCallAcceptance),
    canClaimRealDmAcceptance: Boolean(report.evaluation?.canClaimRealDmAcceptance),
    canClaimRealDataAcceptance: Boolean(report.evaluation?.canClaimRealDataAcceptance),
    liveActionsStillConfirmationGated: !options.requireLive || !Boolean(report.evaluation?.canClaimRealLiveAcceptance),
    v18Report: report.v18?.artifacts?.report || report.v18ReportPath || "",
  };
}

function runV18(report, options, artifactDir, forcePlanOnly = false) {
  const args = [
    V18_SCRIPT,
    "--json",
    "--artifact-root",
    path.join(artifactDir, "v18"),
    "--timeout-ms",
    String(options.timeoutMs),
    "--max-calls",
    String(options.maxCalls),
    "--max-sends",
    String(options.maxSends),
    ...options.forwardArgs.filter((arg) => arg !== "--json"),
  ];
  if ((forcePlanOnly || (!options.requireLive && !options.planOnly)) && !args.includes("--plan-only")) {
    args.push("--plan-only");
  }
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 200 * 1024 * 1024,
    timeout: Math.max(options.timeoutMs + 30000, 90000),
  });
  report.v18Execution = {
    command: `${process.execPath} ${args.map((arg) => (isSensitiveKey(arg) ? "[redacted]" : arg)).join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    stdoutTail: result.stdout?.slice(-5000) || "",
    stderrTail: result.stderr?.slice(-5000) || "",
  };
  try {
    report.v18 = parseJsonOutput(result.stdout);
  } catch (error) {
    report.v18Execution.parseError = error.message;
    const reportPath = result.stdout?.match(/Report:\s*(.+report\.json)/)?.[1]?.trim();
    if (reportPath) {
      report.v18 = JSON.parse(fsSync.readFileSync(reportPath, "utf8"));
    }
  }
  if (!report.v18) throw new Error(`V18 report missing; exit=${result.status}; ${report.v18Execution.parseError || ""}`);
  report.v18ReportPath = report.v18?.artifacts?.report || "";
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V33 Real Live Acceptance QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Real live acceptance: ${report.summary.canClaimRealLiveAcceptance}`);
  lines.push(`Real call acceptance: ${report.summary.canClaimRealCallAcceptance}`);
  lines.push(`Real private-message acceptance: ${report.summary.canClaimRealDmAcceptance}`);
  lines.push("");
  lines.push("## Checks");
  for (const check of report.checks) {
    lines.push(`- ${check.status.toUpperCase()} ${check.name}: ${check.detail}`);
  }
  lines.push("");
  lines.push("## Allowlist");
  lines.push(`- Path: ${report.liveContract.allowlist.path || ""}`);
  lines.push(`- Recipients: ${report.liveContract.allowlist.recipients}`);
  lines.push(`- Calls: ${report.liveContract.allowlist.callRecipients}`);
  lines.push(`- Sends: ${report.liveContract.allowlist.sendRecipients}`);
  for (const issue of report.liveContract.allowlist.issues || []) {
    lines.push(`- Issue: ${issue}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V33 report: ${report.artifacts.report}`);
  lines.push(`- V33 markdown: ${report.artifacts.markdown}`);
  lines.push(`- Nested V18 report: ${report.summary.v18Report}`);
  lines.push(`- Nested V18 trace: ${report.v18?.artifacts?.trace || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V33",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      mode: options.requireLive ? "strict-live" : "plan",
      planOnly: options.planOnly || !options.requireLive,
      requireLive: options.requireLive,
      liveBatch: options.liveBatch,
      maxCalls: options.maxCalls,
      maxSends: options.maxSends,
      confirmations: {
        realData: options.confirmRealData,
        liveCall: options.confirmLiveCall,
        liveDm: options.confirmLiveDm,
        liveComment: options.confirmLiveComment,
        liveBatch: options.confirmLiveBatch,
        productionWrite: options.confirmProductionWrite,
      },
    },
    researchBasis: [
      "Playwright trace artifacts keep action, DOM snapshot, screenshot, network, and console evidence for live workflow debugging.",
      "OpenTelemetry-style correlation makes logs/traces/events useful only when the same execution context can be followed across layers.",
      "Asterisk AMI Originate is the real call-generation action, so live acceptance must prove accepted originate plus channel/media/business events rather than only a clicked UI button.",
      "Schemathesis stateful testing remains useful below this layer for generated API chains, but V33's pass condition is live business evidence.",
    ],
    liveContract: {
      allowlist: {},
      singleInputs: {},
      blockingIssues: [],
    },
    checks: [],
    evidence: {
      realData: [],
      call: [],
      dm: [],
    },
    v18Execution: null,
    v18ReportPath: "",
    v18: null,
    evaluation: {},
    summary: {},
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "live-acceptance.md"),
    },
  };

  try {
    report.liveContract.allowlist = await inspectAllowlist(options);
    report.liveContract.singleInputs = inspectSingleInputs(options);
    report.liveContract.blockingIssues = [
      ...report.liveContract.allowlist.issues.filter((issue) => !/^missing --allowlist/.test(issue) || options.liveBatch || options.requireLive),
      ...report.liveContract.singleInputs.issues.filter(() => !options.allowlistPath),
    ];

    const contractStatus = report.liveContract.blockingIssues.length === 0 ? "pass" : statusForMissing(options);
    addCheck(
      report,
      "V33 真实验收合同: 真实数据/授权/预算",
      contractStatus,
      report.liveContract.blockingIssues.length === 0 ? "contract ready" : report.liveContract.blockingIssues.join(" | "),
      report.liveContract,
    );

    const hasAllLiveConfirmations =
      options.confirmRealData &&
      options.confirmProductionWrite &&
      options.confirmLiveCall &&
      options.confirmLiveDm &&
      (!options.liveBatch || options.confirmLiveBatch);
    addCheck(
      report,
      "V33 真实验收合同: 拨号/私信/写入确认",
      hasAllLiveConfirmations ? "pass" : statusForMissing(options),
      `realData=${options.confirmRealData}, liveCall=${options.confirmLiveCall}, liveDm=${options.confirmLiveDm}, liveBatch=${options.confirmLiveBatch}, productionWrite=${options.confirmProductionWrite}`,
    );

    if (options.fromReport) {
      report.v18 = await readJson(options.fromReport);
      report.v18ReportPath = options.fromReport;
      report.v18Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null };
    } else {
      const forcePlanOnly = options.requireLive && report.liveContract.blockingIssues.length > 0;
      runV18(report, options, artifactDir, forcePlanOnly);
      if (forcePlanOnly) {
        addCheck(report, "V33 安全阻断: 未执行 live 动作", "fail", "live contract has blocking issues, nested V18 was forced to plan-only");
      }
    }
    evaluateLiveEvidence(report, options);
  } catch (error) {
    addCheck(report, "V33 QA runner", "fail", error.stack || error.message);
  }

  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V33 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 realLive=${report.summary.canClaimRealLiveAcceptance}`);
    console.log(`Real call: ${report.summary.canClaimRealCallAcceptance}; real DM: ${report.summary.canClaimRealDmAcceptance}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Evidence: ${report.artifacts.markdown}`);
  }

  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
