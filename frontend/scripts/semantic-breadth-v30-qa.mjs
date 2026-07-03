#!/usr/bin/env node
import { chromium } from "playwright";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v30-semantic-breadth-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

const denyBrowserMutationPatterns = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/sync-replies\b/,
  /\/api\/direct-messages\/accounts\/[^/]+\/(?:login-window|login-session)\b/,
  /\/api\/direct-messages\/intercepts\/sources\/[^/]+\/(?:sync|browser-dm-actions)\b/,
  /\/api\/collections\/tasks\/[^/]+\/run\b/,
  /\/api\/voice\/.*(?:preview|training-jobs)/,
  /\/api\/reports\/exports\b/,
  /\/api\/settings\/items\/[^/]+\b/,
];

const semanticModules = [
  {
    key: "voice",
    nav: "声音档案",
    heading: /^声音档案$/,
    tabs: ["声音档案", "授权审核", "音色复刻", "使用记录"],
    requiredText: ["克隆档案", "声音库", "克隆服务", "使用记录"],
    routeHints: [
      ["GET", "/voice/overview"],
      ["GET", "/voice/provider/status"],
      ["GET", "/voice/system-voices"],
      ["GET", "/voice/profiles"],
      ["GET", "/voice/samples"],
      ["GET", "/voice/training-jobs"],
      ["GET", "/voice/clone-records"],
      ["GET", "/voice/usage-records"],
    ],
  },
  {
    key: "reports",
    nav: "数据报表",
    heading: /^数据报表$/,
    tabs: ["报表总览", "渠道分析", "销售绩效", "导出中心"],
    requiredText: ["商家线索", "电话/私信触达", "A/B 意向", "导出任务"],
    routeHints: [
      ["GET", "/reports/overview"],
      ["GET", "/reports/channels"],
      ["GET", "/reports/sales"],
      ["GET", "/reports/exports"],
    ],
  },
  {
    key: "settings",
    nav: "系统设置",
    heading: /^系统设置$/,
    tabs: ["设置总览", "电话线路", "平台账号", "合规保护"],
    requiredText: ["运营配置", "需确认", "电话线路", "平台账号"],
    routeHints: [
      ["GET", "/settings/overview"],
      ["GET", "/settings/items"],
      ["GET", "/outbound/telephony/config"],
    ],
  },
];

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    timeoutMs: 180000,
    fromReport: "",
    json: false,
    batch: false,
    skipV29: false,
    headed: false,
    keep: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 1000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--timeout-ms") options.timeoutMs = Math.max(10000, Number(next) || 180000);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--skip-v29") {
      options.skipV29 = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--keep") {
      options.keep = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      options.passThrough.push(arg);
      if (next && !next.startsWith("--")) {
        options.passThrough.push(next);
        index += 1;
      }
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V30 semantic breadth + ARIA snapshot QA

Default: run V29, then replay safe semantic coverage for voice, reports, and settings modules.
  npm run qa:v30 -- --repeat 2

Evaluate an existing V29 report and only run V30 semantic breadth:
  npm run qa:v30 -- --from-report .playwright-cli/v29-comment-intent-qa/<run>/report.json

Batch composition keeps live calls/sends/sync gated:
  npm run qa:v30:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
`);
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
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/.test(normalized);
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

function runV29(options, artifactDir) {
  const args = [
    "scripts/comment-intent-v29-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    artifactDir,
  ];
  if (options.batch) args.push("--batch");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 220 * 1024 * 1024,
    timeout: 55 * 60 * 1000,
  });

  let report = null;
  let parseError = null;
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }

  return {
    command: `${process.execPath} ${args.join(" ")}`,
    artifactDir,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: result.stdout?.slice(-5000) || "",
    stderrTail: result.stderr?.slice(-5000) || "",
  };
}

function makeCorrelation() {
  const random = Math.random().toString(16).slice(2, 18).padEnd(16, "0");
  const runId = `v30-semantic-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V30`,
  };
}

function correlationHeaders(correlation) {
  if (!correlation) return {};
  return {
    "X-AI-ACQ-QA-Correlation-Id": correlation.runId,
    "X-Request-ID": correlation.runId,
    traceparent: correlation.traceparent,
    baggage: correlation.baggage,
  };
}

async function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close(() => (port ? resolve(port) : reject(new Error("No free port assigned"))));
    });
    server.on("error", reject);
  });
}

async function waitForUrl(url, timeoutMs, expectText = "") {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (response.ok && (!expectText || text.includes(expectText))) return { status: response.status, text };
      lastError = new Error(`HTTP ${response.status}: ${text.slice(0, 160)}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown"}`);
}

