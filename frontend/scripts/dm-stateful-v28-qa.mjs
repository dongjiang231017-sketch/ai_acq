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
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v28-dm-stateful-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

const denyMutationPatterns = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/sync-replies\b/,
  /\/api\/direct-messages\/accounts\/[^/]+\/(?:login-window|login-session)\b/,
  /\/api\/direct-messages\/intercepts\/.*(?:sync|browser-capture|browser-dm-actions|automation)/,
  /\/api\/collections\/tasks\/[^/]+\/run\b/,
  /\/api\/voice\/.*(?:preview|training-jobs)/,
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
    skipV27: false,
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
    } else if (arg === "--skip-v27") {
      options.skipV27 = true;
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
  console.log(`AI ACQ V28 platform DM stateful UI QA

Default: run V27, then run an isolated platform DM browser journey:
  npm run qa:v28 -- --repeat 2

Evaluate an existing V27 report and only run the V28 DM journey:
  npm run qa:v28 -- --from-report .playwright-cli/v27-collector-stateful-qa/<run>/report.json

Batch composition keeps live calls/sends gated and only checks safe coverage evidence:
  npm run qa:v28:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
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

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/.test(normalized);
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

function runV27(options, artifactDir) {
  const args = [
    "scripts/collector-stateful-v27-qa.mjs",
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
    maxBuffer: 160 * 1024 * 1024,
    timeout: 35 * 60 * 1000,
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
    stdoutTail: report ? "" : String(result.stdout || "").slice(-5000),
    stderrTail: String(result.stderr || "").slice(-5000),
  };
}

function makeCorrelation() {
  const random = Math.random().toString(16).slice(2, 18).padEnd(16, "0");
  const runId = `v28-dm-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V28`,
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
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(`${command} ${args.join(" ")} exited ${code}\n${stdout}\n${stderr}`));
      }
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
  report.dmJourney.checks.push({ name, status, detail, data });
}

function statusRank(status) {
  if (status === "fail") return 3;
  if (status === "warn") return 2;
  return 1;
}

function normalizeApiPath(url, apiBase) {
  const raw = String(url || "");
  const pathname = raw.startsWith(apiBase) ? raw.slice(apiBase.length) || "/" : raw;
  return pathname
    .replace(/\/direct-messages\/accounts\/[^/?#]+\/desktop-login-check\b/, "/direct-messages/accounts/:param/desktop-login-check")
    .replace(/\/direct-messages\/accounts\/[^/?#]+\/preflight\b/, "/direct-messages/accounts/:param/preflight")
    .replace(/\/direct-messages\/tasks\/[^/?#]+\/start\b/, "/direct-messages/tasks/:param/start");
}

function recordApiResponse(report, source, method, url, status, headers = {}) {
  const normalizedPath = normalizeApiPath(url, report.dmJourney.runtime.apiBase || "");
  report.dmJourney.evidence.apiTraffic.push({
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
      ...(report.dmJourney.state.accessToken ? { Authorization: `Bearer ${report.dmJourney.state.accessToken}` } : {}),
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
  report.dmJourney.artifacts.screenshots.push(file);
  return file;
}

async function fillPanelField(panel, label, value) {
  await panel.getByLabel(label, { exact: true }).fill(value);
}

async function runDmPlaywright(report, options, artifactDir, urls, credentials) {
  const browser = await launchBrowser(options.headed);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  });
  const page = await context.newPage();

  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      const location = message.location();
      if (/\/api\/auth\/login\b/.test(location.url || "") && /401|Unauthorized/i.test(message.text())) return;
      report.dmJourney.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 800), location: message.location() });
    }
  });
  page.on("pageerror", (error) => {
    report.dmJourney.browser.pageErrors.push({ message: error.message, stack: error.stack });
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/__vite_ping|favicon/.test(url)) return;
    report.dmJourney.browser.failedRequests.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
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
    const isDenied = isMutation && denyMutationPatterns.some((pattern) => pattern.test(url));
    const isExternalMutation = isMutation && !url.startsWith(urls.apiBase) && !url.startsWith(urls.frontend);
    if (isDenied || isExternalMutation) {
      report.dmJourney.browser.blockedMutations.push({ method, url, reason: isDenied ? "dangerous-workflow" : "external-mutation" });
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
    report.dmJourney.state.accessToken = authState?.accessToken || "";
    addCheck(report, "认证状态: token 已写入浏览器", report.dmJourney.state.accessToken ? "pass" : "fail", "localStorage auth token present");

    const beforeLeads = await apiRequest(report, urls.apiBase, "/leads");
    const beforeAccounts = await apiRequest(report, urls.apiBase, "/direct-messages/accounts");
    const beforeTemplates = await apiRequest(report, urls.apiBase, "/direct-messages/templates");
    const beforeTasks = await apiRequest(report, urls.apiBase, "/direct-messages/tasks");
    const beforeConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const beforeMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    report.dmJourney.state.before = {
      leads: Array.isArray(beforeLeads.body) ? beforeLeads.body.length : -1,
      dmAccounts: Array.isArray(beforeAccounts.body) ? beforeAccounts.body.length : -1,
      dmTemplates: Array.isArray(beforeTemplates.body) ? beforeTemplates.body.length : -1,
      dmTasks: Array.isArray(beforeTasks.body) ? beforeTasks.body.length : -1,
      dmConversations: Array.isArray(beforeConversations.body) ? beforeConversations.body.length : -1,
      dmMessages: Array.isArray(beforeMessages.body) ? beforeMessages.body.length : -1,
    };
    addCheck(
      report,
      "API 基线: 登录后可读 DM 账号、模板、任务、会话和消息",
      beforeLeads.ok && beforeAccounts.ok && beforeTemplates.ok && beforeTasks.ok && beforeConversations.ok && beforeMessages.ok ? "pass" : "fail",
      `leads=${report.dmJourney.state.before.leads}, accounts=${report.dmJourney.state.before.dmAccounts}, templates=${report.dmJourney.state.before.dmTemplates}, tasks=${report.dmJourney.state.before.dmTasks}, conversations=${report.dmJourney.state.before.dmConversations}, messages=${report.dmJourney.state.before.dmMessages}`,
    );

    const suffix = Date.now().toString(36);
    const leadName = `V28美团私信商家-${suffix}`;
    const accountName = `V28美团已登录号-${suffix}`;
    const templateName = `V28美团私信模板-${suffix}`;
    const taskName = `V28美团私信任务-${suffix}`;
    report.dmJourney.state.created = { leadName, accountName, templateName, taskName, platform: "美团" };

    await page.getByRole("button", { name: /商家线索库/ }).click();
    await page.getByText("新增商家线索", { exact: false }).waitFor({ state: "visible", timeout: 25000 });
    const leadPanel = page.locator("article.panel").filter({ hasText: "新增商家线索" }).first();
    await fillPanelField(leadPanel, "商家名称", leadName);
    await leadPanel.locator("select").first().selectOption("美团");
    await fillPanelField(leadPanel, "城市", "南昌");
    await fillPanelField(leadPanel, "品类", "本地餐饮");
    await fillPanelField(leadPanel, "联系人", "V28测试联系人");
    await fillPanelField(leadPanel, "电话", `TEST-V28-${suffix}`);
    await fillPanelField(leadPanel, "平台店铺 URL", `https://www.meituan.com/meishi/${suffix}`);
    await leadPanel.getByRole("button", { name: /保存线索/ }).click();
    await page.getByText(leadName, { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "03-meituan-lead-created");
    addCheck(report, "UI 状态流: 创建美团线索后列表出现", "pass", leadName);

    const afterLead = await apiRequest(report, urls.apiBase, "/leads");
    const createdLead = Array.isArray(afterLead.body) ? afterLead.body.find((lead) => lead.name === leadName) : null;
    report.dmJourney.state.created.leadId = createdLead?.id || "";
    addCheck(
      report,
      "API 对账: 美团线索写入隔离数据库",
      createdLead && createdLead.platform === "美团" && afterLead.body.length === report.dmJourney.state.before.leads + 1 ? "pass" : "fail",
      `leadId=${createdLead?.id || "missing"}, platform=${createdLead?.platform || "missing"}, count ${report.dmJourney.state.before.leads}->${Array.isArray(afterLead.body) ? afterLead.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "数据隔离: 美团线索归属当前用户",
      createdLead?.ownerUserId && createdLead?.createdByUserId ? "pass" : "fail",
      `owner=${createdLead?.ownerUserId || "missing"}, createdBy=${createdLead?.createdByUserId || "missing"}`,
    );

    await page.getByRole("button", { name: /平台私信系统/ }).click();
    await page.getByRole("heading", { name: /^平台私信系统$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("button", { name: /^账号管理$/ }).click();
    await page.getByRole("heading", { name: /^平台个人号管理$/ }).waitFor({ state: "visible", timeout: 15000 });
    const accountPanel = page.locator("article.panel").filter({ hasText: "平台个人号管理" }).first();
    await accountPanel.locator("select").first().selectOption("美团");
    await accountPanel.locator('[data-dm-account-name="true"]').fill(accountName);
    await accountPanel.locator("input").nth(1).fill("V28隔离登录证据账号");
    await accountPanel.locator('input[type="number"]').nth(0).fill("7");
    await accountPanel.locator('input[type="number"]').nth(1).fill("15");
    await accountPanel.getByRole("button", { name: /保存账号/ }).click();
    await page.getByText(accountName, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "04-dm-account-created");
    addCheck(report, "UI 状态流: 美团个人号创建后列表出现", "pass", accountName);

    const afterAccountCreate = await apiRequest(report, urls.apiBase, "/direct-messages/accounts");
    const createdAccount = Array.isArray(afterAccountCreate.body)
      ? afterAccountCreate.body.find((account) => account.accountName === accountName)
      : null;
    report.dmJourney.state.created.dmAccountId = createdAccount?.id || "";
    addCheck(
      report,
      "API 对账: 私信账号写入隔离数据库",
      createdAccount && afterAccountCreate.body.length === report.dmJourney.state.before.dmAccounts + 1 ? "pass" : "fail",
      `dmAccountId=${createdAccount?.id || "missing"}, status=${createdAccount?.status || "missing"}, session=${createdAccount?.sessionStatus || "missing"}`,
    );
    addCheck(
      report,
      "安全门控: 新私信账号不会自动伪造登录态",
      createdAccount?.status === "待登录" && createdAccount?.sessionStatus === "未登录" ? "pass" : "fail",
      `status=${createdAccount?.status || "missing"}, session=${createdAccount?.sessionStatus || "missing"}`,
    );

    const loginEvidence = await apiRequest(report, urls.apiBase, `/direct-messages/accounts/${encodeURIComponent(createdAccount?.id || "")}/desktop-login-check`, {
      method: "POST",
      body: {
        url: "https://passport.meituan.com/account/unitivelogin",
        title: "美团个人号隔离登录态",
        hasCookieEvidence: true,
        hasStorageEvidence: false,
        hasPageLoginSignal: true,
      },
    });
    report.dmJourney.state.created.loginCheckStatus = loginEvidence.body?.sessionStatus || "";
    addCheck(
      report,
      "本地登录态: desktop-login-check 将账号标记为已登录",
      loginEvidence.ok && loginEvidence.body?.status === "可用" && loginEvidence.body?.sessionStatus === "已登录" ? "pass" : "fail",
      `status=${loginEvidence.body?.status || "missing"}, session=${loginEvidence.body?.sessionStatus || "missing"}`,
    );

    await page.reload({ waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.getByRole("button", { name: /平台私信系统/ }).click();
    await page.getByRole("button", { name: /^账号管理$/ }).click();
    await page.getByText(accountName, { exact: false }).first().waitFor({ state: "visible", timeout: 20000 });
    await page.getByText("已登录", { exact: false }).first().waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "05-dm-account-logged-in");
    addCheck(report, "UI 状态流: 已登录账号出现在账号管理", "pass", accountName);

    await page.getByRole("button", { name: /^消息模板$/ }).click();
    await page.getByRole("heading", { name: /^私信模板表单$/ }).waitFor({ state: "visible", timeout: 15000 });
    const templatePanel = page.locator("article.panel").filter({ hasText: "私信模板表单" }).first();
    await templatePanel.locator("input").first().fill(templateName);
    await templatePanel.locator("select").first().selectOption("美团");
    await templatePanel.locator("textarea").first().fill("您好，我们正在做本地商家增长方案的隔离回放测试，本条只创建任务，不会真实发送。");
    await templatePanel.getByRole("button", { name: /保存模板/ }).click();
    await page.getByText(templateName, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "06-dm-template-created");
    addCheck(report, "UI 状态流: 私信模板创建后模板库出现", "pass", templateName);

    const afterTemplates = await apiRequest(report, urls.apiBase, "/direct-messages/templates");
    const createdTemplate = Array.isArray(afterTemplates.body) ? afterTemplates.body.find((template) => template.name === templateName) : null;
    report.dmJourney.state.created.dmTemplateId = createdTemplate?.id || "";
    addCheck(
      report,
      "API 对账: 私信模板写入隔离数据库",
      createdTemplate && createdTemplate.platform === "美团" && afterTemplates.body.length === report.dmJourney.state.before.dmTemplates + 1 ? "pass" : "fail",
      `dmTemplateId=${createdTemplate?.id || "missing"}, platform=${createdTemplate?.platform || "missing"}`,
    );

    await page.getByRole("button", { name: /^任务列表$/ }).click();
    await page.getByRole("heading", { name: /^创建平台私信任务$/ }).waitFor({ state: "visible", timeout: 15000 });
    const taskPanel = page.locator("article.panel").filter({ hasText: "创建平台私信任务" }).first();
    await taskPanel.locator("input").first().fill(taskName);
    await taskPanel.locator("select").first().selectOption("美团");
    await taskPanel.locator("select").nth(1).selectOption(createdTemplate?.id || { label: templateName });
    await taskPanel.getByRole("button", { name: /创建私信任务/ }).click();
    await page.getByText(taskName, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "07-dm-task-created");
    addCheck(report, "UI 状态流: 创建私信任务后队列出现", "pass", taskName);

    const afterTasks = await apiRequest(report, urls.apiBase, "/direct-messages/tasks");
    const afterConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const afterMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    const createdTask = Array.isArray(afterTasks.body) ? afterTasks.body.find((task) => task.name === taskName) : null;
    report.dmJourney.state.created.dmTaskId = createdTask?.id || "";
    addCheck(
      report,
      "API 对账: 私信任务写入隔离数据库",
      createdTask && afterTasks.body.length === report.dmJourney.state.before.dmTasks + 1 ? "pass" : "fail",
      `dmTaskId=${createdTask?.id || "missing"}, targetCount=${createdTask?.targetCount ?? "missing"}, template=${createdTask?.dmTemplateId || "missing"}`,
    );
    addCheck(
      report,
      "安全门控: 私信任务只创建不启动",
      createdTask?.status === "待启动" && createdTask?.startedAt == null ? "pass" : "fail",
      `status=${createdTask?.status || "missing"}, startedAt=${createdTask?.startedAt || "null"}`,
    );
    addCheck(
      report,
      "安全门控: 私信创建不产生会话或消息副作用",
      Array.isArray(afterConversations.body)
        && afterConversations.body.length === report.dmJourney.state.before.dmConversations
        && Array.isArray(afterMessages.body)
        && afterMessages.body.length === report.dmJourney.state.before.dmMessages
        ? "pass"
        : "fail",
      `conversations ${report.dmJourney.state.before.dmConversations}->${Array.isArray(afterConversations.body) ? afterConversations.body.length : "unknown"}, messages ${report.dmJourney.state.before.dmMessages}->${Array.isArray(afterMessages.body) ? afterMessages.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 危险发送/同步请求未触发",
      report.dmJourney.browser.blockedMutations.length === 0 ? "pass" : "warn",
      `blocked=${report.dmJourney.browser.blockedMutations.length}`,
      report.dmJourney.browser.blockedMutations,
    );

    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForTimeout(500);
    await screenshot(page, report, artifactDir, "08-mobile-dm-stateful-flow");
    addCheck(report, "移动端回放: DM 业务态可截图", "pass", "mobile screenshot captured after DM stateful flow");
  } finally {
    const tracePath = path.join(artifactDir, "trace.zip");
    await context.tracing.stop({ path: tracePath }).catch(() => {});
    report.dmJourney.artifacts.trace = tracePath;
    await context.close();
    await browser.close();
  }
}

async function runDmJourney(report, options, artifactDir) {
  const children = [];
  let backendStdout = null;
  let backendStderr = null;
  let frontendStdout = null;
  let frontendStderr = null;

  try {
    const apiPort = await findFreePort();
    const frontendPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v28.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v28_client_${Date.now().toString(36)}`,
      password: `V28-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v28-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v28-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V28隔离客户",
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
    report.dmJourney.runtime = {
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
    await fs.writeFile(report.dmJourney.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.dmJourney.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.dmJourney.artifacts.backendLog, "a");
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

    frontendStdout = await fs.open(report.dmJourney.artifacts.frontendLog, "w");
    frontendStderr = await fs.open(report.dmJourney.artifacts.frontendLog, "a");
    const frontend = startProcess("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort)], {
      cwd: FRONTEND_ROOT,
      env: { ...process.env, VITE_API_BASE_URL: apiBase },
      stdout: frontendStdout.createWriteStream(),
      stderr: frontendStderr.createWriteStream(),
    });
    children.push(frontend);
    await waitForUrl(frontendUrl, options.timeoutMs, "视频号团购商家AI获客客户端");
    addCheck(report, "沙箱前端: 临时 Vite 可用", "pass", frontendUrl);

    await runDmPlaywright(report, options, artifactDir, { frontend: frontendUrl, apiBase }, credentials);
  } catch (error) {
    addCheck(report, "V28 DM stateful QA runner", "fail", error.stack || error.message);
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
  return report.dmJourney.evidence.apiTraffic.some(
    (item) => item.method === method && item.normalizedPath === normalizedPath && item.status >= 200 && item.status < 400,
  );
}

function directMessagesApiTraffic(report) {
  return report.dmJourney.evidence.apiTraffic.filter((item) => /\/direct-messages\//.test(item.normalizedPath || ""));
}

async function evaluate(report) {
  const dmChecks = report.dmJourney.checks;
  const checkStatus = (pattern) => dmChecks.find((check) => pattern.test(`${check.name} ${check.detail}`))?.status || "missing";
  const traceExists = await pathExists(report.dmJourney.artifacts.trace);
  const screenshotExists = await pathExists(
    (report.dmJourney.artifacts.screenshots || []).find((item) => /dm-task-created/.test(item)) || "",
  );
  const dmTraffic = directMessagesApiTraffic(report);
  const echoedDmResponses = dmTraffic.filter((item) => item.correlationEchoed === true);
  const dangerousCovered = dmTraffic.some((item) =>
    item.normalizedPath === "/direct-messages/tasks/:param/start" || item.normalizedPath === "/direct-messages/sync-replies",
  );

  const dimensions = {
    v27RegressionPreserved: {
      status: report.v27?.summary?.canClaimCollectorStatefulUi || report.target.skipV27 ? "pass" : "fail",
      score: report.v27?.summary?.canClaimCollectorStatefulUi || report.target.skipV27 ? 10 : 0,
      detail: report.target.skipV27
        ? "skipped by option"
        : `collectorStateful=${Boolean(report.v27?.summary?.canClaimCollectorStatefulUi)}`,
    },
    sandboxAndAuth: {
      status: checkStatus(/沙箱后端/) === "pass" && checkStatus(/沙箱前端/) === "pass" && checkStatus(/客户账号可登录/) === "pass" ? "pass" : "fail",
      score: checkStatus(/沙箱后端/) === "pass" && checkStatus(/沙箱前端/) === "pass" && checkStatus(/客户账号可登录/) === "pass" ? 10 : 0,
      detail: `backend=${checkStatus(/沙箱后端/)}, frontend=${checkStatus(/沙箱前端/)}, login=${checkStatus(/客户账号可登录/)}`,
    },
    dmPrerequisitesStateful: {
      status:
        checkStatus(/美团线索写入/) === "pass" &&
        checkStatus(/私信账号写入/) === "pass" &&
        checkStatus(/desktop-login-check/) === "pass" &&
        checkStatus(/私信模板写入/) === "pass"
          ? "pass"
          : "fail",
      score:
        checkStatus(/美团线索写入/) === "pass" &&
        checkStatus(/私信账号写入/) === "pass" &&
        checkStatus(/desktop-login-check/) === "pass" &&
        checkStatus(/私信模板写入/) === "pass"
          ? 20
          : 0,
      detail: `lead=${checkStatus(/美团线索写入/)}, account=${checkStatus(/私信账号写入/)}, login=${checkStatus(/desktop-login-check/)}, template=${checkStatus(/私信模板写入/)}`,
    },
    dmTaskStatefulUi: {
      status: checkStatus(/创建私信任务后队列出现/) === "pass" && checkStatus(/私信任务写入/) === "pass" ? "pass" : "fail",
      score: checkStatus(/创建私信任务后队列出现/) === "pass" && checkStatus(/私信任务写入/) === "pass" ? 20 : 0,
      detail: `ui=${checkStatus(/创建私信任务后队列出现/)}, api=${checkStatus(/私信任务写入/)}`,
    },
    routeCoverage: {
      status:
        covered(report, "POST", "/direct-messages/accounts") &&
        covered(report, "POST", "/direct-messages/accounts/:param/desktop-login-check") &&
        covered(report, "POST", "/direct-messages/templates") &&
        covered(report, "POST", "/direct-messages/tasks")
          ? "pass"
          : "fail",
      score:
        covered(report, "POST", "/direct-messages/accounts") &&
        covered(report, "POST", "/direct-messages/accounts/:param/desktop-login-check") &&
        covered(report, "POST", "/direct-messages/templates") &&
        covered(report, "POST", "/direct-messages/tasks")
          ? 15
          : 0,
      detail: `account=${covered(report, "POST", "/direct-messages/accounts")}, loginCheck=${covered(report, "POST", "/direct-messages/accounts/:param/desktop-login-check")}, template=${covered(report, "POST", "/direct-messages/templates")}, task=${covered(report, "POST", "/direct-messages/tasks")}`,
    },
    noSendSideEffects: {
      status:
        checkStatus(/私信任务只创建不启动/) === "pass" &&
        checkStatus(/不产生会话或消息副作用/) === "pass" &&
        !dangerousCovered
          ? "pass"
          : "fail",
      score:
        checkStatus(/私信任务只创建不启动/) === "pass" &&
        checkStatus(/不产生会话或消息副作用/) === "pass" &&
        !dangerousCovered
          ? 15
          : 0,
      detail: `taskNotStarted=${checkStatus(/私信任务只创建不启动/)}, noConversationOrMessages=${checkStatus(/不产生会话或消息副作用/)}, dangerousCovered=${dangerousCovered}`,
    },
    traceAndCorrelation: {
      status: traceExists && screenshotExists && echoedDmResponses.length >= 4 ? "pass" : "warn",
      score: traceExists ? Math.min(10, 4 + Math.min(4, echoedDmResponses.length) + (screenshotExists ? 2 : 0)) : 0,
      detail: `trace=${traceExists}, screenshot=${screenshotExists}, dmEcho=${echoedDmResponses.length}/${dmTraffic.length}`,
    },
  };

  const score = Math.min(100, Object.values(dimensions).reduce((sum, item) => sum + item.score, 0));
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  const runtimeHardFailure =
    report.dmJourney.browser.pageErrors.length > 0 ||
    report.dmJourney.browser.failedRequests.filter((request) => !/blockedbyclient/i.test(request.failure || "")).length > 0;
  const status = hardFailure || runtimeHardFailure ? "fail" : "warn";

  return {
    status,
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure && !runtimeHardFailure,
      canClaimDmStatefulUi: !hardFailure && !runtimeHardFailure,
      canClaimCollectorStatefulUi: Boolean(report.v27?.summary?.canClaimCollectorStatefulUi),
      canClaimBroadBusinessCoverage: Boolean(report.v27?.summary?.canClaimBroadBusinessCoverage),
      canClaimRealBusinessReady: false,
      liveActionsStillGated: true,
      nextJourney: {
        module: "评论截流/意向客户池",
        suggestedGate: "promote safe comment-source capture or intent-customer workflow into a stateful UI replay; real platform sync/send remains V18-gated",
      },
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V28 Platform DM Stateful UI QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`DM stateful UI ready: ${report.summary.canClaimDmStatefulUi}`);
  lines.push(`Collector stateful preserved: ${report.summary.canClaimCollectorStatefulUi}`);
  lines.push(`Real business ready: ${report.summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## DM Evidence");
  lines.push(`- Platform: ${report.dmJourney.state.created.platform || ""}`);
  lines.push(`- Created lead: ${report.dmJourney.state.created.leadName || ""} (${report.dmJourney.state.created.leadId || ""})`);
  lines.push(`- Created account: ${report.dmJourney.state.created.accountName || ""} (${report.dmJourney.state.created.dmAccountId || ""})`);
  lines.push(`- Login check status: ${report.dmJourney.state.created.loginCheckStatus || ""}`);
  lines.push(`- Created template: ${report.dmJourney.state.created.templateName || ""} (${report.dmJourney.state.created.dmTemplateId || ""})`);
  lines.push(`- Created DM task: ${report.dmJourney.state.created.taskName || ""} (${report.dmJourney.state.created.dmTaskId || ""})`);
  lines.push(`- Live send remains gated: ${report.summary.liveActionsStillGated}`);
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V28 report: ${report.artifacts.report}`);
  lines.push(`- V28 markdown: ${report.artifacts.markdown}`);
  lines.push(`- V28 trace: ${report.dmJourney.artifacts.trace}`);
  lines.push(`- V28 screenshots: ${report.dmJourney.artifacts.screenshots.length}`);
  lines.push(`- V27 report: ${report.summary.v27Report}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const startedAt = Date.now();

  const report = {
    version: "V28",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV27: options.skipV27,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Playwright route interception and isolated browser contexts let the test exercise real UI while blocking live send/start endpoints.",
      "W3C traceparent and baggage-style context propagation make browser, API, and backend evidence comparable within a single run.",
      "State-machine-style QA should promote each high-risk product journey into a concrete create/read/safety replay instead of accepting generic navigation.",
    ],
    correlation: makeCorrelation(),
    v27Execution: null,
    v27: null,
    dmJourney: {
      checks: [],
      runtime: {},
      state: {
        accessToken: "",
        before: {},
        created: {},
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
        backendLog: path.join(artifactDir, "backend.log"),
        frontendLog: path.join(artifactDir, "frontend.log"),
        migrationLog: path.join(artifactDir, "migration.log"),
      },
    },
    durationMs: 0,
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "dm.md"),
    },
  };

  if (options.fromReport) {
    report.v27 = await readJson(options.fromReport);
    report.v27Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV27) {
    report.v27Execution = runV27(options, path.join(artifactDir, "v27"));
    report.v27 = report.v27Execution.report;
  } else {
    report.v27Execution = { command: "skip V27", exitCode: 0, durationMs: 0, parseError: null };
  }

  if (!report.v27) {
    report.v27 = { summary: { canClaimCollectorStatefulUi: false, canClaimBroadBusinessCoverage: false, canClaimRealBusinessReady: false } };
  }

  await runDmJourney(report, options, artifactDir);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = await evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimDmStatefulUi: report.evaluation.readinessDecision.canClaimDmStatefulUi,
    canClaimCollectorStatefulUi: report.evaluation.readinessDecision.canClaimCollectorStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v27Report: report.v27?.artifacts?.report || options.fromReport || "",
    trace: report.dmJourney.artifacts.trace,
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V28 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} dmStateful=${report.summary.canClaimDmStatefulUi} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`DM evidence: ${report.artifacts.markdown}`);
    console.log(`Trace: ${report.dmJourney.artifacts.trace}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
