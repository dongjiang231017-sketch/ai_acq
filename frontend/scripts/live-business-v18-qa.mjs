#!/usr/bin/env node
import { chromium } from "playwright";
import { randomUUID } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v18-live-business-qa");
const DEFAULT_URL = process.env.AI_ACQ_QA_URL || "http://127.0.0.1:4178/";
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";
const DEPLOYED_API = "http://101.132.63.159/ai-acq-api/api";
const COLLECTION_PROVIDERS = new Set(["amap", "baidu", "tencent", "public_web", "meituan", "shangou", "douyin"]);
const FRONTEND_COLLECTION_PROVIDERS = new Set(["amap", "baidu", "tencent", "public_web"]);
const DM_SUPPORTED_PLATFORMS = new Set(["美团", "饿了么", "抖音"]);

const mutationRules = [
  { name: "lead-create", pattern: /\/api\/leads\b/ },
  { name: "outbound-task-create", pattern: /\/api\/outbound\/tasks\b/ },
  { name: "outbound-task-start", pattern: /\/api\/outbound\/tasks\/[^/]+\/start\b/ },
  { name: "live-test-call", pattern: /\/api\/outbound\/telephony\/test-call\b/ },
  { name: "line-recovery", pattern: /\/api\/outbound\/telephony\/recover-line\b/ },
  { name: "collection-run", pattern: /\/api\/collections\/tasks\/[^/]+\/run\b/ },
  { name: "comment-intercept", pattern: /\/api\/direct-messages\/intercepts\// },
  { name: "dm-send-or-login", pattern: /\/api\/direct-messages\// },
  { name: "voice-mutation", pattern: /\/api\/voice\/.*(?:samples|training-jobs|preview)/ },
];

function parseArgs(argv) {
  const options = {
    url: DEFAULT_URL,
    api: DEFAULT_API,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    json: false,
    headed: false,
    noTrace: false,
    timeoutMs: 180000,
    cdp: "",
    desktopApp: "",
    cdpPort: 9226,
    planOnly: false,
    requireLive: false,
    liveBatch: false,
    confirmRealData: false,
    confirmLiveCall: false,
    confirmLiveDm: false,
    confirmLiveComment: false,
    confirmLiveBatch: false,
    confirmProductionWrite: false,
    autoLocalAccount: true,
    allowlistPath: process.env.AI_ACQ_LIVE_ALLOWLIST || "",
    maxCalls: Number(process.env.AI_ACQ_LIVE_MAX_CALLS || "1"),
    maxSends: Number(process.env.AI_ACQ_LIVE_MAX_SENDS || "0"),
    batchIntervalMs: Number(process.env.AI_ACQ_LIVE_BATCH_INTERVAL_MS || "8000"),
    batchCallMode: process.env.AI_ACQ_LIVE_BATCH_CALL_MODE || "sequence",
    stopOnCritical: false,
    username: process.env.AI_ACQ_LIVE_USERNAME || "",
    password: process.env.AI_ACQ_LIVE_PASSWORD || "",
    phone: process.env.AI_ACQ_LIVE_PHONE || "",
    callerId: process.env.AI_ACQ_LIVE_CALLER_ID || "",
    merchantName: process.env.AI_ACQ_LIVE_MERCHANT_NAME || "",
    city: process.env.AI_ACQ_LIVE_CITY || "",
    category: process.env.AI_ACQ_LIVE_CATEGORY || "",
    contactName: process.env.AI_ACQ_LIVE_CONTACT_NAME || "",
    platform: process.env.AI_ACQ_LIVE_PLATFORM || "视频号",
    platformUrl: process.env.AI_ACQ_LIVE_PLATFORM_URL || "",
    collectionProvider: process.env.AI_ACQ_LIVE_COLLECTION_PROVIDER || "amap",
    collectionKeyword: process.env.AI_ACQ_LIVE_COLLECTION_KEYWORD || "",
    collectionTarget: Number(process.env.AI_ACQ_LIVE_COLLECTION_TARGET || "8"),
    commentPlatform: process.env.AI_ACQ_LIVE_COMMENT_PLATFORM || "抖音",
    commentSourceUrl: process.env.AI_ACQ_LIVE_COMMENT_SOURCE_URL || "",
    dmMessage: process.env.AI_ACQ_LIVE_DM_MESSAGE || "",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--url" && next) {
      options.url = next;
      index += 1;
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--cdp" && next) {
      options.cdp = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--desktop-app" && next) {
      options.desktopApp = path.resolve(next);
      index += 1;
    } else if (arg === "--cdp-port" && next) {
      options.cdpPort = Number(next);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Number(next);
      index += 1;
    } else if (arg === "--allowlist" && next) {
      options.allowlistPath = path.resolve(next);
      index += 1;
    } else if (arg === "--max-calls" && next) {
      options.maxCalls = Number(next);
      index += 1;
    } else if (arg === "--max-sends" && next) {
      options.maxSends = Number(next);
      index += 1;
    } else if (arg === "--interval-ms" && next) {
      options.batchIntervalMs = Number(next);
      index += 1;
    } else if (arg === "--batch-call-mode" && next) {
      options.batchCallMode = next;
      index += 1;
    } else if (arg === "--username" && next) {
      options.username = next;
      index += 1;
    } else if (arg === "--password" && next) {
      options.password = next;
      index += 1;
    } else if (arg === "--phone" && next) {
      options.phone = next;
      index += 1;
    } else if (arg === "--caller-id" && next) {
      options.callerId = next;
      index += 1;
    } else if (arg === "--merchant-name" && next) {
      options.merchantName = next;
      index += 1;
    } else if (arg === "--city" && next) {
      options.city = next;
      index += 1;
    } else if (arg === "--category" && next) {
      options.category = next;
      index += 1;
    } else if (arg === "--contact-name" && next) {
      options.contactName = next;
      index += 1;
    } else if (arg === "--platform" && next) {
      options.platform = next;
      index += 1;
    } else if (arg === "--platform-url" && next) {
      options.platformUrl = next;
      index += 1;
    } else if (arg === "--collection-provider" && next) {
      options.collectionProvider = next;
      index += 1;
    } else if (arg === "--collection-keyword" && next) {
      options.collectionKeyword = next;
      index += 1;
    } else if (arg === "--collection-target" && next) {
      options.collectionTarget = Number(next);
      index += 1;
    } else if (arg === "--comment-platform" && next) {
      options.commentPlatform = next;
      index += 1;
    } else if (arg === "--comment-source-url" && next) {
      options.commentSourceUrl = next;
      index += 1;
    } else if (arg === "--dm-message" && next) {
      options.dmMessage = next;
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--no-trace") {
      options.noTrace = true;
    } else if (arg === "--plan-only") {
      options.planOnly = true;
    } else if (arg === "--require-live") {
      options.requireLive = true;
    } else if (arg === "--live-batch") {
      options.liveBatch = true;
    } else if (arg === "--confirm-real-data") {
      options.confirmRealData = true;
    } else if (arg === "--confirm-live-call") {
      options.confirmLiveCall = true;
    } else if (arg === "--confirm-live-dm") {
      options.confirmLiveDm = true;
    } else if (arg === "--confirm-live-send") {
      options.confirmLiveDm = true;
    } else if (arg === "--confirm-live-comment") {
      options.confirmLiveComment = true;
    } else if (arg === "--confirm-live-batch") {
      options.confirmLiveBatch = true;
    } else if (arg === "--confirm-production-write") {
      options.confirmProductionWrite = true;
    } else if (arg === "--no-auto-local-account") {
      options.autoLocalAccount = false;
    } else if (arg === "--stop-on-critical") {
      options.stopOnCritical = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }

  if ((options.desktopApp || options.cdp) && options.api === DEFAULT_API) {
    options.api = DEPLOYED_API;
  }

  return options;
}

function printHelp() {
  console.log(`AI ACQ V18 live business-flow QA

Safe planning:
  npm run qa:v18:plan -- --json

Real acceptance, after explicit user approval:
  npm run qa:v18:live -- --url <client-url> --api <api-base> \\
    --username <account> --password <password> \\
    --city <city> --category <category> --collection-provider amap \\
    --confirm-real-data --confirm-live-call --confirm-live-dm \\
    --confirm-live-comment --confirm-production-write

Controlled live batch acceptance, after explicit user approval:
  npm run qa:v18:live-batch -- --allowlist ./qa/v18-live-allowlist.json \\
    --max-calls 5 --max-sends 5 --interval-ms 8000 --batch-call-mode both \\
    --confirm-real-data --confirm-live-call --confirm-live-send \\
    --confirm-live-batch --confirm-production-write

V18 does not pass real acceptance with fake data. It first collects real lead data, then uses collected records for calling, DM, and comment-intercept checks. Live calls, live sends, and production writes remain blocked unless the exact confirmation flags are present.
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

function redact(value, options, key = "") {
  if (value == null) return value;
  if (typeof value === "string") {
    if (/authorization|token|secret/i.test(key)) {
      return value ? "[secret-redacted]" : value;
    }
    let next = value;
    if (options.password) {
      next = next.split(options.password).join("[password-provided]");
    }
    const phoneDigits = String(options.phone || "").replace(/\D/g, "");
    if (phoneDigits.length >= 7) {
      next = next.split(options.phone).join(maskPhone(options.phone));
      next = next.split(phoneDigits).join(maskPhone(phoneDigits));
    }
    next = next.replace(/\b1[3-9]\d{9}\b/g, (match) => maskPhone(match));
    next = next.replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[token-redacted]");
    return next;
  }
  if (Array.isArray(value)) return value.map((item) => redact(item, options, key));
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([itemKey, item]) => [itemKey, redact(item, options, itemKey)]));
  }
  return value;
}

async function writeJson(file, value, options) {
  await fs.writeFile(file, `${JSON.stringify(redact(value, options), null, 2)}\n`, "utf8");
}

function addCheck(report, name, status, detail, data = undefined) {
  report.checks.push({ name, status, detail, data });
}

function statusRank(status) {
  if (status === "fail") return 3;
  if (status === "warn") return 2;
  return 1;
}

function summarize(report) {
  const failures = report.checks.filter((check) => check.status === "fail").length;
  const warnings = report.checks.filter((check) => check.status === "warn").length;
  const maxRank = report.checks.reduce((rank, check) => Math.max(rank, statusRank(check.status)), 1);
  const score = Math.max(
    0,
    100 -
      failures * 14 -
      warnings * 4 -
      report.browser.consoleErrors.length * 8 -
      report.browser.pageErrors.length * 10 -
      report.browser.failedRequests.length * 6 -
      report.browser.blockedMutations.length * 4,
  );
  report.summary = {
    status:
      maxRank === 3 || report.browser.pageErrors.length > 0
        ? "fail"
        : maxRank === 2 || report.browser.blockedMutations.length > 0 || score < 92
          ? "warn"
          : "pass",
    score,
    checks: report.checks.length,
    failures,
    warnings,
    consoleErrors: report.browser.consoleErrors.length,
    pageErrors: report.browser.pageErrors.length,
    failedRequests: report.browser.failedRequests.length,
    blockedMutations: report.browser.blockedMutations.length,
  };
}

async function apiRequest(report, options, endpoint, requestOptions = {}) {
  const headers = {
    Accept: "application/json",
    ...(requestOptions.body ? { "Content-Type": "application/json" } : {}),
    ...(report.state.accessToken ? { Authorization: `Bearer ${report.state.accessToken}` } : {}),
    ...requestOptions.headers,
  };
  const response = await fetch(`${options.api}${endpoint}`, {
    method: requestOptions.method || "GET",
    headers,
    body: requestOptions.body ? JSON.stringify(requestOptions.body) : undefined,
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text.slice(0, 1000) };
  }
  return { ok: response.ok, status: response.status, body };
}

async function launchBrowser(headed) {
  const launchOptions = { headless: !headed, args: ["--disable-blink-features=AutomationControlled"] };
  try {
    return await chromium.launch({ ...launchOptions, channel: "chrome" });
  } catch {
    return chromium.launch(launchOptions);
  }
}

async function waitForCdp(cdpUrl, timeoutMs = 25000) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(`${cdpUrl.replace(/\/$/, "")}/json/version`);
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`CDP endpoint not ready at ${cdpUrl}: ${lastError?.message || "timeout"}`);
}

async function resolveDesktopExecutable(appPath) {
  if (!appPath.endsWith(".app")) return appPath;
  const macosDir = path.join(appPath, "Contents", "MacOS");
  const basenameCandidate = path.join(macosDir, path.basename(appPath, ".app"));
  try {
    await fs.access(basenameCandidate);
    return basenameCandidate;
  } catch {
    const entries = await fs.readdir(macosDir);
    if (!entries.length) throw new Error(`No executable found under ${macosDir}`);
    return path.join(macosDir, entries[0]);
  }
}

async function launchDesktopApp(options, report) {
  const executable = await resolveDesktopExecutable(options.desktopApp);
  const cdpUrl = `http://127.0.0.1:${options.cdpPort}`;
  const child = spawn(executable, [`--remote-debugging-port=${options.cdpPort}`], { detached: true, stdio: "ignore" });
  child.unref();
  report.browser.desktopApp = { executable, pid: child.pid, cdpUrl };
  await waitForCdp(cdpUrl, Math.min(options.timeoutMs, 30000));
  return { cdpUrl, child };
}

async function firstUsefulPage(browser) {
  const deadline = Date.now() + 20000;
  let fallbackPage = null;
  while (Date.now() < deadline) {
    const pages = browser
      .contexts()
      .flatMap((context) => context.pages())
      .filter((page) => !page.url().startsWith("devtools://"));
    fallbackPage = fallbackPage || pages[0] || null;
    for (const page of pages) {
      const title = await page.title().catch(() => "");
      const url = page.url();
      if (/视频号|商家AI|AI获客/.test(title) || /app\.asar|ai-acq|4178|ai-acq/.test(url)) return page;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (fallbackPage) return fallbackPage;
  throw new Error("No useful browser page found after connecting to CDP");
}

async function screenshot(page, report, artifactDir, name) {
  const file = path.join(artifactDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  report.artifacts.screenshots.push(file);
}

function realDataRequirements(options) {
  return [
    { key: "username", label: "真实客户账号或本地可生成账号", ok: Boolean(options.username.trim()) || options.autoLocalAccount },
    { key: "password", label: "真实客户账号密码或本地可生成密码", ok: Boolean(options.password) || options.autoLocalAccount },
    { key: "city", label: "真实城市", ok: Boolean(options.city.trim()) },
    { key: "category", label: "真实品类", ok: Boolean(options.category.trim()) },
    { key: "collectionProvider", label: "真实采集来源", ok: COLLECTION_PROVIDERS.has(options.collectionProvider) },
  ];
}

function addRealDataGate(report, options) {
  const requirements = realDataRequirements(options);
  report.matrix.realData = requirements.map((item) => ({ ...item, value: item.key === "phone" ? maskPhone(options.phone) : item.ok ? "provided" : "" }));
  const missing = requirements.filter((item) => !item.ok);
  addCheck(
    report,
    "V18 真实数据: 必需数据齐备",
    missing.length === 0 ? "pass" : options.requireLive ? "fail" : "warn",
    missing.length === 0 ? "all real-data fields provided" : `missing=${missing.map((item) => item.label).join(", ")}`,
    report.matrix.realData,
  );
  addCheck(
    report,
    "V18 真实写入确认",
    options.confirmRealData ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmRealData ? "confirmed by --confirm-real-data" : "real lead/task creation is blocked until --confirm-real-data",
  );
  addCheck(
    report,
    "V18 真实拨号确认",
    options.confirmLiveCall ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmLiveCall ? "confirmed by --confirm-live-call" : "live test-call is blocked until --confirm-live-call",
  );
  addCheck(
    report,
    "V18 真实私信确认",
    options.confirmLiveDm ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmLiveDm ? "confirmed by --confirm-live-dm" : "live private-message send is blocked until --confirm-live-dm",
  );
  addCheck(
    report,
    "V18 真实评论截流确认",
    options.confirmLiveComment ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmLiveComment ? "confirmed by --confirm-live-comment" : "live comment interception is blocked until --confirm-live-comment",
  );
  addCheck(
    report,
    "V18 生产写入确认",
    options.confirmProductionWrite ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmProductionWrite ? "confirmed by --confirm-production-write" : "production writes are blocked until --confirm-production-write",
  );
}

function normalizeChannels(raw) {
  const channels = raw.channels || raw.channel || [];
  if (Array.isArray(channels)) return channels.map((item) => String(item).trim()).filter(Boolean);
  if (typeof channels === "string" && channels.trim()) {
    return channels
      .split(/[,\s]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

function normalizeBatchEntry(raw, index, options) {
  const channels = normalizeChannels(raw);
  const phone = String(raw.phone || raw.mobile || raw.tel || "").trim();
  const platform = String(raw.platform || options.platform || "视频号").trim();
  const entry = {
    index,
    name: String(raw.name || raw.merchantName || raw.merchant || `${options.merchantName || "V18批量客户"}-${index + 1}`).trim(),
    city: String(raw.city || options.city || "").trim(),
    category: String(raw.category || options.category || "").trim(),
    contactName: String(raw.contactName || raw.contact || options.contactName || "").trim(),
    phone,
    platform,
    platformUrl: String(raw.platformUrl || raw.url || options.platformUrl || "").trim(),
    dmMessage: String(raw.dmMessage || raw.message || options.dmMessage || "").trim(),
    source: String(raw.source || "V18受控真实批量验收").trim(),
    channels,
  };
  if (entry.channels.length === 0) {
    if (entry.phone) entry.channels.push("call");
    if (DM_SUPPORTED_PLATFORMS.has(entry.platform)) entry.channels.push("dm");
  }
  return entry;
}

async function loadBatchAllowlist(report, options) {
  const plan = {
    enabled: options.liveBatch,
    path: options.allowlistPath || "",
    mode: options.batchCallMode,
    intervalMs: options.batchIntervalMs,
    maxCalls: options.maxCalls,
    maxSends: options.maxSends,
    calls: [],
    sends: [],
    issues: [],
  };
  if (!options.liveBatch) return plan;
  if (!options.allowlistPath) {
    plan.issues.push("missing --allowlist");
    return plan;
  }
  try {
    const raw = JSON.parse(await fs.readFile(options.allowlistPath, "utf8"));
    const rows = Array.isArray(raw) ? raw : [...(raw.calls || []), ...(raw.sends || []), ...(raw.recipients || [])];
    const entries = rows.map((item, index) => normalizeBatchEntry(item, index, options));
    plan.calls = entries.filter((entry) => entry.channels.includes("call")).slice(0, Math.max(0, options.maxCalls));
    plan.sends = entries.filter((entry) => entry.channels.includes("dm") || entry.channels.includes("send")).slice(0, Math.max(0, options.maxSends));
    if (entries.length === 0) plan.issues.push("allowlist has no recipients");
    if (entries.some((entry) => entry.channels.includes("call")) && options.maxCalls < 1) plan.issues.push("--max-calls must be >= 1 for call batch");
    if (entries.some((entry) => entry.channels.includes("dm") || entry.channels.includes("send")) && options.maxSends < 1) plan.issues.push("--max-sends must be >= 1 for send batch");
    for (const entry of plan.calls) {
      if (!entry.phone) plan.issues.push(`call[${entry.index}] missing phone`);
      else if (entry.phone.replace(/\D/g, "").length < 7) plan.issues.push(`call[${entry.index}] phone is not a real dialable number`);
      if (!entry.city) plan.issues.push(`call[${entry.index}] missing city`);
      if (!entry.category) plan.issues.push(`call[${entry.index}] missing category`);
    }
    for (const entry of plan.sends) {
      if (!DM_SUPPORTED_PLATFORMS.has(entry.platform)) plan.issues.push(`send[${entry.index}] unsupported platform=${entry.platform}`);
      if (!entry.dmMessage) plan.issues.push(`send[${entry.index}] missing dmMessage`);
    }
    if (!["sequence", "task", "both"].includes(options.batchCallMode)) {
      plan.issues.push("--batch-call-mode must be sequence, task, or both");
    }
    if (!Number.isFinite(options.batchIntervalMs) || options.batchIntervalMs < 3000) {
      plan.issues.push("--interval-ms must be >= 3000 for live batch pacing");
    }
  } catch (error) {
    plan.issues.push(`allowlist read/parse failed: ${error.message}`);
  }
  return plan;
}

function addBatchGate(report, options, batchPlan) {
  report.matrix.batch = {
    enabled: batchPlan.enabled,
    path: batchPlan.path,
    mode: batchPlan.mode,
    intervalMs: batchPlan.intervalMs,
    maxCalls: batchPlan.maxCalls,
    maxSends: batchPlan.maxSends,
    calls: batchPlan.calls.map((entry) => ({
      index: entry.index,
      name: entry.name,
      phone: maskPhone(entry.phone),
      city: entry.city,
      category: entry.category,
      platform: entry.platform,
    })),
    sends: batchPlan.sends.map((entry) => ({
      index: entry.index,
      name: entry.name,
      platform: entry.platform,
      city: entry.city,
      category: entry.category,
      hasMessage: Boolean(entry.dmMessage),
    })),
    issues: batchPlan.issues,
  };

  if (!options.liveBatch) {
    addCheck(report, "V18.2 受控批量: 未启用", "pass", "add --live-batch to validate real batch call/send flow");
    return;
  }

  const gateStatus = batchPlan.issues.length === 0 ? "pass" : options.requireLive ? "fail" : "warn";
  addCheck(
    report,
    "V18.2 受控批量: 白名单与预算",
    gateStatus,
    batchPlan.issues.length === 0
      ? `calls=${batchPlan.calls.length}/${options.maxCalls}, sends=${batchPlan.sends.length}/${options.maxSends}, intervalMs=${options.batchIntervalMs}, mode=${options.batchCallMode}`
      : batchPlan.issues.join(" | "),
    report.matrix.batch,
  );
  addCheck(
    report,
    "V18.2 受控批量: 批量执行确认",
    options.confirmLiveBatch ? "pass" : options.requireLive ? "fail" : "warn",
    options.confirmLiveBatch ? "confirmed by --confirm-live-batch" : "live batch is blocked until --confirm-live-batch",
  );
  if (batchPlan.calls.length > 0) {
    addCheck(
      report,
      "V18.2 批量外呼: 确认与上限",
      options.confirmLiveCall && options.confirmProductionWrite ? "pass" : options.requireLive ? "fail" : "warn",
      `confirmLiveCall=${options.confirmLiveCall}, confirmProductionWrite=${options.confirmProductionWrite}, calls=${batchPlan.calls.length}`,
    );
  }
  if (batchPlan.sends.length > 0) {
    addCheck(
      report,
      "V18.2 批量私信: 确认与上限",
      options.confirmLiveDm && options.confirmProductionWrite ? "pass" : options.requireLive ? "fail" : "warn",
      `confirmLiveDm=${options.confirmLiveDm}, confirmProductionWrite=${options.confirmProductionWrite}, sends=${batchPlan.sends.length}`,
    );
  }
}

async function collectReadiness(report, options) {
  const liveStatus = () => (options.requireLive ? "fail" : "warn");
  const endpoints = [
    ["health", "/health", true],
    ["authMe", "/auth/me", false],
    ["collectionTasks", "/collections/tasks", false],
    ["rawLeadRecords", "/collections/raw-records", false],
    ["dmConfig", "/direct-messages/config", false],
    ["dmAccounts", "/direct-messages/accounts", false],
    ["commentOverview", "/direct-messages/intercepts/overview", false],
    ["telephonyConfig", "/outbound/telephony/config", true],
    ["telephonyHealth", "/outbound/telephony/health", true],
    ["telephonyPreflight", `/outbound/telephony/preflight${options.phone.trim() ? `?phone=${encodeURIComponent(options.phone.trim())}` : ""}`, true],
    ["realtimePipeline", "/outbound/realtime/pipeline", true],
    ["liveEvents", "/outbound/realtime/live-events?limit=40", false],
    ["callRecords", "/outbound/records", false],
  ];

  for (const [name, endpoint, required] of endpoints) {
    try {
      const result = await apiRequest(report, options, endpoint);
      report.api[name] = result;
      addCheck(report, `真实服务 API: ${name}`, result.ok ? "pass" : required ? "fail" : "warn", `${endpoint} -> HTTP ${result.status}`);
    } catch (error) {
      report.api[name] = { ok: false, error: error.message };
      addCheck(report, `真实服务 API: ${name}`, required ? "fail" : "warn", error.message);
    }
  }

  const config = report.api.telephonyConfig?.body;
  const health = report.api.telephonyHealth?.body;
  const preflight = report.api.telephonyPreflight?.body;
  const pipeline = report.api.realtimePipeline?.body;
  const dmConfig = report.api.dmConfig?.body;
  const dmAccounts = report.api.dmAccounts?.body;

  if (config) {
    addCheck(report, "真实业务: 线路模式不是模拟器", config.gatewayMode === "asterisk" ? "pass" : liveStatus(), `gatewayMode=${config.gatewayMode}`);
    addCheck(report, "真实业务: 单号试拨开关已开启", config.asteriskLiveCallEnabled ? "pass" : liveStatus(), `asteriskLiveCallEnabled=${config.asteriskLiveCallEnabled}`);
    addCheck(report, "真实业务: 批量外呼保持关闭", config.asteriskBulkCallEnabled === false ? "pass" : "fail", `asteriskBulkCallEnabled=${config.asteriskBulkCallEnabled}`);
    addCheck(report, "真实业务: 语音网关配置可见", config.voiceGatewayProfile?.trunkName ? "pass" : liveStatus(), `trunk=${config.voiceGatewayProfile?.trunkName || config.asteriskTrunkName || "missing"}`);
    if (options.liveBatch && ["task", "both"].includes(options.batchCallMode)) {
      addCheck(
        report,
        "V18.2 批量外呼: 批量开关已开启",
        config.asteriskBulkCallEnabled ? "pass" : liveStatus(),
        `ASTERISK_BULK_CALL_ENABLED=${config.asteriskBulkCallEnabled}`,
      );
    }
  }

  if (health) {
    addCheck(report, "真实线路: AMI 已认证", health.authenticated ? "pass" : liveStatus(), `authenticated=${health.authenticated}, amiReachable=${health.amiReachable}`);
    addCheck(report, "真实线路: Trunk 已注册可达", health.trunkReachable === true ? "pass" : liveStatus(), `trunkReachable=${health.trunkReachable}, trunkStatus=${health.trunkStatus}`);
    addCheck(report, "真实线路: 可做单号试拨", health.readyForTestCall ? "pass" : liveStatus(), `readyForTestCall=${health.readyForTestCall}, errors=${(health.errors || []).join(" | ") || "none"}`);
  }

  if (preflight) {
    addCheck(
      report,
      "真实预检: 手机号级预检通过",
      preflight.readyForSingleNumberTest ? "pass" : liveStatus(),
      preflight.nextStep || "missing nextStep",
      preflight.steps,
    );
  }

  if (pipeline) {
    addCheck(report, "真实语音: 媒体桥已就绪", pipeline.readyForAsteriskMedia ? "pass" : liveStatus(), `mode=${pipeline.mode}, bridge=${pipeline.bridgeMode}, nextStep=${pipeline.nextStep}`);
    addCheck(report, "真实语音: 当前实时路由可见", Array.isArray(pipeline.routeOptions) && pipeline.routeOptions.some((route) => route.isActive) ? "pass" : "warn", (pipeline.routeOptions || []).map((route) => `${route.key}:${route.isActive ? "active" : "idle"}`).join(", "));
  }

  addCheck(
    report,
    "真实采集: 采集来源有效",
    COLLECTION_PROVIDERS.has(options.collectionProvider) ? "pass" : "fail",
    `provider=${options.collectionProvider}, city=${options.city || "missing"}, category=${options.category || "missing"}`,
  );

  if (dmConfig) {
    addCheck(report, "真实私信: 浏览器发送模式", dmConfig.gatewayMode === "browser" ? "pass" : liveStatus(), `gatewayMode=${dmConfig.gatewayMode}`);
    addCheck(
      report,
      "真实私信: live send 开关",
      dmConfig.browserLiveSendEnabled ? "pass" : liveStatus(),
      `browserLiveSendEnabled=${dmConfig.browserLiveSendEnabled}`,
    );
    if (options.liveBatch && options.maxSends > 0) {
      addCheck(
        report,
        "V18.2 批量私信: live send 可执行",
        dmConfig.gatewayMode === "browser" && dmConfig.browserLiveSendEnabled ? "pass" : liveStatus(),
        `gatewayMode=${dmConfig.gatewayMode}, browserLiveSendEnabled=${dmConfig.browserLiveSendEnabled}`,
      );
    }
  }
  if (Array.isArray(dmAccounts)) {
    const usableAccounts = dmAccounts.filter((account) => account.status === "可用" && account.sessionStatus === "已登录");
    addCheck(
      report,
      "真实私信: 已登录平台个人号",
      usableAccounts.length > 0 ? "pass" : liveStatus(),
      usableAccounts.length > 0
        ? usableAccounts.map((account) => `${account.platform}/${account.accountName}`).join(", ")
        : "missing logged-in platform personal account",
    );
  }
}

function isLocalApi(options) {
  try {
    const hostname = new URL(options.api).hostname;
    return ["127.0.0.1", "localhost", "::1"].includes(hostname);
  } catch {
    return false;
  }
}

function localApiPort(options) {
  try {
    const parsed = new URL(options.api);
    if (parsed.port) return Number(parsed.port);
    return parsed.protocol === "https:" ? 443 : 80;
  } catch {
    return null;
  }
}

function shellLines(command, args) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    timeout: 5000,
  });
  if (result.status !== 0 || !result.stdout) return [];
  return result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function detectLocalServerSqlite(options) {
  const port = localApiPort(options);
  if (!port) return null;
  const pids = shellLines("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"]);
  for (const pid of pids) {
    const lines = shellLines("lsof", ["-nP", "-p", pid]);
    const dbPath = lines
      .map((line) => line.match(/(\/.*\.(?:sqlite|sqlite3|db))$/)?.[1])
      .find((candidate) => candidate && !/Cookies|History|Local Storage/i.test(candidate));
    if (dbPath) {
      return {
        pid,
        path: dbPath,
        databaseUrl: `sqlite:///${dbPath}`,
      };
    }
  }
  return null;
}

function ensureLocalClientAccount(report, options) {
  if (options.username.trim() && options.password) return;
  if (options.planOnly) {
    addCheck(report, "V18 客户账号: 自动生成", "warn", "plan-only does not write user accounts");
    return;
  }
  if (!options.confirmRealData || !options.confirmProductionWrite) {
    addCheck(report, "V18 客户账号: 自动生成", options.requireLive ? "fail" : "warn", "missing --confirm-real-data or --confirm-production-write");
    return;
  }
  if (!options.autoLocalAccount) {
    addCheck(report, "V18 客户账号: 自动生成", options.requireLive ? "fail" : "warn", "disabled by --no-auto-local-account");
    return;
  }
  if (!isLocalApi(options)) {
    addCheck(report, "V18 客户账号: 自动生成", options.requireLive ? "fail" : "warn", "auto account creation only works for local API targets");
    return;
  }

  const suffix = Date.now().toString(36);
  options.username = options.username.trim() || `v18_client_${suffix}`;
  options.password = options.password || `V18-client-${suffix}-${randomUUID().slice(0, 8)}`;
  const backendRoot = path.resolve(FRONTEND_ROOT, "..", "backend");
  const python = path.join(backendRoot, ".venv", "bin", "python");
  const detectedDb = detectLocalServerSqlite(options);
  const accountEnv = detectedDb
    ? {
        ...process.env,
        DATABASE_URL: detectedDb.databaseUrl,
      }
    : process.env;
  addCheck(
    report,
    "V18 客户账号: 本地服务数据库",
    detectedDb ? "pass" : "warn",
    detectedDb
      ? `pid=${detectedDb.pid}, sqlite=${detectedDb.path}`
      : "could not detect the sqlite database opened by the local API process; falling back to backend settings",
  );
  const code = `
from sqlalchemy import select
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User

username = ${JSON.stringify(options.username)}
password = ${JSON.stringify(options.password)}
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        db.add(User(
            username=username,
            display_name="V18真实验收客户",
            phone=None,
            email=None,
            password_hash=hash_password(password),
            status="启用",
            is_superuser=False,
        ))
        db.commit()
`;
  const result = spawnSync(python, ["-c", code], {
    cwd: backendRoot,
    env: accountEnv,
    encoding: "utf8",
    timeout: 20000,
  });
  if (result.status === 0) {
    addCheck(report, "V18 客户账号: 本地生成", "pass", `username=${options.username}`);
  } else {
    const detail = (result.stderr || result.stdout || "unknown account creation failure").slice(0, 1000);
    addCheck(report, "V18 客户账号: 本地生成", options.requireLive ? "fail" : "warn", detail);
  }
}

async function loginThroughUi(page, report, options) {
  const authHeading = page.getByRole("heading", { name: /登录进入获客工作台/ });
  if ((await authHeading.count()) > 0 && (await authHeading.first().isVisible().catch(() => false))) {
    if (!options.username.trim() || !options.password) {
      addCheck(report, "真人路径: 客户账号登录", "fail", "auth gate visible but --username/--password are missing");
      return false;
    }
    await page.getByLabel("登录账号", { exact: true }).fill(options.username.trim());
    await page.getByLabel("密码", { exact: true }).fill(options.password);
    await page.getByRole("button", { name: /^登录$/ }).click();
    await page.getByRole("heading", { name: /AI外呼系统|实时工作台|商家线索库|线索采集/ }).waitFor({ state: "visible", timeout: 25000 });
  }
  const authState = await page.evaluate(() => {
    const raw = window.localStorage.getItem("ai_acq_client_auth");
    return raw ? JSON.parse(raw) : null;
  }).catch(() => null);
  report.state.accessToken = authState?.accessToken || "";
  addCheck(report, "真人路径: 客户账号登录", report.state.accessToken ? "pass" : "warn", report.state.accessToken ? `logged in as ${authState?.user?.username || "current user"}` : "no auth token visible; API state checks may be limited");
  return true;
}

function selectedCollectionKeyword(options) {
  return (options.collectionKeyword || options.category || "附近商家").trim();
}

function selectedDmMessage(options) {
  return (
    options.dmMessage ||
    `您好，看到${options.merchantName || "贵店"}在本地生活平台有获客需求，想确认是否方便了解视频号团购到店获客方案？`
  ).trim();
}

function applySelectedCollectionRecord(report, options, selected) {
  report.state.collectedLeadId = selected?.leadId || "";
  report.state.createdLeadId = selected?.leadId || "";
  if (!selected) return;
  options.merchantName = options.merchantName || selected.name || "";
  options.phone = options.phone || selected.phone || "";
  options.contactName = options.contactName || selected.name || "";
  options.platformUrl = options.platformUrl || selected.sourceUrl || "";
  options.platform = selected.provider || options.platform;
}

async function readCollectionEvidence(report, options, task, run, checkPrefix = "真实采集") {
  report.state.collectionTaskId = task?.id || report.state.collectionTaskId || "";
  report.state.collectionRunId = run?.id || report.state.collectionRunId || "";
  addCheck(report, `${checkPrefix}: 任务可由 API 查到`, task ? "pass" : "fail", `taskId=${task?.id || "missing"}, status=${task?.status || "missing"}`);
  addCheck(
    report,
    `${checkPrefix}: 运行结果`,
    run && run.status === "已完成" && (run.fetchedCount || 0) > 0 ? "pass" : "fail",
    run ? `status=${run.status}, fetched=${run.fetchedCount}, inserted=${run.insertedCount}, failed=${run.failedCount}, error=${run.errorMessage || ""}` : "missing run",
  );

  const rawRecords = await apiRequest(report, options, "/collections/raw-records");
  const records = Array.isArray(rawRecords.body)
    ? rawRecords.body.filter((record) => record.taskId === task?.id || record.runId === run?.id)
    : [];
  const callable = records.find((record) => record.leadId && record.phone);
  const anyLead = records.find((record) => record.leadId);
  const selected = callable || anyLead || records[0] || null;
  report.state.collectedRecords = Math.max(report.state.collectedRecords || 0, records.length);
  applySelectedCollectionRecord(report, options, selected);

  addCheck(
    report,
    `${checkPrefix}: 采集结果可用于后续业务`,
    selected?.leadId && selected?.phone ? "pass" : "fail",
    selected
      ? `records=${records.length}, leadId=${selected.leadId || "missing"}, merchant=${selected.name}, phone=${selected.phone ? maskPhone(selected.phone) : "missing"}, sourceUrl=${selected.sourceUrl || "missing"}, importStatus=${selected.importStatus || "missing"}`
      : "no raw collection record selected",
  );
  return selected;
}

async function runRealCollectionViaApi(report, options, provider, reason = "") {
  const taskName = `V18后端真实采集-${provider}-${options.city.trim()}-${options.category.trim()}-${Date.now().toString(36)}`;
  const created = await apiRequest(report, options, "/collections/tasks", {
    method: "POST",
    body: {
      name: taskName,
      provider,
      cities: [options.city.trim()],
      categories: [options.category.trim()],
      keywords: [selectedCollectionKeyword(options)],
      targetPerKeyword: Math.max(1, Math.min(Number(options.collectionTarget) || 8, 20)),
      remark: reason || "V18 live business QA backend collection fallback",
    },
  });
  addCheck(
    report,
    `真实采集: 后端创建任务(${provider})`,
    created.ok ? "pass" : "fail",
    created.ok ? `${taskName}, taskId=${created.body?.id || "missing"}${reason ? `, reason=${reason}` : ""}` : `HTTP ${created.status}: ${JSON.stringify(created.body).slice(0, 300)}`,
  );
  if (!created.ok || !created.body?.id) return null;

  const run = await apiRequest(report, options, `/collections/tasks/${encodeURIComponent(created.body.id)}/run`, {
    method: "POST",
    body: {},
  });
  addCheck(
    report,
    `真实采集: 后端运行任务(${provider})`,
    run.ok ? "pass" : "fail",
    run.ok ? `runId=${run.body?.id || "missing"}, status=${run.body?.status || "missing"}` : `HTTP ${run.status}: ${JSON.stringify(run.body).slice(0, 300)}`,
  );
  if (!run.ok) return null;
  return readCollectionEvidence(report, options, created.body, run.body, `真实采集: 后端${provider}`);
}

async function runRealCollectionThroughUi(page, report, options) {
  if (!FRONTEND_COLLECTION_PROVIDERS.has(options.collectionProvider)) {
    addCheck(
      report,
      "真实采集: 前端数据源入口",
      "warn",
      `frontend currently exposes amap/baidu/tencent only; using backend API for provider=${options.collectionProvider}`,
    );
    return runRealCollectionViaApi(report, options, options.collectionProvider, "frontend provider entry missing");
  }
  await page.getByRole("button", { name: /线索采集/ }).click();
  await page.getByRole("heading", { name: /新建采集任务/ }).waitFor({ state: "visible", timeout: 15000 });

  const taskName = `V18真实采集-${options.city.trim()}-${options.category.trim()}-${Date.now().toString(36)}`;
  report.state.collectionTaskName = taskName;
  const panel = page.locator("article.panel").filter({ hasText: "新建采集任务" }).first();
  const form = panel.locator("form").first();
  await form.locator("input").nth(0).fill(taskName);
  await form.locator("select").first().selectOption(options.collectionProvider);
  await form.locator('input[type="number"]').first().fill(String(Math.max(1, Math.min(Number(options.collectionTarget) || 8, 20))));
  await form.locator("input").nth(2).fill(options.city.trim());
  await form.locator("input").nth(3).fill(options.category.trim());
  await form.locator("input").nth(4).fill(selectedCollectionKeyword(options));
  await panel.getByRole("button", { name: /创建采集任务/ }).click();
  await page.getByText(taskName, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
  addCheck(report, "真实采集: 前端创建采集任务", "pass", `${taskName}, provider=${options.collectionProvider}`);

  const taskRow = page.locator(".task-row").filter({ hasText: taskName }).first();
  await taskRow.getByRole("button", { name: /^运行$/ }).click();
  await page.getByText(/采集完成|采集运行失败|未配置|采集失败/, { exact: false }).waitFor({ state: "visible", timeout: 90000 }).catch(() => {});

  const tasks = await apiRequest(report, options, "/collections/tasks");
  const task = Array.isArray(tasks.body) ? tasks.body.find((item) => item.name === taskName) : null;

  const runs = await apiRequest(report, options, "/collections/runs");
  const run = Array.isArray(runs.body) ? runs.body.find((item) => item.taskId === task?.id) : null;
  return readCollectionEvidence(report, options, task, run);
}

async function createRealLeadThroughUi(page, report, options) {
  await page.getByRole("button", { name: /商家线索库/ }).click();
  await page.getByText("新增商家线索", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
  const leadPanel = page.locator("article.panel").filter({ hasText: "新增商家线索" }).first();
  await leadPanel.getByLabel("商家名称", { exact: true }).fill(options.merchantName.trim());
  await leadPanel.getByLabel("城市", { exact: true }).fill(options.city.trim());
  await leadPanel.getByLabel("品类", { exact: true }).fill(options.category.trim());
  await leadPanel.getByLabel("联系人", { exact: true }).fill(options.contactName.trim());
  await leadPanel.getByLabel("电话", { exact: true }).fill(options.phone.trim());
  if (options.platformUrl.trim()) {
    await leadPanel.getByLabel("平台店铺 URL", { exact: true }).fill(options.platformUrl.trim());
  }
  await leadPanel.getByRole("button", { name: /保存线索/ }).click();
  await page.getByText(options.merchantName.trim(), { exact: false }).waitFor({ state: "visible", timeout: 20000 });
  addCheck(report, "真人路径: 真实线索 UI 入库", "pass", options.merchantName.trim());

  if (report.state.accessToken) {
    const leads = await apiRequest(report, options, `/leads?query=${encodeURIComponent(options.merchantName.trim())}`);
    const created = Array.isArray(leads.body) ? leads.body.find((lead) => lead.name === options.merchantName.trim()) : null;
    report.state.createdLeadId = created?.id || "";
    addCheck(report, "真实数据对账: 线索可由 API 查到", created ? "pass" : "fail", `leadId=${created?.id || "missing"}, phone=${maskPhone(options.phone)}`);
  }
}

async function createRealOutboundTaskThroughUi(page, report, options) {
  await page.getByRole("button", { name: /AI外呼系统/ }).click();
  await page.locator("section.outbound-tabs").getByRole("button", { name: /^任务列表$/ }).click();
  const taskName = `V18真实验收-${options.merchantName.trim()}-${Date.now().toString(36)}`;
  report.state.createdTaskName = taskName;

  let uiSubmitted = false;
  try {
    const outboundPanel = page.locator("article.panel").filter({ hasText: "外呼任务操作表单" }).first();
    await outboundPanel.getByLabel("任务名称", { exact: true }).fill(taskName);
    await outboundPanel.getByLabel("并发数量", { exact: true }).fill("1");
    const row = page.locator("tr").filter({ hasText: options.merchantName.trim() }).first();
    if ((await row.count()) > 0) {
      const checkbox = row.locator("input[type='checkbox']").first();
      if ((await checkbox.count()) > 0 && !(await checkbox.isChecked().catch(() => false))) {
        await checkbox.check();
      }
    }
    await outboundPanel.getByRole("button", { name: /创建外呼任务/ }).click();
    await page.getByText(taskName, { exact: false }).waitFor({ state: "visible", timeout: 12000 });
    uiSubmitted = true;
    addCheck(report, "真人路径: 真实外呼任务 UI 创建", "pass", taskName);
  } catch (error) {
    addCheck(
      report,
      "真人路径: 真实外呼任务 UI 创建",
      "warn",
      `UI did not surface created task; using API fallback with collected lead. ${String(error?.message || error).split("\n")[0]}`,
    );
  }

  if (!uiSubmitted && report.state.accessToken) {
    const leadId = report.state.createdLeadId || report.state.collectedLeadId;
    if (!leadId) {
      addCheck(report, "真实数据对账: 外呼任务 API 兜底", "fail", "missing collected lead id");
    } else {
      const createdByApi = await apiRequest(report, options, "/outbound/tasks", {
        method: "POST",
        body: {
          name: taskName,
          leadIds: [leadId],
          concurrency: 1,
          scriptId: null,
          scheduledAt: null,
        },
      });
      if (createdByApi.ok) {
        report.state.createdTaskId = createdByApi.body?.id || "";
        addCheck(report, "真实数据对账: 外呼任务 API 兜底", "pass", `taskId=${report.state.createdTaskId}, leadId=${leadId}`);
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.getByRole("button", { name: /AI外呼系统/ }).click();
        await page.locator("section.outbound-tabs").getByRole("button", { name: /^任务列表$/ }).click();
        await page.getByText(taskName, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
        addCheck(report, "真实数据对账: 外呼任务前端可见", "pass", taskName);
      } else {
        addCheck(report, "真实数据对账: 外呼任务 API 兜底", "fail", `HTTP ${createdByApi.status}: ${JSON.stringify(createdByApi.body).slice(0, 300)}`);
      }
    }
  }

  if (report.state.accessToken) {
    const tasks = await apiRequest(report, options, "/outbound/tasks");
    const created = Array.isArray(tasks.body) ? tasks.body.find((task) => task.name === taskName) : null;
    report.state.createdTaskId = created?.id || report.state.createdTaskId || "";
    addCheck(report, "真实数据对账: 外呼任务可由 API 查到", created ? "pass" : "fail", `taskId=${created?.id || "missing"}, status=${created?.status || "missing"}, targetCount=${created?.targetCount ?? "missing"}`);
    addCheck(report, "真实安全: 任务创建后未自动启动", created?.status === "待启动" ? "pass" : "fail", `status=${created?.status || "missing"}`);
  }
}

async function runLiveCallThroughUi(page, report, options, entry = null) {
  const phone = String(entry?.phone || options.phone || "").trim();
  const label = entry ? `#${entry.index + 1} ${entry.name}` : "单号";
  let liveResponse = null;
  page.on("response", async (response) => {
    if (/\/api\/outbound\/telephony\/test-call\b/.test(response.url())) {
      try {
        liveResponse = { status: response.status(), body: await response.json() };
      } catch {
        liveResponse = { status: response.status(), body: await response.text().catch(() => "") };
      }
    }
  });

  await page.getByRole("button", { name: /AI外呼系统/ }).click();
  await page.locator("section.outbound-tabs").getByRole("button", { name: /^实时监听$/ }).click();
  await page.getByPlaceholder("输入自己的手机号").fill(phone);
  if (options.callerId.trim()) {
    await page.getByPlaceholder("默认 AI获客").fill(options.callerId.trim());
  }
  await page.getByRole("button", { name: /单号试拨/ }).click();
  await page.waitForTimeout(9000);

  if (!liveResponse) {
    addCheck(report, "真实外呼: 单号试拨响应", "fail", "no /telephony/test-call response captured");
    return;
  }

  report.state.liveCall = liveResponse;
  if (entry) {
    report.state.batch.callResults.push({ index: entry.index, name: entry.name, phone: maskPhone(phone), response: liveResponse.body });
  }
  const body = liveResponse.body || {};
  addCheck(report, `真实外呼 ${label}: 请求被网关接收`, body.accepted ? "pass" : "fail", `status=${liveResponse.status}, actionId=${body.actionId || "missing"}, gatewayStatus=${body.gatewayStatus || "missing"}`);
  addCheck(report, `真实外呼 ${label}: 蜂窝侧确认`, body.cellularConfirmed ? "pass" : "fail", body.acceptanceNote || body.message || "missing acceptance note");
  addCheck(report, `真实外呼 ${label}: 媒体链路确认`, body.mediaLoopConfirmed ? "pass" : "fail", `verificationStage=${body.verificationStage || "missing"}`);
  addCheck(report, `真实外呼 ${label}: 真人语音确认`, body.humanSpeechConfirmed ? "pass" : "fail", `humanSpeechConfirmed=${body.humanSpeechConfirmed}, callScreeningDetected=${body.callScreeningDetected}`);
  addCheck(report, `真实外呼 ${label}: AI 首句播出确认`, body.aiSpeechConfirmed ? "pass" : "fail", `aiSpeechConfirmed=${body.aiSpeechConfirmed}`);
  addCheck(report, `真实外呼 ${label}: 对话验收通过`, body.conversationConfirmed || body.acceptanceReady ? "pass" : "fail", body.acceptanceNote || "conversation not confirmed");

  const liveEvents = await apiRequest(report, options, "/outbound/realtime/live-events?limit=120");
  report.api.afterLiveEvents = liveEvents;
  const eventTypes = Array.isArray(liveEvents.body?.events) ? liveEvents.body.events.map((event) => event.type) : [];
  for (const eventType of ["call_connected", "human_speech_confirmed", "tts_start", "call_disconnected"]) {
    addCheck(report, `真实事件: ${eventType}`, eventTypes.includes(eventType) ? "pass" : "warn", `events=${eventTypes.slice(0, 24).join(", ")}`);
  }
}

async function createLeadViaApi(report, options, entry) {
  const result = await apiRequest(report, options, "/leads", {
    method: "POST",
    body: {
      name: entry.name,
      platform: entry.platform || options.platform || "视频号",
      city: entry.city || options.city,
      category: entry.category || options.category,
      phone: entry.phone || null,
      contactName: entry.contactName || options.contactName || null,
      platformUrl: entry.platformUrl || null,
      source: entry.source || "V18受控真实批量验收",
      status: entry.phone ? "待外呼" : "待私信",
      remark: `V18.2 live batch allowlist index=${entry.index}`,
    },
  });
  if (!result.ok) {
    addCheck(report, `V18.2 真实线索: ${entry.name}`, "fail", `HTTP ${result.status}: ${JSON.stringify(result.body).slice(0, 300)}`);
    return null;
  }
  report.state.batch.createdLeadIds.push(result.body.id);
  addCheck(report, `V18.2 真实线索: ${entry.name}`, "pass", `leadId=${result.body.id}, phone=${maskPhone(entry.phone)}`);
  return result.body;
}

async function createDmTemplateViaApi(report, options, content) {
  if (!content.trim()) return null;
  const result = await apiRequest(report, options, "/direct-messages/templates", {
    method: "POST",
    body: {
      name: `V18.2真实批量私信-${Date.now().toString(36)}`,
      platform: "通用",
      content,
      isActive: true,
    },
  });
  if (!result.ok) {
    addCheck(report, "V18.2 批量私信: 模板创建", "fail", `HTTP ${result.status}: ${JSON.stringify(result.body).slice(0, 300)}`);
    return null;
  }
  addCheck(report, "V18.2 批量私信: 模板创建", "pass", `templateId=${result.body?.id || "created"}`);
  return result.body;
}

async function runBatchCallTask(report, options, leads) {
  if (leads.length === 0) return null;
  const taskName = `V18.2真实批量外呼-${Date.now().toString(36)}`;
  const created = await apiRequest(report, options, "/outbound/tasks", {
    method: "POST",
    body: {
      name: taskName,
      leadIds: leads.map((lead) => lead.id),
      concurrency: Math.max(1, Math.min(leads.length, 2)),
    },
  });
  if (!created.ok) {
    addCheck(report, "V18.2 批量外呼任务: 创建", "fail", `HTTP ${created.status}: ${JSON.stringify(created.body).slice(0, 300)}`);
    return null;
  }
  report.state.batch.callTaskId = created.body.id;
  addCheck(report, "V18.2 批量外呼任务: 创建", "pass", `taskId=${created.body.id}, targets=${created.body.targetCount}`);

  const started = await apiRequest(report, options, `/outbound/tasks/${encodeURIComponent(created.body.id)}/start`, {
    method: "POST",
    body: {},
  });
  report.state.batch.callTaskStart = started;
  addCheck(
    report,
    "V18.2 批量外呼任务: 启动真实批量",
    started.ok ? "pass" : "fail",
    started.ok ? `status=${started.body?.status || "unknown"}, completed=${started.body?.completedCount ?? "n/a"}` : `HTTP ${started.status}: ${JSON.stringify(started.body).slice(0, 300)}`,
  );

  const records = await apiRequest(report, options, "/outbound/records");
  report.api.afterBatchCallRecords = records;
  const matchingRecords = Array.isArray(records.body)
    ? records.body.filter((record) => leads.some((lead) => lead.id === record.leadId))
    : [];
  addCheck(report, "V18.2 批量外呼任务: 通话记录落库", matchingRecords.length > 0 ? "pass" : "warn", `records=${matchingRecords.length}/${leads.length}`);
  return created.body;
}

async function runBatchDmTask(report, options, leads, message) {
  if (leads.length === 0) return null;
  const template = await createDmTemplateViaApi(report, options, message);
  const created = await apiRequest(report, options, "/direct-messages/tasks", {
    method: "POST",
    body: {
      name: `V18.2真实批量私信-${Date.now().toString(36)}`,
      leadIds: leads.map((lead) => lead.id),
      templateId: template?.id || null,
    },
  });
  if (!created.ok) {
    addCheck(report, "V18.2 批量私信任务: 创建", "fail", `HTTP ${created.status}: ${JSON.stringify(created.body).slice(0, 300)}`);
    return null;
  }
  report.state.batch.dmTaskId = created.body.id;
  addCheck(report, "V18.2 批量私信任务: 创建", "pass", `taskId=${created.body.id}, targets=${created.body.targetCount}`);

  const started = await apiRequest(report, options, `/direct-messages/tasks/${encodeURIComponent(created.body.id)}/start`, {
    method: "POST",
    body: {},
  });
  report.state.batch.dmTaskStart = started;
  addCheck(
    report,
    "V18.2 批量私信任务: 启动真实发送",
    started.ok ? "pass" : "fail",
    started.ok ? `status=${started.body?.status || "unknown"}, completed=${started.body?.completedCount ?? "n/a"}` : `HTTP ${started.status}: ${JSON.stringify(started.body).slice(0, 300)}`,
  );

  const messages = await apiRequest(report, options, "/direct-messages/messages");
  report.api.afterBatchDmMessages = messages;
  const outgoing = Array.isArray(messages.body) ? messages.body.filter((messageRecord) => messageRecord.direction === "outbound") : [];
  addCheck(report, "V18.2 批量私信任务: 消息记录落库", outgoing.length > 0 ? "pass" : "warn", `outboundMessages=${outgoing.length}`);
  return created.body;
}

async function runLiveBatchFlow(page, report, options, batchPlan, artifactDir) {
  if (!options.confirmLiveBatch) {
    addCheck(report, "V18.2 受控批量: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-batch");
    return;
  }
  if (!options.confirmRealData || !options.confirmProductionWrite) {
    addCheck(report, "V18.2 受控批量: 写入被阻断", options.requireLive ? "fail" : "warn", "missing --confirm-real-data or --confirm-production-write");
    return;
  }
  if (batchPlan.issues.length > 0) {
    addCheck(report, "V18.2 受控批量: 白名单阻断", "fail", batchPlan.issues.join(" | "));
    return;
  }
  if (!report.state.accessToken) {
    addCheck(report, "V18.2 受控批量: 鉴权阻断", "fail", "no auth token visible after login");
    return;
  }

  const entries = [...batchPlan.calls, ...batchPlan.sends.filter((send) => !batchPlan.calls.some((call) => call.index === send.index))];
  const leadByIndex = new Map();
  for (const entry of entries) {
    const lead = await createLeadViaApi(report, options, entry);
    if (lead) leadByIndex.set(entry.index, lead);
  }
  await screenshot(page, report, artifactDir, "03-v18-batch-leads-created");

  if (batchPlan.calls.length > 0 && (!options.confirmLiveCall || !options.confirmProductionWrite)) {
    addCheck(report, "V18.2 批量外呼: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-call or --confirm-production-write");
  } else if (batchPlan.calls.length > 0) {
    if (["sequence", "both"].includes(options.batchCallMode)) {
      for (const entry of batchPlan.calls) {
        await runLiveCallThroughUi(page, report, options, entry);
        if (options.stopOnCritical && report.checks.some((check) => check.status === "fail" && check.name.includes(`#${entry.index + 1}`))) break;
        await page.waitForTimeout(options.batchIntervalMs);
      }
      await screenshot(page, report, artifactDir, "04-v18-batch-call-sequence");
    }
    if (["task", "both"].includes(options.batchCallMode)) {
      const callLeads = batchPlan.calls.map((entry) => leadByIndex.get(entry.index)).filter(Boolean);
      await runBatchCallTask(report, options, callLeads);
      await screenshot(page, report, artifactDir, "05-v18-batch-call-task");
    }
  }

  if (batchPlan.sends.length > 0 && (!options.confirmLiveDm || !options.confirmProductionWrite)) {
    addCheck(report, "V18.2 批量私信: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-send/--confirm-live-dm or --confirm-production-write");
  } else if (batchPlan.sends.length > 0) {
    const sendLeads = batchPlan.sends.map((entry) => leadByIndex.get(entry.index)).filter(Boolean);
    const message = batchPlan.sends.find((entry) => entry.dmMessage)?.dmMessage || selectedDmMessage(options);
    await runBatchDmTask(report, options, sendLeads, message);
    await screenshot(page, report, artifactDir, "06-v18-batch-dm-task");
  }
}

async function assessRealDmFlow(report, options) {
  const dmConfig = await apiRequest(report, options, "/direct-messages/config");
  report.api.liveDmConfig = dmConfig;
  const accounts = await apiRequest(report, options, "/direct-messages/accounts");
  report.api.liveDmAccounts = accounts;
  const selectedLead = report.state.createdLeadId;

  if (!selectedLead) {
    addCheck(report, "真实私信: 采集线索可私信", "fail", "missing collected lead id");
    return;
  }
  const leads = await apiRequest(report, options, "/leads");
  const lead = Array.isArray(leads.body) ? leads.body.find((item) => item.id === selectedLead) : null;
  const platform = lead?.platform || options.platform;
  addCheck(
    report,
    "真实私信: 采集线索平台可私信",
    DM_SUPPORTED_PLATFORMS.has(platform) ? "pass" : "fail",
    `leadPlatform=${platform || "missing"}; supported=${Array.from(DM_SUPPORTED_PLATFORMS).join("/")}`,
  );
  if (!DM_SUPPORTED_PLATFORMS.has(platform)) return;

  const usableAccounts = Array.isArray(accounts.body)
    ? accounts.body.filter((account) => account.platform === platform && account.status === "可用" && account.sessionStatus === "已登录")
    : [];
  addCheck(
    report,
    "真实私信: 匹配平台个人号",
    usableAccounts.length > 0 ? "pass" : "fail",
    usableAccounts.length > 0 ? usableAccounts.map((account) => account.accountName).join(", ") : `missing logged-in ${platform} personal account`,
  );
  addCheck(
    report,
    "真实私信: 浏览器真发开关",
    dmConfig.body?.gatewayMode === "browser" && dmConfig.body?.browserLiveSendEnabled ? "pass" : "fail",
    `gatewayMode=${dmConfig.body?.gatewayMode || "missing"}, browserLiveSendEnabled=${dmConfig.body?.browserLiveSendEnabled}`,
  );
  if (!options.confirmLiveDm) {
    addCheck(report, "真实私信: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-dm");
    return;
  }
  if (!options.confirmProductionWrite) {
    addCheck(report, "真实私信: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-production-write");
    return;
  }
  if (usableAccounts.length === 0 || dmConfig.body?.gatewayMode !== "browser" || !dmConfig.body?.browserLiveSendEnabled) return;

  const taskName = `V18真实私信-${lead.name}-${Date.now().toString(36)}`;
  const task = await apiRequest(report, options, "/direct-messages/tasks", {
    method: "POST",
    body: { name: taskName, leadIds: [lead.id], accountId: usableAccounts[0].id, templateId: null },
  });
  report.state.createdDmTaskId = task.body?.id || "";
  addCheck(report, "真实私信: 任务创建", task.ok ? "pass" : "fail", `status=${task.status}, taskId=${task.body?.id || "missing"}`);
  if (!task.ok || !task.body?.id) return;

  const started = await apiRequest(report, options, `/direct-messages/tasks/${task.body.id}/start`, { method: "POST", body: {} });
  addCheck(report, "真实私信: 真发送执行", started.ok ? "pass" : "fail", `status=${started.status}, taskStatus=${started.body?.status || "missing"}`);
  const conversations = await apiRequest(report, options, "/direct-messages/conversations");
  const createdConversation = Array.isArray(conversations.body)
    ? conversations.body.find((conversation) => conversation.taskId === task.body.id)
    : null;
  addCheck(
    report,
    "真实私信: 会话/消息证据",
    createdConversation ? "pass" : "fail",
    createdConversation
      ? `conversationId=${createdConversation.id}, status=${createdConversation.status}, platform=${createdConversation.platform}`
      : "missing conversation",
  );
}

async function assessRealCommentInterceptFlow(report, options) {
  const overview = await apiRequest(report, options, "/direct-messages/intercepts/overview");
  report.api.liveCommentOverview = overview;
  if (!options.commentSourceUrl.trim()) {
    addCheck(report, "真实评论截流: 来源 URL", options.requireLive ? "fail" : "warn", "missing --comment-source-url");
    return;
  }
  if (!options.confirmLiveComment || !options.confirmProductionWrite) {
    addCheck(report, "真实评论截流: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-comment or --confirm-production-write");
    return;
  }

  const source = await apiRequest(report, options, "/direct-messages/intercepts/sources", {
    method: "POST",
    body: {
      platform: options.commentPlatform,
      sourceType: "视频链接",
      name: `V18真实评论截流-${Date.now().toString(36)}`,
      keyword: selectedCollectionKeyword(options),
      videoUrl: options.commentSourceUrl.trim(),
      videoTitle: "",
      keywordRules: "合作,价格,报名,入驻,求资料,想了解,加我",
      autoReplyEnabled: false,
      humanConfirmRequired: true,
    },
  });
  report.state.commentSourceId = source.body?.id || "";
  addCheck(report, "真实评论截流: 来源创建", source.ok ? "pass" : "fail", `status=${source.status}, sourceId=${source.body?.id || "missing"}`);
  if (!source.ok || !source.body?.id) return;

  const synced = await apiRequest(report, options, `/direct-messages/intercepts/sources/${source.body.id}/sync`, {
    method: "POST",
    body: {},
  });
  addCheck(
    report,
    "真实评论截流: 平台同步",
    synced.ok && (synced.body?.imported || 0) > 0 ? "pass" : "fail",
    synced.body?.message || `HTTP ${synced.status}`,
  );
  if (!synced.ok) return;

  const comments = await apiRequest(report, options, `/direct-messages/intercepts/comments?sourceId=${encodeURIComponent(source.body.id)}`);
  const highIntent = Array.isArray(comments.body) ? comments.body.filter((comment) => ["A", "B"].includes(comment.intentLevel)) : [];
  addCheck(report, "真实评论截流: 高意向评论", highIntent.length > 0 ? "pass" : "fail", `highIntent=${highIntent.length}`);
  if (highIntent.length === 0) return;

  const converted = await apiRequest(report, options, "/direct-messages/intercepts/comments/convert", {
    method: "POST",
    body: {
      commentIds: highIntent.slice(0, 3).map((comment) => comment.id),
      city: options.city,
      category: options.category,
      status: "待私信",
    },
  });
  addCheck(
    report,
    "真实评论截流: 转线索",
    converted.ok && (converted.body?.leadIds || []).length > 0 ? "pass" : "fail",
    converted.body?.message || `HTTP ${converted.status}`,
  );
}

async function runBrowser(report, options, artifactDir, batchPlan) {
  let launchedDesktop = null;
  if (options.desktopApp) {
    launchedDesktop = await launchDesktopApp(options, report);
    options.cdp = launchedDesktop.cdpUrl;
  }

  const browser = options.cdp ? await chromium.connectOverCDP(options.cdp) : await launchBrowser(options.headed);
  const context = options.cdp
    ? browser.contexts()[0]
    : await browser.newContext({ viewport: { width: 1440, height: 1100 }, locale: "zh-CN", timezoneId: "Asia/Shanghai" });
  const page = options.cdp ? await firstUsefulPage(browser) : await context.newPage();

  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      const location = message.location();
      if (/\/api\/auth\/login\b/.test(location.url || "") && /401|Unauthorized/i.test(message.text())) return;
      report.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 1000), location });
    }
  });
  page.on("pageerror", (error) => report.browser.pageErrors.push({ message: error.message, stack: error.stack }));
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/favicon|__vite_ping/.test(url)) return;
    report.browser.failedRequests.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const method = request.method().toUpperCase();
    const url = request.url();
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      await route.continue();
      return;
    }
    const matched = mutationRules.find((rule) => rule.pattern.test(url));
    const allowRealData =
      options.confirmRealData &&
      options.confirmProductionWrite &&
      ["lead-create", "outbound-task-create", "collection-run"].includes(matched?.name || "");
    const allowLiveCall = options.confirmLiveCall && options.confirmProductionWrite && matched?.name === "live-test-call";
    const allowLiveDm = options.confirmLiveDm && options.confirmProductionWrite && matched?.name === "dm-send-or-login";
    const allowLiveComment = options.confirmLiveComment && options.confirmProductionWrite && matched?.name === "comment-intercept";
    const allowed = !matched || allowRealData || allowLiveCall || allowLiveDm || allowLiveComment;
    if (!allowed) {
      report.browser.blockedMutations.push({ method, url, rule: matched?.name || "unknown" });
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });

  let traceStarted = false;
  if (!options.noTrace && context.tracing) {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    traceStarted = true;
  }
  try {
    if (!options.cdp) {
      await page.goto(options.url, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    }
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await screenshot(page, report, artifactDir, "01-entry");
    const loggedIn = await loginThroughUi(page, report, options);
    if (!loggedIn) return;
    await screenshot(page, report, artifactDir, "02-after-login");

    if (options.planOnly) {
      addCheck(report, "V18 执行模式", "pass", "plan-only: real mutations intentionally skipped");
      return;
    }
    if (!options.confirmRealData || !options.confirmProductionWrite) {
      addCheck(report, "V18 真实流程: 写入被阻断", options.requireLive ? "fail" : "warn", "missing --confirm-real-data or --confirm-production-write");
      return;
    }

    if (options.liveBatch) {
      await runLiveBatchFlow(page, report, options, batchPlan, artifactDir);
      await screenshot(page, report, artifactDir, "07-v18-batch-final");
      return;
    }

    let selectedRecord = await runRealCollectionThroughUi(page, report, options);
    await screenshot(page, report, artifactDir, "03-real-collection-result");
    if (!selectedRecord?.leadId || !selectedRecord.phone) {
      for (const provider of ["public_web", "douyin", "meituan"].filter((item) => item !== options.collectionProvider)) {
        const fallbackRecord = await runRealCollectionViaApi(
          report,
          options,
          provider,
          `primary provider ${options.collectionProvider} did not produce a callable lead`,
        );
        await screenshot(page, report, artifactDir, `03-real-collection-fallback-${provider}`);
        if (fallbackRecord?.leadId && fallbackRecord.phone) {
          selectedRecord = fallbackRecord;
          break;
        }
      }
    }
    if (!selectedRecord?.leadId || !selectedRecord.phone) {
      addCheck(report, "V18 真实流程: 采集线索不足", "fail", "real collection did not produce a callable lead with phone");
      return;
    }
    await createRealOutboundTaskThroughUi(page, report, options);
    await screenshot(page, report, artifactDir, "04-real-task-created");

    if (!options.confirmLiveCall) {
      addCheck(report, "V18 真实外呼: 未执行", options.requireLive ? "fail" : "warn", "missing --confirm-live-call");
    } else {
      await runLiveCallThroughUi(page, report, options);
      await screenshot(page, report, artifactDir, "05-live-call-result");
    }
    await assessRealDmFlow(report, options);
    await assessRealCommentInterceptFlow(report, options);
    await screenshot(page, report, artifactDir, "06-live-business-matrix");
  } finally {
    if (traceStarted) {
      const tracePath = path.join(artifactDir, "trace.zip");
      await context.tracing.stop({ path: tracePath }).catch(() => {});
      report.artifacts.trace = tracePath;
    }
    if (!options.cdp) await context.close().catch(() => {});
    await browser.close().catch(() => {});
    if (launchedDesktop?.child?.pid) {
      try {
        process.kill(launchedDesktop.child.pid);
      } catch {
        // The app may have already exited.
      }
    }
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V18",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      url: options.url,
      api: options.api,
      mode: options.desktopApp ? "desktop-app" : options.cdp ? "cdp" : "browser",
      planOnly: options.planOnly,
      requireLive: options.requireLive,
      liveBatch: options.liveBatch,
      phone: maskPhone(options.phone),
      merchantName: options.merchantName || "",
      allowlist: options.allowlistPath || "",
      maxCalls: options.maxCalls,
      maxSends: options.maxSends,
      batchIntervalMs: options.batchIntervalMs,
      batchCallMode: options.batchCallMode,
      collectionProvider: options.collectionProvider,
      collectionKeyword: selectedCollectionKeyword(options),
      collectionTarget: options.collectionTarget,
      commentPlatform: options.commentPlatform,
      commentSourceUrl: options.commentSourceUrl || "",
      confirmations: {
        realData: options.confirmRealData,
        liveCall: options.confirmLiveCall,
        liveDm: options.confirmLiveDm,
        liveComment: options.confirmLiveComment,
        liveBatch: options.confirmLiveBatch,
        productionWrite: options.confirmProductionWrite,
      },
    },
    summary: null,
    checks: [],
    matrix: {
      realData: [],
      batch: {},
    },
    api: {},
    browser: {
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
      blockedMutations: [],
      desktopApp: null,
    },
    state: {
      accessToken: "",
      collectionTaskId: "",
      collectionTaskName: "",
      collectionRunId: "",
      collectedRecords: 0,
      collectedLeadId: "",
      createdLeadId: "",
      createdTaskId: "",
      createdTaskName: "",
      createdDmTaskId: "",
      commentSourceId: "",
      liveCall: null,
      batch: {
        createdLeadIds: [],
        callTaskId: "",
        dmTaskId: "",
        callResults: [],
        callTaskStart: null,
        dmTaskStart: null,
      },
    },
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      trace: null,
      screenshots: [],
    },
  };

  try {
    const batchPlan = await loadBatchAllowlist(report, options);
    ensureLocalClientAccount(report, options);
    addRealDataGate(report, options);
    addBatchGate(report, options, batchPlan);
    await collectReadiness(report, options);
    if (options.planOnly) {
      addCheck(report, "V18 执行模式", "pass", "plan-only: browser/live mutations skipped; readiness matrix only");
    } else {
      await runBrowser(report, options, artifactDir, batchPlan);
    }
  } catch (error) {
    addCheck(report, "V18 QA runner", "fail", error.stack || error.message);
  }

  summarize(report);
  await writeJson(report.artifacts.report, report, options);

  if (options.json) {
    console.log(JSON.stringify(redact(report, options), null, 2));
  } else {
    console.log(`V18 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}`);
    console.log(`Report: ${report.artifacts.report}`);
    if (report.artifacts.trace) console.log(`Trace: ${report.artifacts.trace}`);
    for (const check of report.checks) {
      const marker = check.status === "pass" ? "PASS" : check.status === "warn" ? "WARN" : "FAIL";
      console.log(`${marker} ${check.name}: ${redact(check.detail, options)}`);
    }
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