async function runCommand(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(" ")} exited ${code}\n${stdout}\n${stderr}`));
    });
  });
}

async function backendPython() {
  const venvPython = path.join(BACKEND_ROOT, ".venv", "bin", "python");
  try {
    await fs.access(venvPython);
    return venvPython;
  } catch {
    return "python3";
  }
}

function startProcess(command, args, options) {
  return spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    detached: true,
    stdio: ["ignore", options.stdout, options.stderr],
  });
}

function stopProcess(child) {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    try {
      process.kill(child.pid, "SIGTERM");
    } catch {
      // Already stopped.
    }
  }
}

function addCheck(report, name, status, detail, data = undefined) {
  report.semanticBreadthJourney.checks.push({ name, status, detail, data });
}

function normalizeApiPath(url, apiBase) {
  const raw = String(url || "");
  return raw.startsWith(apiBase) ? raw.slice(apiBase.length) || "/" : raw;
}

function recordApiResponse(report, source, method, url, status, headers = {}) {
  const normalizedPath = normalizeApiPath(url, report.semanticBreadthJourney.runtime.apiBase || "");
  report.semanticBreadthJourney.evidence.apiTraffic.push({
    source,
    method,
    url,
    normalizedPath,
    status,
    echoedCorrelationId: headers["x-ai-acq-qa-correlation-id"] || headers["x-request-id"] || "",
    traceparent: headers.traceparent || "",
    correlationEchoed: report.correlation?.runId ? headers["x-ai-acq-qa-correlation-id"] === report.correlation.runId : null,
    traceparentEchoed: report.correlation?.traceparent ? headers.traceparent === report.correlation.traceparent : null,
  });
}

async function apiRequest(report, baseUrl, pathName, options = {}) {
  const method = options.method || "GET";
  const response = await fetch(`${baseUrl}${pathName}`, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(report.semanticBreadthJourney.state.accessToken ? { Authorization: `Bearer ${report.semanticBreadthJourney.state.accessToken}` } : {}),
      ...correlationHeaders(report.correlation),
      ...options.headers,
    },
    method,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const headers = Object.fromEntries(response.headers.entries());
  recordApiResponse(report, "node-api", method, `${baseUrl}${pathName}`, response.status, headers);
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
  const options = { headless: !headed, args: ["--disable-blink-features=AutomationControlled"] };
  try {
    return await chromium.launch({ ...options, channel: "chrome" });
  } catch {
    return chromium.launch(options);
  }
}

async function screenshot(page, report, artifactDir, name) {
  const file = path.join(artifactDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  report.semanticBreadthJourney.artifacts.screenshots.push(file);
  return file;
}

async function clickRefresh(page) {
  const refresh = page.locator('button[title="刷新数据"]').first();
  if (await refresh.count()) {
    await refresh.click();
    await page.waitForTimeout(800);
  }
}

async function ariaSnapshot(page) {
  const body = page.locator("body");
  if (typeof body.ariaSnapshot === "function") {
    return body.ariaSnapshot({ timeout: 5000 });
  }
  return page.evaluate(() => document.body.innerText.slice(0, 20000));
}

async function captureAria(page, report, artifactDir, moduleKey, label) {
  const ariaDir = path.join(artifactDir, "aria");
  await mkdirp(ariaDir);
  const file = path.join(ariaDir, `${moduleKey}-${label}.aria.yml`);
  const snapshot = await ariaSnapshot(page);
  await fs.writeFile(file, snapshot, "utf8");
  report.semanticBreadthJourney.artifacts.ariaSnapshots.push(file);
  return { file, snapshot };
}

async function walkSemanticModule(page, report, artifactDir, moduleConfig) {
  const moduleState = {
    key: moduleConfig.key,
    nav: moduleConfig.nav,
    tabs: {},
    screenshots: [],
    ariaSnapshots: [],
  };

  await page.getByRole("button", { name: new RegExp(moduleConfig.nav) }).click();
  await page.getByRole("heading", { name: moduleConfig.heading }).waitFor({ state: "visible", timeout: 20000 });
  await clickRefresh(page);
  for (const text of moduleConfig.requiredText) {
    await page.getByText(text, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
  }
  const overviewShot = await screenshot(page, report, artifactDir, `${moduleConfig.key}-00-overview`);
  moduleState.screenshots.push(overviewShot);

  for (let index = 0; index < moduleConfig.tabs.length; index += 1) {
    const tab = moduleConfig.tabs[index];
    await page.getByRole("button", { name: new RegExp(`^${tab}$`) }).click();
    await page.waitForTimeout(500);
    await page.getByRole("heading", { name: moduleConfig.heading }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByText(tab, { exact: false }).first().waitFor({ state: "visible", timeout: 10000 });
    const { file, snapshot } = await captureAria(page, report, artifactDir, moduleConfig.key, `${String(index + 1).padStart(2, "0")}-${tab}`);
    moduleState.ariaSnapshots.push(file);
    moduleState.tabs[tab] = {
      aria: file,
      containsNav: snapshot.includes(moduleConfig.nav),
      containsTab: snapshot.includes(tab),
      bytes: Buffer.byteLength(snapshot, "utf8"),
    };
  }

  report.semanticBreadthJourney.state.modules[moduleConfig.key] = moduleState;
  const allTabsCaptured = moduleConfig.tabs.every((tab) => moduleState.tabs[tab]?.containsTab);
  addCheck(
    report,
    `语义 UI: ${moduleConfig.nav} 模块 tab/ARIA 快照完整`,
    allTabsCaptured ? "pass" : "fail",
    `${moduleConfig.tabs.length} tabs, aria=${moduleState.ariaSnapshots.length}`,
    moduleState,
  );
}

async function runSemanticPlaywright(report, options, artifactDir, urls, credentials) {
  const browser = await launchBrowser(options.headed);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    extraHTTPHeaders: correlationHeaders(report.correlation),
  });
  const page = await context.newPage();

  page.on("console", (message) => {
    if (["error"].includes(message.type())) {
      report.semanticBreadthJourney.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 800), location: message.location() });
    }
  });
  page.on("pageerror", (error) => {
    report.semanticBreadthJourney.browser.pageErrors.push({ message: error.message, stack: error.stack });
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (!url.startsWith(urls.apiBase) && !url.startsWith(urls.frontend)) return;
    report.semanticBreadthJourney.browser.failedRequests.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!url.startsWith(urls.apiBase)) return;
    recordApiResponse(report, "browser", response.request().method(), url, response.status(), response.headers());
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const method = request.method().toUpperCase();
    const url = request.url();
    const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
    const isDenied = isMutation && denyBrowserMutationPatterns.some((pattern) => pattern.test(url));
    const isExternalMutation = isMutation && !url.startsWith(urls.apiBase) && !url.startsWith(urls.frontend);
    if (isDenied || isExternalMutation) {
      report.semanticBreadthJourney.browser.blockedMutations.push({ method, url, reason: isDenied ? "dangerous-workflow" : "external-mutation" });
      await route.abort("blockedbyclient");
      return;
    }
    if (url.startsWith(urls.apiBase)) {
      await route.continue({ headers: { ...request.headers(), ...correlationHeaders(report.correlation) } });
      return;
    }
    await route.continue();
  });

  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  try {
    await page.goto(urls.frontend, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.getByRole("heading", { name: /登录进入获客工作台/ }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "01-login-gate");
    addCheck(report, "认证入口: 登录页可见", "pass", "customer login gate rendered");

    await page.getByLabel("登录账号", { exact: true }).fill(credentials.username);
    await page.getByLabel("密码", { exact: true }).fill(credentials.password);
    await page.getByRole("button", { name: /^登录$/ }).click();
    await page.getByRole("heading", { name: /AI外呼系统/ }).waitFor({ state: "visible", timeout: 25000 });
    await screenshot(page, report, artifactDir, "02-after-login-dashboard");
    addCheck(report, "认证正例: 客户账号可登录", "pass", `logged in as ${credentials.username}`);

    const authState = await page.evaluate(() => {
      const raw = window.localStorage.getItem("ai_acq_client_auth");
      return raw ? JSON.parse(raw) : null;
    });
    report.semanticBreadthJourney.state.accessToken = authState?.accessToken || "";
    addCheck(report, "认证状态: token 已写入浏览器", report.semanticBreadthJourney.state.accessToken ? "pass" : "fail", "localStorage auth token present");

    const beforeConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const beforeMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    const beforeExports = await apiRequest(report, urls.apiBase, "/reports/exports");
    report.semanticBreadthJourney.state.before = {
      dmConversations: Array.isArray(beforeConversations.body) ? beforeConversations.body.length : -1,
      dmMessages: Array.isArray(beforeMessages.body) ? beforeMessages.body.length : -1,
      reportExports: Array.isArray(beforeExports.body) ? beforeExports.body.length : -1,
    };

    for (const moduleConfig of semanticModules) {
      await walkSemanticModule(page, report, artifactDir, moduleConfig);
    }

    const afterConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const afterMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    const afterExports = await apiRequest(report, urls.apiBase, "/reports/exports");
    const noSideEffects =
      Array.isArray(afterConversations.body)
      && afterConversations.body.length === report.semanticBreadthJourney.state.before.dmConversations
      && Array.isArray(afterMessages.body)
      && afterMessages.body.length === report.semanticBreadthJourney.state.before.dmMessages
      && Array.isArray(afterExports.body)
      && afterExports.body.length === report.semanticBreadthJourney.state.before.reportExports;
    addCheck(
      report,
      "安全门控: 语义广度回放不产生私信消息或报表导出副作用",
      noSideEffects ? "pass" : "fail",
      `conversations ${report.semanticBreadthJourney.state.before.dmConversations}->${Array.isArray(afterConversations.body) ? afterConversations.body.length : "unknown"}, messages ${report.semanticBreadthJourney.state.before.dmMessages}->${Array.isArray(afterMessages.body) ? afterMessages.body.length : "unknown"}, exports ${report.semanticBreadthJourney.state.before.reportExports}->${Array.isArray(afterExports.body) ? afterExports.body.length : "unknown"}`,
    );

    const dangerousCovered = report.semanticBreadthJourney.evidence.apiTraffic.some((item) =>
      item.normalizedPath.includes("/test-call")
      || item.normalizedPath.includes("/recover-line")
      || item.normalizedPath.includes("/sync-replies")
      || item.normalizedPath.includes("/browser-dm-actions")
      || item.normalizedPath.includes("/reports/exports") && item.method === "POST"
      || item.normalizedPath.includes("/settings/items/") && ["POST", "PUT", "PATCH", "DELETE"].includes(item.method),
    );
    addCheck(
      report,
      "安全门控: 真实外呼/发送/导出/设置写入未触发",
      !dangerousCovered && report.semanticBreadthJourney.browser.blockedMutations.length === 0 ? "pass" : "warn",
      `dangerousCovered=${dangerousCovered}, blocked=${report.semanticBreadthJourney.browser.blockedMutations.length}`,
      report.semanticBreadthJourney.browser.blockedMutations,
    );

    await page.setViewportSize({ width: 390, height: 900 });
    await page.getByRole("button", { name: /系统设置/ }).click();
    await page.waitForTimeout(500);
    await screenshot(page, report, artifactDir, "08-mobile-settings-semantic");
    addCheck(report, "移动端回放: 语义广度模块可截图", "pass", "mobile screenshot captured after V30 semantic flow");
  } finally {
    const tracePath = path.join(artifactDir, "trace.zip");
    await context.tracing.stop({ path: tracePath }).catch(() => {});
    report.semanticBreadthJourney.artifacts.trace = tracePath;
    await context.close();
    await browser.close();
  }
}

async function runSemanticJourney(report, options, artifactDir) {
  const children = [];
  let backendStdout = null;
  let backendStderr = null;
  let frontendStdout = null;
  let frontendStderr = null;

  try {
    const apiPort = await findFreePort();
    const frontendPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v30.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v30_client_${Date.now().toString(36)}`,
      password: `V30-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v30-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v30-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V30隔离客户",
      INITIAL_CLIENT_PHONE: "",
      INITIAL_CLIENT_EMAIL: "",
      ASTERISK_LIVE_CALL_ENABLED: "false",
      ASTERISK_BULK_CALL_ENABLED: "false",
      OUTBOUND_QUEUE_ENABLED: "false",
      DM_BROWSER_LIVE_SEND_ENABLED: "false",
      DM_QUEUE_ENABLED: "false",
      COMMENT_INTERCEPT_LIVE_SYNC_ENABLED: "false",
      COMMENT_INTERCEPT_ADAPTER_MODE: "disabled",
      REALTIME_CONVERSATION_MODE: "pipeline",
      VOICE_SAMPLE_STORAGE_ROOT: path.join(artifactDir, "voice-samples"),
    };
    const apiBase = `http://127.0.0.1:${apiPort}/api`;
    const frontendUrl = `http://127.0.0.1:${frontendPort}/`;
    report.semanticBreadthJourney.runtime = {
      apiPort,
      frontendPort,
      apiBase,
      frontendUrl,
      databasePath,
      databaseUrl,
      credentialsAlias: credentials.username,
    };

    const migration = await runCommand(python, ["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], {
      cwd: BACKEND_ROOT,
      env,
    });
    await fs.writeFile(report.semanticBreadthJourney.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.semanticBreadthJourney.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.semanticBreadthJourney.artifacts.backendLog, "a");
    const backend = startProcess(
      python,
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
      {
        cwd: BACKEND_ROOT,
        env,
        stdout: backendStdout.createWriteStream(),
        stderr: backendStderr.createWriteStream(),
      },
    );
    children.push(backend);
    await waitForUrl(`${apiBase}/health`, options.timeoutMs, "ok");
    addCheck(report, "沙箱后端: 临时 API 可用", "pass", apiBase);

    frontendStdout = await fs.open(report.semanticBreadthJourney.artifacts.frontendLog, "w");
    frontendStderr = await fs.open(report.semanticBreadthJourney.artifacts.frontendLog, "a");
    const frontend = startProcess("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort)], {
      cwd: FRONTEND_ROOT,
      env: { ...process.env, VITE_API_BASE_URL: apiBase },
      stdout: frontendStdout.createWriteStream(),
      stderr: frontendStderr.createWriteStream(),
    });
    children.push(frontend);
    await waitForUrl(frontendUrl, options.timeoutMs, "视频号团购商家AI获客客户端");
    addCheck(report, "沙箱前端: 临时 Vite 可用", "pass", frontendUrl);

    await runSemanticPlaywright(report, options, artifactDir, { frontend: frontendUrl, apiBase }, credentials);
  } catch (error) {
    addCheck(report, "V30 semantic breadth QA runner", "fail", error.stack || error.message);
  } finally {
    if (!options.keep) {
      for (const child of children.reverse()) stopProcess(child);
    }
    await backendStdout?.close().catch(() => {});
    await backendStderr?.close().catch(() => {});
    await frontendStdout?.close().catch(() => {});
    await frontendStderr?.close().catch(() => {});
  }
}

