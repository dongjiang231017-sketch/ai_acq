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
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v29-comment-intent-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

const denyBrowserMutationPatterns = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/sync-replies\b/,
  /\/api\/direct-messages\/accounts\/[^/]+\/(?:login-window|login-session)\b/,
  /\/api\/direct-messages\/intercepts\/sources\/[^/]+\/sync\b/,
  /\/api\/direct-messages\/intercepts\/sources\/[^/]+\/browser-dm-actions\b/,
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
    skipV28: false,
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
    } else if (arg === "--skip-v28") {
      options.skipV28 = true;
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
  console.log(`AI ACQ V29 comment intercept + intent-pool stateful QA

Default: run V28, then replay a safe comment-intercept -> comment capture -> conversion -> intent-pool flow.
  npm run qa:v29 -- --repeat 2

Evaluate an existing V28 report and only run the V29 journey:
  npm run qa:v29 -- --from-report .playwright-cli/v28-dm-stateful-qa/<run>/report.json

Batch composition keeps live calls/sends/sync gated:
  npm run qa:v29:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1 --batch-call-mode both
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

function runV28(options, artifactDir) {
  const args = [
    "scripts/dm-stateful-v28-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--skip-v27",
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
    maxBuffer: 180 * 1024 * 1024,
    timeout: 45 * 60 * 1000,
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
  const runId = `v29-comment-${Date.now().toString(36)}-${random.slice(0, 6)}`;
  const traceId = `${Date.now().toString(16).padStart(16, "0")}${random}`.slice(0, 32).padEnd(32, "0");
  const spanId = random.slice(0, 16).padEnd(16, "0");
  return {
    runId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V29`,
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
  report.commentIntentJourney.checks.push({ name, status, detail, data });
}

function normalizeApiPath(url, apiBase) {
  const raw = String(url || "");
  const pathname = raw.startsWith(apiBase) ? raw.slice(apiBase.length) || "/" : raw;
  return pathname
    .replace(/\/direct-messages\/intercepts\/sources\/[^/?#]+\/browser-capture\b/, "/direct-messages/intercepts/sources/:param/browser-capture")
    .replace(/\/direct-messages\/intercepts\/sources\/[^/?#]+\/sync\b/, "/direct-messages/intercepts/sources/:param/sync")
    .replace(/\/direct-messages\/intercepts\/sources\/[^/?#]+\/browser-dm-actions\b/, "/direct-messages/intercepts/sources/:param/browser-dm-actions")
    .replace(/\/intent\/customers\/[^/?#]+\/events\b/, "/intent/customers/:param/events")
    .replace(/\/intent\/customers\/[^/?#]+/, "/intent/customers/:param");
}

function recordApiResponse(report, source, method, url, status, headers = {}) {
  const normalizedPath = normalizeApiPath(url, report.commentIntentJourney.runtime.apiBase || "");
  report.commentIntentJourney.evidence.apiTraffic.push({
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
      ...(report.commentIntentJourney.state.accessToken ? { Authorization: `Bearer ${report.commentIntentJourney.state.accessToken}` } : {}),
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
  report.commentIntentJourney.artifacts.screenshots.push(file);
  return file;
}

function highIntentComments(socialComments) {
  return Array.isArray(socialComments)
    ? socialComments.filter((comment) => ["A", "B"].includes(comment.intentLevel) && comment.status !== "已转线索")
    : [];
}

async function clickRefresh(page) {
  const refresh = page.locator('button[title="刷新数据"]').first();
  if (await refresh.count()) {
    await refresh.click();
    await page.waitForTimeout(800);
  }
}

async function waitForApiState(label, fn, timeoutMs = 20000, intervalMs = 500) {
  const started = Date.now();
  let lastState = null;
  while (Date.now() - started < timeoutMs) {
    lastState = await fn();
    if (lastState?.ready) return lastState;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  const detail = lastState ? JSON.stringify(redact(lastState)).slice(0, 1200) : "no state observed";
  throw new Error(`${label} did not become ready within ${timeoutMs}ms: ${detail}`);
}

async function runCommentIntentPlaywright(report, options, artifactDir, urls, credentials) {
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
      report.commentIntentJourney.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 800), location });
    }
  });
  page.on("pageerror", (error) => {
    report.commentIntentJourney.browser.pageErrors.push({ message: error.message, stack: error.stack });
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/__vite_ping|favicon/.test(url)) return;
    report.commentIntentJourney.browser.failedRequests.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
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
      report.commentIntentJourney.browser.blockedMutations.push({ method, url, reason: isDenied ? "dangerous-workflow" : "external-mutation" });
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
    report.commentIntentJourney.state.accessToken = authState?.accessToken || "";
    addCheck(report, "认证状态: token 已写入浏览器", report.commentIntentJourney.state.accessToken ? "pass" : "fail", "localStorage auth token present");

    const beforeSources = await apiRequest(report, urls.apiBase, "/direct-messages/intercepts/sources");
    const beforeComments = await apiRequest(report, urls.apiBase, "/direct-messages/intercepts/comments");
    const beforeLeads = await apiRequest(report, urls.apiBase, "/leads");
    const beforeIntentCustomers = await apiRequest(report, urls.apiBase, "/intent/customers");
    const beforeWorkOrders = await apiRequest(report, urls.apiBase, "/intent/work-orders");
    const beforeConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const beforeMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    report.commentIntentJourney.state.before = {
      sources: Array.isArray(beforeSources.body) ? beforeSources.body.length : -1,
      comments: Array.isArray(beforeComments.body) ? beforeComments.body.length : -1,
      leads: Array.isArray(beforeLeads.body) ? beforeLeads.body.length : -1,
      intentCustomers: Array.isArray(beforeIntentCustomers.body) ? beforeIntentCustomers.body.length : -1,
      workOrders: Array.isArray(beforeWorkOrders.body) ? beforeWorkOrders.body.length : -1,
      dmConversations: Array.isArray(beforeConversations.body) ? beforeConversations.body.length : -1,
      dmMessages: Array.isArray(beforeMessages.body) ? beforeMessages.body.length : -1,
    };
    addCheck(
      report,
      "API 基线: 评论截流、线索、意向客户、工单可读",
      beforeSources.ok && beforeComments.ok && beforeLeads.ok && beforeIntentCustomers.ok && beforeWorkOrders.ok ? "pass" : "fail",
      `sources=${report.commentIntentJourney.state.before.sources}, comments=${report.commentIntentJourney.state.before.comments}, leads=${report.commentIntentJourney.state.before.leads}, intent=${report.commentIntentJourney.state.before.intentCustomers}, workOrders=${report.commentIntentJourney.state.before.workOrders}`,
    );

    const suffix = Date.now().toString(36);
    const sourceName = `V29抖音评论截流-${suffix}`;
    const authorA = `V29高意向作者-${suffix}`;
    const authorC = `V29观察作者-${suffix}`;
    const videoUrl = `https://www.douyin.com/video/v29-${suffix}`;
    report.commentIntentJourney.state.created = { sourceName, authorA, authorC, platform: "抖音", videoUrl };

    const createdSourceResponse = await apiRequest(report, urls.apiBase, "/direct-messages/intercepts/sources", {
      method: "POST",
      body: {
        platform: "抖音",
        sourceType: "视频链接",
        name: sourceName,
        keyword: "南昌 团购 入驻",
        videoUrl,
        videoTitle: `V29评论截流测试视频-${suffix}`,
        ownerAccountId: null,
        syncFrequencyMinutes: 120,
        keywordRules: "合作,价格,报名,入驻,求资料,想了解,加我,怎么做",
        autoReplyEnabled: false,
        humanConfirmRequired: true,
      },
    });
    const createdSource = createdSourceResponse.body || {};
    report.commentIntentJourney.state.created.sourceId = createdSource.id || "";
    addCheck(
      report,
      "API 状态流: 创建评论截流来源",
      createdSourceResponse.ok && createdSource.name === sourceName ? "pass" : "fail",
      `sourceId=${createdSource.id || "missing"}, platform=${createdSource.platform || "missing"}`,
    );

    await page.getByRole("button", { name: /平台私信系统/ }).click();
    await page.getByRole("heading", { name: /^平台私信系统$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("button", { name: /^评论截流$/ }).click();
    await clickRefresh(page);
    await page.getByText(sourceName, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "03-comment-source-visible");
    addCheck(report, "UI 状态流: 评论截流来源在页面可见", "pass", sourceName);

    const captureResponse = await apiRequest(
      report,
      urls.apiBase,
      `/direct-messages/intercepts/sources/${encodeURIComponent(createdSource.id)}/browser-capture`,
      {
        method: "POST",
        body: {
          platform: "抖音",
          pageUrl: videoUrl,
          pageTitle: `V29评论截流测试视频-${suffix}`,
          comments: [
            {
              externalCommentId: `v29-a-${suffix}`,
              authorName: authorA,
              authorProfileUrl: `https://www.douyin.com/user/v29-a-${suffix}`,
              content: "想了解合作价格，怎么报名入驻？可以加我沟通本地团购获客方案。",
              videoUrl,
              city: "南昌",
              category: "本地生活",
              likeCount: 18,
              replyCount: 2,
              rawPayload: { qa: "v29", intent: "high" },
            },
            {
              externalCommentId: `v29-c-${suffix}`,
              authorName: authorC,
              authorProfileUrl: `https://www.douyin.com/user/v29-c-${suffix}`,
              content: "路过看看，内容挺有意思。",
              videoUrl,
              city: "南昌",
              category: "本地生活",
              likeCount: 1,
              replyCount: 0,
              rawPayload: { qa: "v29", intent: "low" },
            },
          ],
        },
      },
    );
    addCheck(
      report,
      "API 状态流: browser-capture 导入当前页评论",
      captureResponse.ok && captureResponse.body?.imported === 2 ? "pass" : "fail",
      `imported=${captureResponse.body?.imported ?? "missing"}, skipped=${captureResponse.body?.skipped ?? "missing"}, total=${captureResponse.body?.totalComments ?? "missing"}`,
    );

    await clickRefresh(page);
    await page.getByText(authorA, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
    await page.getByText(authorC, { exact: false }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "04-comments-visible");
    addCheck(report, "UI 状态流: 浏览器采集评论在评论线索池可见", "pass", `${authorA}, ${authorC}`);

    const commentsAfterCapture = await apiRequest(report, urls.apiBase, `/direct-messages/intercepts/comments?sourceId=${encodeURIComponent(createdSource.id)}`);
    const capturedComments = Array.isArray(commentsAfterCapture.body) ? commentsAfterCapture.body : [];
    const pendingHigh = highIntentComments(capturedComments);
    report.commentIntentJourney.state.created.commentIds = capturedComments.map((comment) => comment.id);
    report.commentIntentJourney.state.created.highIntentCommentIds = pendingHigh.map((comment) => comment.id);
    addCheck(
      report,
      "状态模型: 高意向评论被规则识别为 A/B",
      pendingHigh.length >= 1 && pendingHigh.some((comment) => comment.authorName === authorA) ? "pass" : "fail",
      `highIntent=${pendingHigh.map((comment) => `${comment.authorName}:${comment.intentLevel}/${comment.intentScore}`).join(", ")}`,
    );

    await page.getByRole("button", { name: /选择高意向/ }).click();
    const convertResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/direct-messages/intercepts/comments/convert") &&
        response.request().method() === "POST",
      { timeout: 20000 },
    );
    await page.getByRole("button", { name: /^转入线索库$/ }).click();
    const convertResponse = await convertResponsePromise;
    await page
      .locator(".form-result")
      .filter({ hasText: /新增|复用|跳过/ })
      .first()
      .waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "05-comments-converted");
    addCheck(
      report,
      "UI 状态流: 页面按钮将高意向评论转入线索库",
      convertResponse.ok() ? "pass" : "fail",
      `clicked select-high-intent and convert, apiStatus=${convertResponse.status()}`,
    );

    const conversionState = await waitForApiState("comment conversion API state", async () => {
      const commentsAfterConvert = await apiRequest(report, urls.apiBase, `/direct-messages/intercepts/comments?sourceId=${encodeURIComponent(createdSource.id)}`);
      const leadsAfterConvert = await apiRequest(report, urls.apiBase, "/leads");
      const intentAfterConvert = await apiRequest(report, urls.apiBase, "/intent/customers");
      const workOrdersAfterConvert = await apiRequest(report, urls.apiBase, "/intent/work-orders");
      const convertedComments = Array.isArray(commentsAfterConvert.body)
        ? commentsAfterConvert.body.filter((comment) => comment.status === "已转线索")
        : [];
      const convertedLead = Array.isArray(leadsAfterConvert.body)
        ? leadsAfterConvert.body.find((lead) => lead.name === authorA && lead.source === "评论截流")
        : null;
      const intentCustomer = Array.isArray(intentAfterConvert.body)
        ? intentAfterConvert.body.find((customer) => customer.merchantName === authorA)
        : null;
      const workOrders = Array.isArray(workOrdersAfterConvert.body) ? workOrdersAfterConvert.body : [];
      return {
        ready: Boolean(convertedComments.some((comment) => comment.authorName === authorA) && convertedLead && intentCustomer),
        commentsAfterConvert,
        leadsAfterConvert,
        intentAfterConvert,
        workOrdersAfterConvert,
        convertedComments,
        convertedLead,
        intentCustomer,
        workOrders,
      };
    });
    const { commentsAfterConvert, leadsAfterConvert, intentAfterConvert, workOrdersAfterConvert, convertedComments, convertedLead, intentCustomer } = conversionState;
    report.commentIntentJourney.state.created.convertedCommentIds = convertedComments.map((comment) => comment.id);
    report.commentIntentJourney.state.created.leadId = convertedLead?.id || "";
    report.commentIntentJourney.state.created.intentCustomerId = intentCustomer?.id || "";
    report.commentIntentJourney.state.created.workOrderIds = Array.isArray(workOrdersAfterConvert.body)
      ? workOrdersAfterConvert.body.filter((order) => order.customerId === intentCustomer?.id).map((order) => order.id)
      : [];

    addCheck(
      report,
      "API 对账: 评论状态变为已转线索",
      convertedComments.some((comment) => comment.authorName === authorA) ? "pass" : "fail",
      `converted=${convertedComments.map((comment) => comment.authorName).join(", ")}`,
    );
    addCheck(
      report,
      "API 对账: 评论截流线索写入隔离数据库",
      convertedLead && leadsAfterConvert.body.length > report.commentIntentJourney.state.before.leads ? "pass" : "fail",
      `leadId=${convertedLead?.id || "missing"}, source=${convertedLead?.source || "missing"}, count ${report.commentIntentJourney.state.before.leads}->${Array.isArray(leadsAfterConvert.body) ? leadsAfterConvert.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "API 对账: 意向客户池从评论线索同步客户",
      intentCustomer && intentCustomer.intentLevel && intentCustomer.intentScore >= 70 ? "pass" : "fail",
      `intentCustomerId=${intentCustomer?.id || "missing"}, level=${intentCustomer?.intentLevel || "missing"}, score=${intentCustomer?.intentScore ?? "missing"}`,
    );
    addCheck(
      report,
      "API 对账: 高意向客户生成跟进工单",
      report.commentIntentJourney.state.created.workOrderIds.length >= 1 ? "pass" : "warn",
      `workOrders=${report.commentIntentJourney.state.created.workOrderIds.join(", ") || "none"}`,
    );

    await page.getByRole("button", { name: /意向客户池/ }).click();
    await page.getByRole("heading", { name: /^意向客户池$/ }).waitFor({ state: "visible", timeout: 15000 });
    await clickRefresh(page);
    await page.getByText(authorA, { exact: false }).first().waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "06-intent-customer-visible");
    addCheck(report, "UI 状态流: 意向客户池显示评论转入客户", "pass", authorA);

    await page.getByRole("button", { name: /^跟进工单$/ }).click();
    await page.getByText(authorA, { exact: false }).first().waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "07-work-order-visible");
    addCheck(report, "UI 状态流: 跟进工单显示评论转入客户", "pass", authorA);

    const afterConversations = await apiRequest(report, urls.apiBase, "/direct-messages/conversations");
    const afterMessages = await apiRequest(report, urls.apiBase, "/direct-messages/messages");
    const noDmSideEffects =
      Array.isArray(afterConversations.body)
      && afterConversations.body.length === report.commentIntentJourney.state.before.dmConversations
      && Array.isArray(afterMessages.body)
      && afterMessages.body.length === report.commentIntentJourney.state.before.dmMessages;
    addCheck(
      report,
      "安全门控: 评论截流转线索不产生私信会话或消息",
      noDmSideEffects ? "pass" : "fail",
      `conversations ${report.commentIntentJourney.state.before.dmConversations}->${Array.isArray(afterConversations.body) ? afterConversations.body.length : "unknown"}, messages ${report.commentIntentJourney.state.before.dmMessages}->${Array.isArray(afterMessages.body) ? afterMessages.body.length : "unknown"}`,
    );
    const dangerousCovered = report.commentIntentJourney.evidence.apiTraffic.some((item) =>
      item.normalizedPath === "/direct-messages/intercepts/sources/:param/sync"
      || item.normalizedPath === "/direct-messages/intercepts/sources/:param/browser-dm-actions"
      || item.normalizedPath === "/direct-messages/tasks/:param/start"
      || item.normalizedPath === "/direct-messages/sync-replies",
    );
    addCheck(
      report,
      "安全门控: 真实平台同步/自动私信发送未触发",
      !dangerousCovered && report.commentIntentJourney.browser.blockedMutations.length === 0 ? "pass" : "warn",
      `dangerousCovered=${dangerousCovered}, blocked=${report.commentIntentJourney.browser.blockedMutations.length}`,
      report.commentIntentJourney.browser.blockedMutations,
    );

    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForTimeout(500);
    await screenshot(page, report, artifactDir, "08-mobile-comment-intent-flow");
    addCheck(report, "移动端回放: 评论截流到意向客户池可截图", "pass", "mobile screenshot captured after V29 flow");
  } finally {
    const tracePath = path.join(artifactDir, "trace.zip");
    await context.tracing.stop({ path: tracePath }).catch(() => {});
    report.commentIntentJourney.artifacts.trace = tracePath;
    await context.close();
    await browser.close();
  }
}

async function runCommentIntentJourney(report, options, artifactDir) {
  const children = [];
  let backendStdout = null;
  let backendStderr = null;
  let frontendStdout = null;
  let frontendStderr = null;

  try {
    const apiPort = await findFreePort();
    const frontendPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v29.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v29_client_${Date.now().toString(36)}`,
      password: `V29-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v29-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v29-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V29隔离客户",
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
    report.commentIntentJourney.runtime = {
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
    await fs.writeFile(report.commentIntentJourney.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.commentIntentJourney.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.commentIntentJourney.artifacts.backendLog, "a");
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

    frontendStdout = await fs.open(report.commentIntentJourney.artifacts.frontendLog, "w");
    frontendStderr = await fs.open(report.commentIntentJourney.artifacts.frontendLog, "a");
    const frontend = startProcess("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort)], {
      cwd: FRONTEND_ROOT,
      env: { ...process.env, VITE_API_BASE_URL: apiBase },
      stdout: frontendStdout.createWriteStream(),
      stderr: frontendStderr.createWriteStream(),
    });
    children.push(frontend);
    await waitForUrl(frontendUrl, options.timeoutMs, "视频号团购商家AI获客客户端");
    addCheck(report, "沙箱前端: 临时 Vite 可用", "pass", frontendUrl);

    await runCommentIntentPlaywright(report, options, artifactDir, { frontend: frontendUrl, apiBase }, credentials);
  } catch (error) {
    addCheck(report, "V29 comment-intent QA runner", "fail", error.stack || error.message);
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
  return report.commentIntentJourney.evidence.apiTraffic.some(
    (item) => item.method === method && item.normalizedPath === normalizedPath && item.status >= 200 && item.status < 400,
  );
}

function checkStatus(report, pattern) {
  return report.commentIntentJourney.checks.find((check) => pattern.test(`${check.name} ${check.detail}`))?.status || "missing";
}

async function evaluate(report) {
  const traceExists = await pathExists(report.commentIntentJourney.artifacts.trace);
  const intentScreenshotExists = await pathExists(
    (report.commentIntentJourney.artifacts.screenshots || []).find((item) => /intent-customer-visible/.test(item)) || "",
  );
  const commentTraffic = report.commentIntentJourney.evidence.apiTraffic.filter((item) =>
    /\/direct-messages\/intercepts|\/intent|\/leads/.test(item.normalizedPath || ""),
  );
  const echoedResponses = commentTraffic.filter((item) => item.correlationEchoed === true);
  const dangerousCovered = report.commentIntentJourney.evidence.apiTraffic.some((item) =>
    item.normalizedPath === "/direct-messages/intercepts/sources/:param/sync"
    || item.normalizedPath === "/direct-messages/intercepts/sources/:param/browser-dm-actions"
    || item.normalizedPath === "/direct-messages/tasks/:param/start"
    || item.normalizedPath === "/direct-messages/sync-replies",
  );

  const dimensions = {
    v28RegressionPreserved: {
      status: report.v28?.summary?.canClaimDmStatefulUi || report.target.skipV28 ? "pass" : "fail",
      score: report.v28?.summary?.canClaimDmStatefulUi || report.target.skipV28 ? 10 : 0,
      detail: report.target.skipV28 ? "skipped by option" : `dmStateful=${Boolean(report.v28?.summary?.canClaimDmStatefulUi)}`,
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
    commentSourceAndCapture: {
      status:
        checkStatus(report, /创建评论截流来源/) === "pass" &&
        checkStatus(report, /评论截流来源在页面可见/) === "pass" &&
        checkStatus(report, /browser-capture/) === "pass" &&
        checkStatus(report, /浏览器采集评论在评论线索池可见/) === "pass"
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /创建评论截流来源/) === "pass" &&
        checkStatus(report, /评论截流来源在页面可见/) === "pass" &&
        checkStatus(report, /browser-capture/) === "pass" &&
        checkStatus(report, /浏览器采集评论在评论线索池可见/) === "pass"
          ? 20
          : 0,
      detail: `source=${checkStatus(report, /创建评论截流来源/)}, sourceUi=${checkStatus(report, /评论截流来源在页面可见/)}, capture=${checkStatus(report, /browser-capture/)}, commentsUi=${checkStatus(report, /浏览器采集评论在评论线索池可见/)}`,
    },
    modelStateInvariants: {
      status:
        checkStatus(report, /高意向评论被规则识别/) === "pass" &&
        checkStatus(report, /页面按钮将高意向评论转入线索库/) === "pass" &&
        checkStatus(report, /评论状态变为已转线索/) === "pass"
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /高意向评论被规则识别/) === "pass" &&
        checkStatus(report, /页面按钮将高意向评论转入线索库/) === "pass" &&
        checkStatus(report, /评论状态变为已转线索/) === "pass"
          ? 15
          : 0,
      detail: `intentRule=${checkStatus(report, /高意向评论被规则识别/)}, convertUi=${checkStatus(report, /页面按钮将高意向评论转入线索库/)}, convertedStatus=${checkStatus(report, /评论状态变为已转线索/)}`,
    },
    intentPoolStatefulUi: {
      status:
        checkStatus(report, /评论截流线索写入/) === "pass" &&
        checkStatus(report, /意向客户池从评论线索同步客户/) === "pass" &&
        checkStatus(report, /意向客户池显示评论转入客户/) === "pass"
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /评论截流线索写入/) === "pass" &&
        checkStatus(report, /意向客户池从评论线索同步客户/) === "pass" &&
        checkStatus(report, /意向客户池显示评论转入客户/) === "pass"
          ? 20
          : 0,
      detail: `lead=${checkStatus(report, /评论截流线索写入/)}, intentApi=${checkStatus(report, /意向客户池从评论线索同步客户/)}, intentUi=${checkStatus(report, /意向客户池显示评论转入客户/)}`,
    },
    routeCoverage: {
      status:
        covered(report, "POST", "/direct-messages/intercepts/sources") &&
        covered(report, "POST", "/direct-messages/intercepts/sources/:param/browser-capture") &&
        covered(report, "POST", "/direct-messages/intercepts/comments/convert") &&
        covered(report, "GET", "/intent/customers") &&
        covered(report, "GET", "/intent/work-orders")
          ? "pass"
          : "fail",
      score:
        covered(report, "POST", "/direct-messages/intercepts/sources") &&
        covered(report, "POST", "/direct-messages/intercepts/sources/:param/browser-capture") &&
        covered(report, "POST", "/direct-messages/intercepts/comments/convert") &&
        covered(report, "GET", "/intent/customers") &&
        covered(report, "GET", "/intent/work-orders")
          ? 10
          : 0,
      detail: `source=${covered(report, "POST", "/direct-messages/intercepts/sources")}, capture=${covered(report, "POST", "/direct-messages/intercepts/sources/:param/browser-capture")}, convert=${covered(report, "POST", "/direct-messages/intercepts/comments/convert")}, intent=${covered(report, "GET", "/intent/customers")}, workOrders=${covered(report, "GET", "/intent/work-orders")}`,
    },
    noLiveOrDmSideEffects: {
      status:
        checkStatus(report, /不产生私信会话或消息/) === "pass" &&
        checkStatus(report, /真实平台同步\/自动私信发送未触发/) === "pass" &&
        !dangerousCovered
          ? "pass"
          : "fail",
      score:
        checkStatus(report, /不产生私信会话或消息/) === "pass" &&
        checkStatus(report, /真实平台同步\/自动私信发送未触发/) === "pass" &&
        !dangerousCovered
          ? 10
          : 0,
      detail: `noDm=${checkStatus(report, /不产生私信会话或消息/)}, noLive=${checkStatus(report, /真实平台同步\/自动私信发送未触发/)}, dangerousCovered=${dangerousCovered}`,
    },
    traceAndCorrelation: {
      status: traceExists && intentScreenshotExists && echoedResponses.length >= 6 ? "pass" : "warn",
      score: traceExists ? Math.min(5, 2 + Math.min(2, echoedResponses.length) + (intentScreenshotExists ? 1 : 0)) : 0,
      detail: `trace=${traceExists}, intentScreenshot=${intentScreenshotExists}, echo=${echoedResponses.length}/${commentTraffic.length}`,
    },
  };

  const score = Math.min(100, Object.values(dimensions).reduce((sum, item) => sum + item.score, 0));
  const hardFailure = Object.values(dimensions).some((item) => item.status === "fail");
  const runtimeHardFailure =
    report.commentIntentJourney.browser.pageErrors.length > 0 ||
    report.commentIntentJourney.browser.failedRequests.filter((request) => !/blockedbyclient/i.test(request.failure || "")).length > 0;
  const status = hardFailure || runtimeHardFailure ? "fail" : "warn";

  return {
    status,
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure && !runtimeHardFailure,
      canClaimCommentIntentStatefulUi: !hardFailure && !runtimeHardFailure,
      canClaimDmStatefulUi: Boolean(report.v28?.summary?.canClaimDmStatefulUi),
      canClaimCollectorStatefulUi: Boolean(report.v28?.summary?.canClaimCollectorStatefulUi),
      canClaimBroadBusinessCoverage: Boolean(report.v28?.summary?.canClaimBroadBusinessCoverage),
      canClaimRealBusinessReady: false,
      liveActionsStillGated: true,
      nextJourney: {
        module: "声音档案/报表导出/系统设置广度",
        suggestedGate: "promote the next V26 matrix gap into a stateful UI replay, or add model-based path generation over existing V17-V29 journeys",
      },
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V29 Comment Intercept + Intent Pool Stateful QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Comment intent stateful UI ready: ${report.summary.canClaimCommentIntentStatefulUi}`);
  lines.push(`DM stateful preserved: ${report.summary.canClaimDmStatefulUi}`);
  lines.push(`Real business ready: ${report.summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Journey Evidence");
  lines.push(`- Source: ${report.commentIntentJourney.state.created.sourceName || ""} (${report.commentIntentJourney.state.created.sourceId || ""})`);
  lines.push(`- High-intent author: ${report.commentIntentJourney.state.created.authorA || ""}`);
  lines.push(`- Converted lead: ${report.commentIntentJourney.state.created.leadId || ""}`);
  lines.push(`- Intent customer: ${report.commentIntentJourney.state.created.intentCustomerId || ""}`);
  lines.push(`- Work orders: ${(report.commentIntentJourney.state.created.workOrderIds || []).join(", ")}`);
  lines.push(`- Live sync/send remains gated: ${report.summary.liveActionsStillGated}`);
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V29 report: ${report.artifacts.report}`);
  lines.push(`- V29 markdown: ${report.artifacts.markdown}`);
  lines.push(`- V29 trace: ${report.commentIntentJourney.artifacts.trace}`);
  lines.push(`- V29 screenshots: ${report.commentIntentJourney.artifacts.screenshots.length}`);
  lines.push(`- V28 report: ${report.summary.v28Report}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const startedAt = Date.now();

  const report = {
    version: "V29",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      skipV28: options.skipV28,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Playwright trace viewer and tracing APIs support action-level debugging with snapshots, screenshots, and network evidence.",
      "Model-based testing turns a workflow into states and transitions, so V29 records source-created, comments-captured, high-intent-selected, converted, and intent-customer-visible invariants.",
      "Contract testing and schema/property testing suggest separating route contracts from functional UI assertions; V29 asserts both covered routes and state outcomes.",
    ],
    correlation: makeCorrelation(),
    v28Execution: null,
    v28: null,
    commentIntentJourney: {
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
      markdown: path.join(artifactDir, "comment-intent.md"),
    },
  };

  if (options.fromReport) {
    report.v28 = await readJson(options.fromReport);
    report.v28Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV28) {
    report.v28Execution = runV28(options, path.join(artifactDir, "v28"));
    report.v28 = report.v28Execution.report;
  } else {
    report.v28Execution = { command: "skip V28", exitCode: 0, durationMs: 0, parseError: null };
  }

  if (!report.v28) {
    report.v28 = {
      summary: {
        canClaimDmStatefulUi: false,
        canClaimCollectorStatefulUi: false,
        canClaimBroadBusinessCoverage: false,
        canClaimRealBusinessReady: false,
      },
    };
  }

  await runCommentIntentJourney(report, options, artifactDir);
  report.durationMs = Date.now() - startedAt;
  report.evaluation = await evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimCommentIntentStatefulUi: report.evaluation.readinessDecision.canClaimCommentIntentStatefulUi,
    canClaimDmStatefulUi: report.evaluation.readinessDecision.canClaimDmStatefulUi,
    canClaimCollectorStatefulUi: report.evaluation.readinessDecision.canClaimCollectorStatefulUi,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    liveActionsStillGated: report.evaluation.readinessDecision.liveActionsStillGated,
    nextJourney: report.evaluation.readinessDecision.nextJourney,
    v28Report: report.v28?.artifacts?.report || options.fromReport || "",
    trace: report.commentIntentJourney.artifacts.trace,
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V29 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} commentIntentStateful=${report.summary.canClaimCommentIntentStatefulUi} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Comment intent evidence: ${report.artifacts.markdown}`);
    console.log(`Trace: ${report.commentIntentJourney.artifacts.trace}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