async function pathExists(file) {
  if (!file) return false;
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

function covered(report, method, normalizedPath) {
  return report.semanticBreadthJourney.evidence.apiTraffic.some(
    (item) => item.method === method && item.normalizedPath === normalizedPath && item.status >= 200 && item.status < 400,
  );
}

function checkStatus(report, pattern) {
  return report.semanticBreadthJourney.checks.find((check) => pattern.test(`${check.name} ${check.detail}`))?.status || "missing";
}

async function evaluate(report) {
  const traceExists = await pathExists(report.semanticBreadthJourney.artifacts.trace);
  const ariaCount = report.semanticBreadthJourney.artifacts.ariaSnapshots.length;
  const requiredRoutes = semanticModules.flatMap((item) => item.routeHints);
  const coveredRoutes = requiredRoutes.filter(([method, route]) => covered(report, method, route));
  const semanticTraffic = report.semanticBreadthJourney.evidence.apiTraffic.filter((item) =>
    /\/voice|\/reports|\/settings|\/outbound\/telephony/.test(item.normalizedPath || ""),
  );
  const echoedResponses = semanticTraffic.filter((item) => item.correlationEchoed === true);
  const moduleChecks = semanticModules.map((item) => checkStatus(report, new RegExp(`语义 UI: ${item.nav}`)));
  const dangerousCovered = report.semanticBreadthJourney.evidence.apiTraffic.some((item) =>
    item.normalizedPath.includes("/test-call")
    || item.normalizedPath.includes("/recover-line")
    || item.normalizedPath.includes("/sync-replies")
    || item.normalizedPath.includes("/browser-dm-actions")
    || (item.normalizedPath.includes("/reports/exports") && item.method === "POST")
    || (item.normalizedPath.includes("/settings/items/") && ["POST", "PUT", "PATCH", "DELETE"].includes(item.method)),
  );

  const dimensions = {
    v29RegressionPreserved: {
      status: report.v29?.summary?.canClaimCommentIntentStatefulUi || report.target.skipV29 ? "pass" : "fail",
      score: report.v29?.summary?.canClaimCommentIntentStatefulUi || report.target.skipV29 ? 10 : 0,
      detail: report.target.skipV29 ? "skipped by option" : `commentIntent=${Boolean(report.v29?.summary?.canClaimCommentIntentStatefulUi)}`,
    },
    sandboxAndAuth: {
      status:
        checkStatus(report, /沙箱后端/) === "pass" &&
        checkStatus(report, /沙箱前端/) === "pass" &&
        checkStatus(report, /客户账号可登录/) === "pass"
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /沙箱后端/) === "pass" &&
        checkStatus(report, /沙箱前端/) === "pass" &&
        checkStatus(report, /客户账号可登录/) === "pass"
          ? 10
          : 0,
      detail: `backend=${checkStatus(report, /沙箱后端/)}, frontend=${checkStatus(report, /沙箱前端/)}, login=${checkStatus(report, /客户账号可登录/)}`,
    },
    semanticModuleBreadth: {
      status: moduleChecks.every((status) => status === "pass") ? "pass" : "fail",
      score: moduleChecks.every((status) => status === "pass") ? 25 : 0,
      detail: semanticModules.map((item, index) => `${item.key}=${moduleChecks[index]}`).join(", "),
    },
    ariaSnapshots: {
      status: ariaCount >= 12 ? "pass" : "fail",
      score: ariaCount >= 12 ? 20 : Math.min(15, ariaCount),
      detail: `ariaSnapshots=${ariaCount}/12`,
    },
    routeCoverage: {
      status: coveredRoutes.length >= requiredRoutes.length ? "pass" : "fail",
      score: Math.round((coveredRoutes.length / Math.max(1, requiredRoutes.length)) * 15),
      detail: `covered=${coveredRoutes.length}/${requiredRoutes.length}`,
    },
    noDangerousSideEffects: {
      status:
        checkStatus(report, /不产生私信消息或报表导出副作用/) === "pass" &&
        checkStatus(report, /真实外呼\/发送\/导出\/设置写入未触发/) !== "fail" &&
        !dangerousCovered
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /不产生私信消息或报表导出副作用/) === "pass" &&
        checkStatus(report, /真实外呼\/发送\/导出\/设置写入未触发/) !== "fail" &&
        !dangerousCovered
          ? 10
          : 0,
      detail: `noSideEffects=${checkStatus(report, /不产生私信消息或报表导出副作用/)}, dangerousCovered=${dangerousCovered}, blocked=${report.semanticBreadthJourney.browser.blockedMutations.length}`,
    },
    traceAndCorrelation: {
      status: traceExists && echoedResponses.length >= requiredRoutes.length ? "pass" : "warn",
      score: traceExists ? Math.min(10, 4 + Math.min(4, echoedResponses.length) + (ariaCount >= 12 ? 2 : 0)) : 0,
      detail: `trace=${traceExists}, echo=${echoedResponses.length}/${semanticTraffic.length}, aria=${ariaCount}`,
    },
  };

  const score = Math.min(100, Object.values(dimensions).reduce((sum, item) => sum + item.score, 0));
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  const runtimeHardFailure =
    report.semanticBreadthJourney.browser.pageErrors.length > 0 ||
    report.semanticBreadthJourney.browser.failedRequests.filter((request) => !/blockedbyclient/i.test(request.failure || "")).length > 0;
  const status = hardFailure || runtimeHardFailure ? "fail" : "warn";

  return {
    status,
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure && !runtimeHardFailure,
      canClaimSemanticBreadthUi: !hardFailure && !runtimeHardFailure,
      canClaimCommentIntentStatefulUi: Boolean(report.v29?.summary?.canClaimCommentIntentStatefulUi),
      canClaimDmStatefulUi: Boolean(report.v29?.summary?.canClaimDmStatefulUi),
      canClaimBroadBusinessCoverage: false,
      canClaimRealBusinessReady: false,
      liveActionsStillGated: true,
      nextJourney: {
        module: "模型化路径生成/API Schema 状态测试",
        suggestedGate: "add model-generated UI path coverage over V17-V30 journeys and/or Schemathesis-style OpenAPI stateful/property gates",
      },
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  const summary = report.summary;
  lines.push("# V30 Semantic Breadth + ARIA Snapshot QA");
  lines.push("");
  lines.push(`Status: ${summary.status}`);
  lines.push(`Score: ${summary.score}/100`);
  lines.push(`Semantic breadth UI ready: ${summary.canClaimSemanticBreadthUi}`);
  lines.push(`Comment-intent preserved: ${summary.canClaimCommentIntentStatefulUi}`);
  lines.push(`Real business ready: ${summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, dimension] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${dimension.status} (${dimension.score}) - ${dimension.detail}`);
  }
  lines.push("");
  lines.push("## Module Evidence");
  for (const moduleConfig of semanticModules) {
    const moduleState = report.semanticBreadthJourney.state.modules[moduleConfig.key] || {};
    lines.push(`- ${moduleConfig.nav}: tabs=${Object.keys(moduleState.tabs || {}).length}, aria=${(moduleState.ariaSnapshots || []).length}, screenshots=${(moduleState.screenshots || []).length}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V30 report: ${report.artifacts.report}`);
  lines.push(`- V30 markdown: ${report.artifacts.markdown}`);
  lines.push(`- V30 trace: ${report.semanticBreadthJourney.artifacts.trace}`);
  lines.push(`- V30 ARIA snapshots: ${report.semanticBreadthJourney.artifacts.ariaSnapshots.length}`);
  lines.push(`- V30 screenshots: ${report.semanticBreadthJourney.artifacts.screenshots.length}`);
  lines.push(`- V29 report: ${report.summary.v29Report || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V30",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV29: options.skipV29,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Playwright ARIA snapshots provide structured accessibility-tree evidence that is more stable than screenshots for semantic UI regression.",
      "Playwright trace viewer and tracing APIs preserve action, DOM snapshot, screenshot, console, and network evidence for failed user-path debugging.",
      "Model-based and stateful testing guidance points V30 toward module/state coverage plus route invariants before broader path generation or API property testing.",
    ],
    correlation: makeCorrelation(),
    v29Execution: null,
    v29: null,
    semanticBreadthJourney: {
      checks: [],
      runtime: {},
      state: {
        accessToken: "",
        before: {},
        modules: {},
      },
      browser: {
        consoleErrors: [],
        pageErrors: [],
        failedRequests: [],
        blockedMutations: [],
      },
      evidence: {
        apiTraffic: [],
      },
      artifacts: {
        root: artifactDir,
        trace: "",
        screenshots: [],
        ariaSnapshots: [],
        backendLog: path.join(artifactDir, "backend.log"),
        frontendLog: path.join(artifactDir, "frontend.log"),
        migrationLog: path.join(artifactDir, "migration.log"),
      },
    },
    durationMs: 0,
  };

  const startedAt = Date.now();
  if (options.fromReport) {
    report.v29 = await readJson(options.fromReport);
    report.v29Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV29) {
    report.v29Execution = runV29(options, path.join(artifactDir, "v29"));
    report.v29 = report.v29Execution.report;
  } else {
    report.v29Execution = { command: "skip V29", exitCode: 0, durationMs: 0, parseError: null };
    report.v29 = {
      summary: {
        canClaimCommentIntentStatefulUi: false,
        canClaimDmStatefulUi: false,
        canClaimRealBusinessReady: false,
      },
    };
  }

  await runSemanticJourney(report, options, artifactDir);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = await evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimSemanticBreadthUi: report.evaluation.readinessDecision.canClaimSemanticBreadthUi,
    canClaimCommentIntentStatefulUi: report.evaluation.readinessDecision.canClaimCommentIntentStatefulUi,
    canClaimDmStatefulUi: report.evaluation.readinessDecision.canClaimDmStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v29Report: report.v29?.artifacts?.report || report.v29?.summary?.v29Report || options.fromReport || "",
    trace: report.semanticBreadthJourney.artifacts.trace,
  };
  report.artifacts = {
    root: artifactDir,
    report: path.join(artifactDir, "report.json"),
    markdown: path.join(artifactDir, "semantic-breadth.md"),
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V30 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} semanticBreadth=${report.summary.canClaimSemanticBreadthUi} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Semantic breadth evidence: ${report.artifacts.markdown}`);
    console.log(`Trace: ${report.semanticBreadthJourney.artifacts.trace}`);
  }

  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
