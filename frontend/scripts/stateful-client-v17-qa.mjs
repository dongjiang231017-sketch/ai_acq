#!/usr/bin/env node
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v17-stateful-qa");

const denyMutationPatterns = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/tasks\/[^/]+\/start\b/,
  /\/api\/direct-messages\/sync-replies\b/,
  /\/api\/direct-messages\/accounts\/[^/]+\/(?:login-window|login-session|desktop-login-check|preflight)\b/,
  /\/api\/direct-messages\/intercepts\/.*(?:sync|browser-capture|browser-dm-actions|automation)/,
  /\/api\/collections\/tasks\/[^/]+\/run\b/,
  /\/api\/voice\/.*(?:preview|training-jobs)/,
];

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    headed: false,
    json: false,
    keep: false,
    timeoutMs: 180000,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Number(next);
      index += 1;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--keep") {
      options.keep = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V17 stateful client QA

Usage:
  npm run qa:v17
  npm run quality:v17

What it does:
  - Creates an isolated SQLite database.
  - Runs Alembic migrations in the isolated DB.
  - Starts a temporary backend with a seeded customer login.
  - Starts a temporary Vite frontend wired to that backend.
  - Uses Playwright to log in, create a lead, create an outbound task, replay a mock realtime call, and verify API state deltas.
  - Blocks live call, recovery, external messaging, account/session send, and collection-run mutations.
`);
}

function correlationContext() {
  const runId = process.env.AI_ACQ_QA_CORRELATION_ID || "";
  const traceparent = process.env.AI_ACQ_QA_TRACEPARENT || "";
  if (!runId && !traceparent) return null;
  return {
    runId,
    traceparent,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V25`,
  };
}

function correlationHeaders(correlation) {
  if (!correlation) return {};
  return {
    ...(correlation.runId ? { "X-AI-ACQ-QA-Correlation-Id": correlation.runId, "X-Request-ID": correlation.runId } : {}),
    ...(correlation.traceparent ? { traceparent: correlation.traceparent } : {}),
    ...(correlation.baggage ? { baggage: correlation.baggage } : {}),
  };
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
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
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: options.env,
    detached: true,
    stdio: ["ignore", options.stdout, options.stderr],
  });
  return child;
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
      failures * 22 -
      warnings * 5 -
      report.browser.consoleErrors.length * 10 -
      report.browser.pageErrors.length * 12 -
      report.browser.failedRequests.length * 8 -
      report.browser.blockedMutations.length * 3,
  );

  report.summary = {
    status: maxRank === 3 || report.browser.pageErrors.length > 0 ? "fail" : maxRank === 2 || score < 90 ? "warn" : "pass",
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

async function apiRequest(report, baseUrl, pathName, options = {}) {
  const method = options.method || "GET";
  const url = `${baseUrl}${pathName}`;
  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(report.state.accessToken ? { Authorization: `Bearer ${report.state.accessToken}` } : {}),
      ...correlationHeaders(report.correlation),
      ...options.headers,
    },
    method,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { raw: text.slice(0, 1000) };
  }
  report.apiResponses?.push({
    method,
    url,
    status: response.status,
    echoedCorrelationId: response.headers.get("x-ai-acq-qa-correlation-id") || response.headers.get("x-request-id") || "",
    traceparent: response.headers.get("traceparent") || "",
    correlationEchoed: report.correlation?.runId ? response.headers.get("x-ai-acq-qa-correlation-id") === report.correlation.runId : null,
    traceparentEchoed: report.correlation?.traceparent ? response.headers.get("traceparent") === report.correlation.traceparent : null,
  });
  return { ok: response.ok, status: response.status, body };
}

async function seedMonitorRecord(report, task, lead) {
  if (!task?.id || !lead?.id || !report.runtime?.databaseUrl) return "";
  const python = await backendPython();
  const payload = {
    task_id: task.id,
    lead_id: lead.id,
    merchant_name: lead.name || "V17隔离监听客户",
    phone: lead.phone || "TEST-MONITOR",
    ai_seat: "AI-V17",
    duration_seconds: 42,
    intent_level: "B",
    current_node: "报价确认",
    outcome: "已接通",
    transcript: "客户：你好，我想了解一下怎么收费\\nAI：可以，我先确认您的主营品类和预算范围\\n客户：预算大概三千，先看效果",
    gateway_status: "completed",
    need_handoff: true,
  };
  const script = `
import json
import os
from app.db.session import SessionLocal
from app.models.task import CallRecord

payload = json.loads(os.environ["V17_MONITOR_RECORD"])
db = SessionLocal()
try:
    record = CallRecord(**payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    print(record.id)
finally:
    db.close()
`;
  const result = await runCommand(python, ["-c", script], {
    cwd: BACKEND_ROOT,
    env: {
      ...process.env,
      DATABASE_URL: report.runtime.databaseUrl,
      V17_MONITOR_RECORD: JSON.stringify(payload),
    },
  });
  return result.stdout.trim();
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
  report.artifacts.screenshots.push(file);
  return file;
}

function attachPageTelemetry(page, report, urls) {
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      const location = message.location();
      if (/\/api\/auth\/login\b/.test(location.url || "") && /401|Unauthorized/i.test(message.text())) {
        return;
      }
      report.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 800), location: message.location() });
    }
  });
  page.on("pageerror", (error) => {
    report.browser.pageErrors.push({ message: error.message, stack: error.stack });
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (/__vite_ping|favicon/.test(url)) return;
    report.browser.failedRequests.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
  });
  page.on("response", (response) => {
    const url = response.url();
    if (!url.startsWith(urls.apiBase)) return;
    const headers = response.headers();
    report.browser.apiResponses.push({
      method: response.request().method(),
      url,
      status: response.status(),
      echoedCorrelationId: headers["x-ai-acq-qa-correlation-id"] || headers["x-request-id"] || "",
      traceparent: headers.traceparent || "",
      correlationEchoed: report.correlation?.runId ? headers["x-ai-acq-qa-correlation-id"] === report.correlation.runId : null,
      traceparentEchoed: report.correlation?.traceparent ? headers.traceparent === report.correlation.traceparent : null,
    });
  });
}

async function installSafeMutationGuard(page, report, urls) {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const method = request.method().toUpperCase();
    const url = request.url();
    const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
    const isDenied = isMutation && denyMutationPatterns.some((pattern) => pattern.test(url));
    const isExternalMutation = isMutation && !url.startsWith(urls.apiBase) && !url.startsWith(urls.frontend);
    if (isDenied || isExternalMutation) {
      report.browser.blockedMutations.push({ method, url, reason: isDenied ? "dangerous-workflow" : "external-mutation" });
      await route.abort("blockedbyclient");
      return;
    }
    if (url.startsWith(urls.apiBase) && report.correlation) {
      await route.continue({ headers: { ...request.headers(), ...correlationHeaders(report.correlation) } });
      return;
    }
    await route.continue();
  });
}

async function writeSilentWav(filePath, durationSeconds = 1) {
  const sampleRate = 8000;
  const bitsPerSample = 16;
  const channels = 1;
  const sampleCount = sampleRate * durationSeconds;
  const dataSize = sampleCount * channels * (bitsPerSample / 8);
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(channels, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * channels * (bitsPerSample / 8), 28);
  buffer.writeUInt16LE(channels * (bitsPerSample / 8), 32);
  buffer.writeUInt16LE(bitsPerSample, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  await fs.writeFile(filePath, buffer);
}

async function fillPanelField(panel, label, value) {
  await panel.getByLabel(label, { exact: true }).fill(value);
}

async function runPlaywright(report, options, artifactDir, urls, credentials) {
  const browser = await launchBrowser(options.headed);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  });
  const page = await context.newPage();

  attachPageTelemetry(page, report, urls);
  await installSafeMutationGuard(page, report, urls);

  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  try {
    await page.goto(urls.frontend, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.getByRole("heading", { name: /登录进入获客工作台/ }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "01-login-gate");
    addCheck(report, "认证入口: 登录页可见", "pass", "customer login gate rendered");

    await page.getByLabel("登录账号", { exact: true }).fill(credentials.username);
    await page.getByLabel("密码", { exact: true }).fill("wrong-password");
    await page.getByRole("button", { name: /^登录$/ }).click();
    await page.getByText("账号或密码错误", { exact: false }).waitFor({ state: "visible", timeout: 10000 });
    addCheck(report, "认证负例: 错误密码被拒绝", "pass", "invalid login showed account/password error");

    await page.getByLabel("登录账号", { exact: true }).fill(credentials.username);
    await page.getByLabel("密码", { exact: true }).fill(credentials.password);
    await page.getByRole("button", { name: /^登录$/ }).click();
    await page.getByRole("heading", { name: /AI外呼系统/ }).waitFor({ state: "visible", timeout: 25000 });
    await page.getByText("在线坐席", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    addCheck(report, "实时工作台: AI外呼系统客户态指标可见", "pass", "AI外呼系统 / 在线坐席 / 实时通话");
    await page.getByRole("button", { name: /商家线索库/ }).click();
    await page.getByText("新增商家线索", { exact: false }).waitFor({ state: "visible", timeout: 25000 });
    await screenshot(page, report, artifactDir, "02-after-login-dashboard");
    addCheck(report, "认证正例: 客户账号可登录", "pass", `logged in as ${credentials.username}`);

    const authState = await page.evaluate(() => {
      const raw = window.localStorage.getItem("ai_acq_client_auth");
      return raw ? JSON.parse(raw) : null;
    });
    report.state.accessToken = authState?.accessToken || "";
    addCheck(report, "认证状态: token 已写入浏览器", report.state.accessToken ? "pass" : "fail", "localStorage auth token present");

    const storageStatePath = path.join(artifactDir, "auth-storage-state.json");
    await context.storageState({ path: storageStatePath });
    report.artifacts.storageState = storageStatePath;
    addCheck(report, "认证态复用: storageState 已保存", "pass", "auth-storage-state.json");

    const replayContext = await browser.newContext({
      storageState: storageStatePath,
      viewport: { width: 1440, height: 1050 },
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
    });
    const replayPage = await replayContext.newPage();
    attachPageTelemetry(replayPage, report, urls);
    await installSafeMutationGuard(replayPage, report, urls);
    try {
      await replayPage.goto(urls.frontend, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
      await replayPage.getByRole("heading", { name: /AI外呼系统/ }).waitFor({ state: "visible", timeout: 25000 });
      await replayPage.getByText("在线坐席", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
      const replayScreenshot = await screenshot(replayPage, report, artifactDir, "02b-auth-state-reuse-dashboard");
      const replayAuthState = await replayPage.evaluate(() => {
        const raw = window.localStorage.getItem("ai_acq_client_auth");
        return raw ? JSON.parse(raw) : null;
      });
      report.state.authReplay = {
        storageStatePath,
        screenshot: replayScreenshot,
        tokenReused: Boolean(replayAuthState?.accessToken),
      };
      addCheck(report, "认证态复用: 新浏览器上下文直达业务台", replayAuthState?.accessToken ? "pass" : "fail", "storageState replay reached AI外呼系统 without login form");
    } finally {
      await replayContext.close();
    }

    const beforeLeads = await apiRequest(report, urls.apiBase, "/leads");
    const beforeTasks = await apiRequest(report, urls.apiBase, "/outbound/tasks");
    const beforeCollectionTasks = await apiRequest(report, urls.apiBase, "/collections/tasks");
    const beforeCollectionRuns = await apiRequest(report, urls.apiBase, "/collections/runs");
    const beforeRawRecords = await apiRequest(report, urls.apiBase, "/collections/raw-records");
    const beforeDmAccounts = await apiRequest(report, urls.apiBase, "/direct-messages/accounts");
    const beforeDmTemplates = await apiRequest(report, urls.apiBase, "/direct-messages/templates");
    const beforeDmTasks = await apiRequest(report, urls.apiBase, "/direct-messages/tasks");
    const beforeVoiceProfiles = await apiRequest(report, urls.apiBase, "/voice/profiles");
    const beforeVoiceSamples = await apiRequest(report, urls.apiBase, "/voice/samples");
    const beforeVoiceTrainingJobs = await apiRequest(report, urls.apiBase, "/voice/training-jobs");
    const beforeSettings = await apiRequest(report, urls.apiBase, "/settings/items");
    const beforeAuditLogs = await apiRequest(report, urls.apiBase, "/settings/audit-logs");
    const beforeRealtimePipeline = await apiRequest(report, urls.apiBase, "/outbound/realtime/pipeline");
    const beforeRealtimeLiveEvents = await apiRequest(report, urls.apiBase, "/outbound/realtime/live-events?limit=80");
    report.state.before = {
      leads: Array.isArray(beforeLeads.body) ? beforeLeads.body.length : -1,
      outboundTasks: Array.isArray(beforeTasks.body) ? beforeTasks.body.length : -1,
      collectionTasks: Array.isArray(beforeCollectionTasks.body) ? beforeCollectionTasks.body.length : -1,
      collectionRuns: Array.isArray(beforeCollectionRuns.body) ? beforeCollectionRuns.body.length : -1,
      rawRecords: Array.isArray(beforeRawRecords.body) ? beforeRawRecords.body.length : -1,
      dmAccounts: Array.isArray(beforeDmAccounts.body) ? beforeDmAccounts.body.length : -1,
      dmTemplates: Array.isArray(beforeDmTemplates.body) ? beforeDmTemplates.body.length : -1,
      dmTasks: Array.isArray(beforeDmTasks.body) ? beforeDmTasks.body.length : -1,
      voiceProfiles: Array.isArray(beforeVoiceProfiles.body) ? beforeVoiceProfiles.body.length : -1,
      voiceSamples: Array.isArray(beforeVoiceSamples.body) ? beforeVoiceSamples.body.length : -1,
      voiceTrainingJobs: Array.isArray(beforeVoiceTrainingJobs.body) ? beforeVoiceTrainingJobs.body.length : -1,
      settings: Array.isArray(beforeSettings.body) ? beforeSettings.body.length : -1,
      auditLogs: Array.isArray(beforeAuditLogs.body) ? beforeAuditLogs.body.length : -1,
      realtimePipelineReady: Boolean(beforeRealtimePipeline.body?.readyForMockCall),
      realtimeLiveEvents: Array.isArray(beforeRealtimeLiveEvents.body?.events) ? beforeRealtimeLiveEvents.body.events.length : -1,
    };
    addCheck(
      report,
      "API 基线: 登录后可读线索、外呼、采集、私信、声音档案、设置和实时通话",
      beforeLeads.ok &&
        beforeTasks.ok &&
        beforeCollectionTasks.ok &&
        beforeCollectionRuns.ok &&
        beforeRawRecords.ok &&
        beforeDmAccounts.ok &&
        beforeDmTemplates.ok &&
        beforeDmTasks.ok &&
        beforeVoiceProfiles.ok &&
        beforeVoiceSamples.ok &&
        beforeVoiceTrainingJobs.ok &&
        beforeSettings.ok &&
        beforeAuditLogs.ok &&
        beforeRealtimePipeline.ok &&
        beforeRealtimeLiveEvents.ok
        ? "pass"
        : "fail",
      `leads=${report.state.before.leads}, outboundTasks=${report.state.before.outboundTasks}, collectionTasks=${report.state.before.collectionTasks}, runs=${report.state.before.collectionRuns}, raw=${report.state.before.rawRecords}, dmAccounts=${report.state.before.dmAccounts}, dmTemplates=${report.state.before.dmTemplates}, dmTasks=${report.state.before.dmTasks}, voiceProfiles=${report.state.before.voiceProfiles}, voiceSamples=${report.state.before.voiceSamples}, voiceTrainingJobs=${report.state.before.voiceTrainingJobs}, settings=${report.state.before.settings}, auditLogs=${report.state.before.auditLogs}, realtimePipelineReady=${report.state.before.realtimePipelineReady}, realtimeEvents=${report.state.before.realtimeLiveEvents}`,
    );

    const suffix = Date.now().toString(36);
    const leadName = `V17隔离回归店-${suffix}`;
    const taskName = `V17隔离外呼任务-${suffix}`;
    report.state.created = { leadName, taskName };

    const leadPanel = page.locator("article.panel").filter({ hasText: "新增商家线索" }).first();
    await fillPanelField(leadPanel, "商家名称", leadName);
    await fillPanelField(leadPanel, "城市", "南昌");
    await fillPanelField(leadPanel, "品类", "本地餐饮");
    await fillPanelField(leadPanel, "联系人", "V17测试联系人");
    await fillPanelField(leadPanel, "电话", `TEST-V17-${suffix}`);
    await leadPanel.getByRole("button", { name: /保存线索/ }).click();
    await page.getByText(leadName, { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "03-lead-created");
    addCheck(report, "UI 状态流: 创建线索后列表出现", "pass", leadName);

    const afterLead = await apiRequest(report, urls.apiBase, "/leads");
    const createdLead = Array.isArray(afterLead.body) ? afterLead.body.find((lead) => lead.name === leadName) : null;
    report.state.created.leadId = createdLead?.id || "";
    addCheck(
      report,
      "API 对账: 线索写入隔离数据库",
      createdLead && afterLead.body.length === report.state.before.leads + 1 ? "pass" : "fail",
      `leadId=${createdLead?.id || "missing"}, count ${report.state.before.leads}->${Array.isArray(afterLead.body) ? afterLead.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "数据隔离: 新线索归属当前用户",
      createdLead?.ownerUserId && createdLead?.createdByUserId ? "pass" : "fail",
      `owner=${createdLead?.ownerUserId || "missing"}, createdBy=${createdLead?.createdByUserId || "missing"}`,
    );

    async function openOutboundTaskPanel() {
      await page.getByRole("button", { name: /AI外呼系统/ }).click();
      await page.getByRole("heading", { name: /^AI外呼系统$/ }).waitFor({ state: "visible", timeout: 15000 });
      await page.locator("section.outbound-tabs").getByRole("button", { name: /^任务列表$/ }).click();
      await page.getByRole("heading", { name: /^外呼任务操作表单$/ }).waitFor({ state: "visible", timeout: 15000 });
      return page.locator("article.panel").filter({ hasText: "外呼任务操作表单" }).first();
    }

    let outboundPanel = await openOutboundTaskPanel();
    let outboundLeadRow = outboundPanel.locator("tbody tr").filter({ hasText: leadName }).first();
    if (!(await outboundLeadRow.isVisible({ timeout: 5000 }).catch(() => false))) {
      await page.reload({ waitUntil: "domcontentloaded", timeout: options.timeoutMs });
      outboundPanel = await openOutboundTaskPanel();
      outboundLeadRow = outboundPanel.locator("tbody tr").filter({ hasText: leadName }).first();
    }
    if (await outboundLeadRow.isVisible({ timeout: 3000 }).catch(() => false)) {
      const outboundLeadCheckbox = outboundLeadRow.locator('input[type="checkbox"]').first();
      if (!(await outboundLeadCheckbox.isChecked())) {
        await outboundLeadCheckbox.check();
      }
    }
    await fillPanelField(outboundPanel, "任务名称", taskName);
    await fillPanelField(outboundPanel, "并发数量", "1");
    try {
      const outboundTaskResponse = page.waitForResponse(
        (response) => response.url() === `${urls.apiBase}/outbound/tasks` && response.request().method() === "POST",
        { timeout: 20000 },
      );
      await outboundPanel.getByRole("button", { name: /创建外呼任务/ }).click();
      await outboundTaskResponse;
    } catch (error) {
      if (!createdLead?.id) throw error;
      const fallbackTask = await apiRequest(report, urls.apiBase, "/outbound/tasks", {
        method: "POST",
        body: {
          name: taskName,
          leadIds: [createdLead.id],
          concurrency: 1,
          scriptId: null,
          scheduledAt: null,
        },
      });
      addCheck(
        report,
        "恢复路径: 外呼任务 UI 未提交时使用隔离 API 创建",
        fallbackTask.ok ? "warn" : "fail",
        `status=${fallbackTask.status}, leadId=${createdLead.id}`,
      );
      if (!fallbackTask.ok) throw error;
      await page.reload({ waitUntil: "domcontentloaded", timeout: options.timeoutMs });
      await openOutboundTaskPanel();
    }
    await page.getByText(taskName, { exact: true }).waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "04-outbound-task-created");
    addCheck(report, "UI 状态流: 创建外呼任务后队列出现", "pass", taskName);

    const afterTask = await apiRequest(report, urls.apiBase, "/outbound/tasks");
    const createdTask = Array.isArray(afterTask.body) ? afterTask.body.find((task) => task.name === taskName) : null;
    report.state.created.taskId = createdTask?.id || "";
    addCheck(
      report,
      "API 对账: 外呼任务写入隔离数据库",
      createdTask && afterTask.body.length === report.state.before.outboundTasks + 1 ? "pass" : "fail",
      `taskId=${createdTask?.id || "missing"}, targetCount=${createdTask?.targetCount ?? "missing"}`,
    );
    addCheck(
      report,
      "安全门控: 任务只创建不启动",
      createdTask?.status === "待启动" ? "pass" : "fail",
      `status=${createdTask?.status || "missing"}`,
    );
    addCheck(
      report,
      "安全门控: 危险请求被默认阻断或未触发",
      report.browser.blockedMutations.length === 0 ? "pass" : "warn",
      `blocked=${report.browser.blockedMutations.length}`,
      report.browser.blockedMutations,
    );

    await page.locator("section.outbound-tabs").getByRole("button", { name: /^话术流程$/ }).click();
    await page.getByRole("heading", { name: /^话术流程$/ }).waitFor({ state: "visible", timeout: 15000 });
    const scriptPanel = page.locator("article.panel").filter({ hasText: "话术流程" }).first();
    await scriptPanel.getByRole("button", { name: /AI生成/ }).click();
    await page.getByText("AI 已根据业务和当前客户回复生成一版话术", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await fillPanelField(scriptPanel, "话术名称", `V17隔离话术-${suffix}`);
    const scriptSaveResponse = page.waitForResponse(
      (response) => /\/api\/outbound\/scripts(?:\/[^/]+)?$/.test(response.url()) && ["POST", "PATCH"].includes(response.request().method()),
      { timeout: 20000 },
    );
    await scriptPanel.getByRole("button", { name: /保存话术/ }).click();
    await scriptSaveResponse;
    await page.getByText("已保存", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "05-script-editor-saved");
    addCheck(report, "UI 状态流: 客户可 AI 生成并保存外呼话术", "pass", `V17隔离话术-${suffix}`);

    await page.locator("section.outbound-tabs").getByRole("button", { name: /^重拨规则$/ }).click();
    await page.getByRole("heading", { name: /^重拨规则$/ }).waitFor({ state: "visible", timeout: 15000 });
    const recallPanel = page.locator("article.panel").filter({ hasText: "重拨规则" }).first();
    await fillPanelField(recallPanel, "最大次数", "4");
    const recallSaveResponse = page.waitForResponse(
      (response) => /\/api\/outbound\/recall-rules\/[^/]+$/.test(response.url()) && response.request().method() === "PATCH",
      { timeout: 20000 },
    );
    await recallPanel.getByRole("button", { name: /保存规则/ }).click();
    await recallSaveResponse;
    await page.getByText("已保存", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "06-recall-rule-saved");
    addCheck(report, "UI 状态流: 客户可调整并保存重拨规则", "pass", "maxAttempts=4");

    const monitorRecordId = await seedMonitorRecord(report, createdTask, createdLead);
    report.state.created.monitorRecordId = monitorRecordId;
    addCheck(
      report,
      "测试夹具: 隔离通话记录已供实时监听点击",
      monitorRecordId ? "pass" : "warn",
      `recordId=${monitorRecordId || "missing"}`,
    );
    await page.reload({ waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.getByRole("button", { name: /AI外呼系统/ }).click();
    await page.getByRole("heading", { name: /^AI外呼系统$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.locator("section.outbound-tabs").getByRole("button", { name: /^实时监听$/ }).click();
    await page.getByRole("heading", { name: /^实时监听聊天$/ }).waitFor({ state: "visible", timeout: 15000 });
    const realtimePanel = page.locator("article.panel").filter({ hasText: "实时监听聊天" }).first();
    await realtimePanel.getByLabel("实时通话客户").waitFor({ state: "visible", timeout: 15000 });
    const monitorButtons = realtimePanel.locator(".monitor-call-list button");
    const monitorCount = await monitorButtons.count();
    if (monitorCount > 0) {
      await monitorButtons.first().click();
    }
    await realtimePanel.locator(".monitor-chat-panel").waitFor({ state: "visible", timeout: 15000 });
    await realtimePanel.getByText("当前话术", { exact: true }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "07-realtime-monitor-chat");
    addCheck(
      report,
      "UI 状态流: 实时监听以客户列表和聊天面板呈现",
      monitorCount > 0 ? "pass" : "warn",
      `monitorCalls=${monitorCount}`,
    );
    addCheck(
      report,
      "安全门控: 实时监听查看未触发真实单号试拨",
      report.browser.apiResponses.some((entry) => /\/api\/outbound\/telephony\/test-call\b/.test(entry.url)) ? "fail" : "pass",
      "monitor chat only; no telephony test-call request observed",
    );

    await page.getByRole("button", { name: /线索采集/ }).click();
    await page.getByRole("heading", { name: /^线索采集$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("heading", { name: /^新建采集任务$/ }).waitFor({ state: "visible", timeout: 15000 });
    const collectionTaskName = `V17隔离采集任务-${suffix}`;
    report.state.created.collectionTaskName = collectionTaskName;
    const collectionPanel = page
      .locator("article.panel")
      .filter({ hasText: "地图点位采集" })
      .filter({ hasText: "新建采集任务" })
      .first();
    await collectionPanel.locator("input").nth(0).fill(collectionTaskName);
    await collectionPanel.locator("select").first().selectOption("public_web");
    await collectionPanel.locator('input[type="number"]').first().fill("2");
    await collectionPanel.locator("input").nth(2).fill("南昌");
    await collectionPanel.locator("input").nth(3).fill("餐饮");
    await collectionPanel.locator("input").nth(4).fill("隔离回放");
    await collectionPanel.getByRole("button", { name: /创建采集任务/ }).click();
    await page.getByText(collectionTaskName, { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "08-collection-task-created");
    addCheck(report, "UI 状态流: 线索采集任务创建后队列出现", "pass", collectionTaskName);

    const afterCollectionTasks = await apiRequest(report, urls.apiBase, "/collections/tasks");
    const afterCollectionRuns = await apiRequest(report, urls.apiBase, "/collections/runs");
    const afterRawRecords = await apiRequest(report, urls.apiBase, "/collections/raw-records");
    const afterCollectionLeads = await apiRequest(report, urls.apiBase, "/leads");
    const createdCollectionTask = Array.isArray(afterCollectionTasks.body)
      ? afterCollectionTasks.body.find((task) => task.name === collectionTaskName)
      : null;
    report.state.created.collectionTaskId = createdCollectionTask?.id || "";
    addCheck(
      report,
      "API 对账: 线索采集任务写入隔离数据库",
      createdCollectionTask && afterCollectionTasks.body.length === report.state.before.collectionTasks + 1 ? "pass" : "fail",
      `collectionTaskId=${createdCollectionTask?.id || "missing"}, provider=${createdCollectionTask?.provider || "missing"}, count ${report.state.before.collectionTasks}->${Array.isArray(afterCollectionTasks.body) ? afterCollectionTasks.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "数据隔离: 采集任务归属当前用户",
      createdCollectionTask?.ownerUserId && createdCollectionTask?.createdByUserId ? "pass" : "fail",
      `owner=${createdCollectionTask?.ownerUserId || "missing"}, createdBy=${createdCollectionTask?.createdByUserId || "missing"}`,
    );
    addCheck(
      report,
      "安全门控: 采集任务只创建不运行",
      createdCollectionTask?.status === "待采集"
        && Array.isArray(afterCollectionRuns.body)
        && afterCollectionRuns.body.length === report.state.before.collectionRuns
        && Array.isArray(afterRawRecords.body)
        && afterRawRecords.body.length === report.state.before.rawRecords
        ? "pass"
        : "fail",
      `status=${createdCollectionTask?.status || "missing"}, runs ${report.state.before.collectionRuns}->${Array.isArray(afterCollectionRuns.body) ? afterCollectionRuns.body.length : "unknown"}, raw ${report.state.before.rawRecords}->${Array.isArray(afterRawRecords.body) ? afterRawRecords.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 采集创建不产生线索副作用",
      Array.isArray(afterCollectionLeads.body) && afterCollectionLeads.body.length === report.state.before.leads + 1 ? "pass" : "fail",
      `leads expected ${report.state.before.leads + 1}, actual=${Array.isArray(afterCollectionLeads.body) ? afterCollectionLeads.body.length : "unknown"}`,
    );

    await page.getByRole("button", { name: /平台私信系统/ }).click();
    await page.getByRole("heading", { name: /^平台私信系统$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("button", { name: /^账号管理$/ }).click();
    await page.getByRole("heading", { name: /^平台个人号管理$/ }).waitFor({ state: "visible", timeout: 15000 });

    const dmAccountName = `V17隔离美团号-${suffix}`;
    const dmTemplateName = `V17隔离私信模板-${suffix}`;
    report.state.created.dmAccountName = dmAccountName;
    report.state.created.dmTemplateName = dmTemplateName;

    const dmAccountPanel = page.locator("article.panel").filter({ hasText: "平台个人号管理" }).first();
    await dmAccountPanel.locator("select").first().selectOption("美团");
    await dmAccountPanel.locator('[data-dm-account-name="true"]').fill(dmAccountName);
    await dmAccountPanel.locator("input").nth(1).fill("V17隔离账号备注");
    await dmAccountPanel.locator('input[type="number"]').nth(0).fill("5");
    await dmAccountPanel.locator('input[type="number"]').nth(1).fill("30");
    await dmAccountPanel.getByRole("button", { name: /保存账号/ }).click();
    await page.getByText(dmAccountName, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "09-dm-account-created");
    addCheck(report, "UI 状态流: 平台私信账号创建后列表出现", "pass", dmAccountName);

    const afterDmAccounts = await apiRequest(report, urls.apiBase, "/direct-messages/accounts");
    const createdDmAccount = Array.isArray(afterDmAccounts.body)
      ? afterDmAccounts.body.find((account) => account.accountName === dmAccountName)
      : null;
    report.state.created.dmAccountId = createdDmAccount?.id || "";
    addCheck(
      report,
      "API 对账: 私信账号写入隔离数据库",
      createdDmAccount && afterDmAccounts.body.length === report.state.before.dmAccounts + 1 ? "pass" : "fail",
      `dmAccountId=${createdDmAccount?.id || "missing"}, count ${report.state.before.dmAccounts}->${Array.isArray(afterDmAccounts.body) ? afterDmAccounts.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 私信账号保持待登录不伪造登录态",
      createdDmAccount?.status === "待登录" && createdDmAccount?.sessionStatus === "未登录" ? "pass" : "fail",
      `status=${createdDmAccount?.status || "missing"}, session=${createdDmAccount?.sessionStatus || "missing"}`,
    );

    await page.getByRole("button", { name: /^消息模板$/ }).click();
    await page.getByRole("heading", { name: /^私信模板表单$/ }).waitFor({ state: "visible", timeout: 15000 });
    const dmTemplatePanel = page.locator("article.panel").filter({ hasText: "私信模板表单" }).first();
    await dmTemplatePanel.locator("input").first().fill(dmTemplateName);
    await dmTemplatePanel.locator("select").first().selectOption("美团");
    await dmTemplatePanel.locator("textarea").first().fill("您好，我们正在做本地商家增长方案的隔离回放测试，本条不会真实发送。");
    await dmTemplatePanel.getByRole("button", { name: /保存模板/ }).click();
    await page.getByText(dmTemplateName, { exact: false }).first().waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "10-dm-template-created");
    addCheck(report, "UI 状态流: 私信模板创建后模板库出现", "pass", dmTemplateName);

    const afterDmTemplates = await apiRequest(report, urls.apiBase, "/direct-messages/templates");
    const afterDmTasks = await apiRequest(report, urls.apiBase, "/direct-messages/tasks");
    const createdDmTemplate = Array.isArray(afterDmTemplates.body)
      ? afterDmTemplates.body.find((template) => template.name === dmTemplateName)
      : null;
    report.state.created.dmTemplateId = createdDmTemplate?.id || "";
    addCheck(
      report,
      "API 对账: 私信模板写入隔离数据库",
      createdDmTemplate && afterDmTemplates.body.length === report.state.before.dmTemplates + 1 ? "pass" : "fail",
      `dmTemplateId=${createdDmTemplate?.id || "missing"}, count ${report.state.before.dmTemplates}->${Array.isArray(afterDmTemplates.body) ? afterDmTemplates.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 私信回放只建账号和模板不启动发送",
      Array.isArray(afterDmTasks.body) && afterDmTasks.body.length === report.state.before.dmTasks ? "pass" : "fail",
      `dmTasks ${report.state.before.dmTasks}->${Array.isArray(afterDmTasks.body) ? afterDmTasks.body.length : "unknown"}`,
    );

    const voiceProfileName = `V17隔离声音档案-${suffix}`;
    const voiceOwnerName = `V17授权人-${suffix}`;
    const voiceSamplePath = path.join(artifactDir, `v17-voice-sample-${suffix}.wav`);
    await writeSilentWav(voiceSamplePath);
    report.state.created.voiceProfileName = voiceProfileName;
    report.state.created.voiceOwnerName = voiceOwnerName;

    await page.getByRole("button", { name: /声音档案/ }).click();
    await page.getByRole("heading", { name: /^声音档案$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("heading", { name: /^新增授权克隆档案$/ }).waitFor({ state: "visible", timeout: 15000 });
    const voiceProfilePanel = page.locator("article.panel").filter({ hasText: "新增授权克隆档案" }).first();
    await voiceProfilePanel.locator("input").nth(0).fill(voiceProfileName);
    await voiceProfilePanel.locator("input").nth(1).fill(voiceOwnerName);
    await voiceProfilePanel.locator("select").nth(0).selectOption("外呼");
    await voiceProfilePanel.locator('input[type="file"]').setInputFiles(voiceSamplePath);
    await voiceProfilePanel.locator("textarea").first().fill("V17隔离授权说明：仅用于本地回放，不进入真实训练。");
    await voiceProfilePanel.getByRole("button", { name: /新增克隆档案/ }).click();
    await page.getByText(voiceProfileName, { exact: false }).first().waitFor({ state: "visible", timeout: 20000 });
    await screenshot(page, report, artifactDir, "11-voice-profile-created");
    addCheck(report, "UI 状态流: 声音档案创建后授权审核出现", "pass", voiceProfileName);

    const afterVoiceProfiles = await apiRequest(report, urls.apiBase, "/voice/profiles");
    const afterVoiceSamples = await apiRequest(report, urls.apiBase, "/voice/samples");
    const afterVoiceTrainingJobs = await apiRequest(report, urls.apiBase, "/voice/training-jobs");
    const createdVoiceProfile = Array.isArray(afterVoiceProfiles.body)
      ? afterVoiceProfiles.body.find((profile) => profile.name === voiceProfileName)
      : null;
    const createdVoiceSample = Array.isArray(afterVoiceSamples.body)
      ? afterVoiceSamples.body.find((sample) => sample.profileId === createdVoiceProfile?.id)
      : null;
    report.state.created.voiceProfileId = createdVoiceProfile?.id || "";
    report.state.created.voiceSampleId = createdVoiceSample?.id || "";
    addCheck(
      report,
      "API 对账: 声音档案写入隔离数据库",
      createdVoiceProfile && afterVoiceProfiles.body.length === report.state.before.voiceProfiles + 1 ? "pass" : "fail",
      `voiceProfileId=${createdVoiceProfile?.id || "missing"}, status=${createdVoiceProfile?.status || "missing"}, count ${report.state.before.voiceProfiles}->${Array.isArray(afterVoiceProfiles.body) ? afterVoiceProfiles.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "API 对账: 声音授权样本写入隔离存储",
      createdVoiceSample && afterVoiceSamples.body.length === report.state.before.voiceSamples + 1 ? "pass" : "fail",
      `voiceSampleId=${createdVoiceSample?.id || "missing"}, profileId=${createdVoiceSample?.profileId || "missing"}, count ${report.state.before.voiceSamples}->${Array.isArray(afterVoiceSamples.body) ? afterVoiceSamples.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 声音档案待授权且不触发训练",
      createdVoiceProfile?.status === "待授权"
        && createdVoiceProfile?.authorizationStatus === "待提交"
        && Array.isArray(afterVoiceTrainingJobs.body)
        && afterVoiceTrainingJobs.body.length === report.state.before.voiceTrainingJobs
        ? "pass"
        : "fail",
      `status=${createdVoiceProfile?.status || "missing"}, authorization=${createdVoiceProfile?.authorizationStatus || "missing"}, trainingJobs ${report.state.before.voiceTrainingJobs}->${Array.isArray(afterVoiceTrainingJobs.body) ? afterVoiceTrainingJobs.body.length : "unknown"}`,
    );

    const outboundQueueSetting = Array.isArray(beforeSettings.body)
      ? beforeSettings.body.find((setting) => setting.groupKey === "telephony" && setting.itemKey === "queue_enabled")
      : null;
    const nextOutboundQueueValue = outboundQueueSetting?.value === "true" ? "false" : "true";
    report.state.created.settingId = outboundQueueSetting?.id || "";
    report.state.created.settingValue = nextOutboundQueueValue;

    await page.getByRole("button", { name: /系统设置/ }).click();
    await page.getByRole("heading", { name: /^系统设置$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("button", { name: /^电话线路$/ }).click();
    await page.getByRole("heading", { name: /^电话线路$/ }).waitFor({ state: "visible", timeout: 15000 });
    await page.getByRole("button", { name: /外呼队列/ }).first().click();
    await page.getByRole("heading", { name: /^调整运营设置$/ }).waitFor({ state: "visible", timeout: 15000 });
    const settingsPanel = page.locator("article.panel").filter({ hasText: "调整运营设置" }).first();
    await settingsPanel.locator("label").filter({ hasText: "调整为" }).locator("select").selectOption(nextOutboundQueueValue);
    const settingPatchResponse = page.waitForResponse(
      (response) =>
        response.url() === `${urls.apiBase}/settings/items/${outboundQueueSetting?.id}` && response.request().method() === "PATCH",
      { timeout: 20000 },
    );
    await settingsPanel.getByRole("button", { name: /保存设置/ }).click();
    await settingPatchResponse;
    await page.getByText("已保存", { exact: false }).waitFor({ state: "visible", timeout: 15000 });
    await screenshot(page, report, artifactDir, "12-settings-updated");
    addCheck(report, "UI 状态流: 系统设置保存后前端提示成功", "pass", `外呼队列=${nextOutboundQueueValue}`);

    const afterSettings = await apiRequest(report, urls.apiBase, "/settings/items");
    const afterAuditLogs = await apiRequest(report, urls.apiBase, "/settings/audit-logs");
    const updatedSetting = Array.isArray(afterSettings.body)
      ? afterSettings.body.find((setting) => setting.id === outboundQueueSetting?.id)
      : null;
    const createdAuditLog = Array.isArray(afterAuditLogs.body)
      ? afterAuditLogs.body.find((log) => log.targetId === outboundQueueSetting?.id && log.afterValue === nextOutboundQueueValue)
      : null;
    addCheck(
      report,
      "API 对账: 系统设置写入隔离数据库",
      updatedSetting?.value === nextOutboundQueueValue && afterSettings.body.length === report.state.before.settings ? "pass" : "fail",
      `settingId=${updatedSetting?.id || "missing"}, value=${updatedSetting?.value || "missing"}, count ${report.state.before.settings}->${Array.isArray(afterSettings.body) ? afterSettings.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "API 对账: 系统设置审计日志新增",
      createdAuditLog && afterAuditLogs.body.length === report.state.before.auditLogs + 1 ? "pass" : "fail",
      `auditId=${createdAuditLog?.id || "missing"}, auditLogs ${report.state.before.auditLogs}->${Array.isArray(afterAuditLogs.body) ? afterAuditLogs.body.length : "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 设置回放未触碰敏感密钥",
      updatedSetting && !updatedSetting.sensitive ? "pass" : "fail",
      `label=${updatedSetting?.label || "missing"}, sensitive=${updatedSetting?.sensitive ?? "missing"}`,
    );

    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForTimeout(500);
    await screenshot(page, report, artifactDir, "13-mobile-after-stateful-flow");
    addCheck(report, "移动端回放: 已登录业务态可截图", "pass", "mobile screenshot captured after stateful flow");
  } finally {
    const tracePath = path.join(artifactDir, "trace.zip");
    await context.tracing.stop({ path: tracePath }).catch(() => {});
    report.artifacts.trace = tracePath;
    await context.close();
    await browser.close();
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V17",
    generatedAt: new Date().toISOString(),
    project: "ai_acq",
    correlation: correlationContext(),
    summary: null,
    checks: [],
    state: {
      accessToken: "",
      before: {},
      created: {},
    },
    runtime: {},
    browser: {
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
      blockedMutations: [],
      apiResponses: [],
    },
    apiResponses: [],
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      trace: null,
      screenshots: [],
      storageState: "",
      backendLog: path.join(artifactDir, "backend.log"),
      frontendLog: path.join(artifactDir, "frontend.log"),
      migrationLog: path.join(artifactDir, "migration.log"),
    },
  };

  const children = [];
  let backendStdout = null;
  let backendStderr = null;
  let frontendStdout = null;
  let frontendStderr = null;

  try {
    const apiPort = await findFreePort();
    const frontendPort = await findFreePort();
    const python = await backendPython();
    const databasePath = path.join(artifactDir, "v17.sqlite");
    const databaseUrl = `sqlite:///${databasePath}`;
    const credentials = {
      username: `v17_client_${Date.now().toString(36)}`,
      password: `V17-${Math.random().toString(36).slice(2, 10)}-pass`,
    };
    const env = {
      ...process.env,
      DATABASE_URL: databaseUrl,
      AUTH_SECRET_KEY: `v17-auth-${Date.now()}`,
      ADMIN_SECRET_KEY: `v17-admin-${Date.now()}`,
      INITIAL_CLIENT_USERNAME: credentials.username,
      INITIAL_CLIENT_PASSWORD: credentials.password,
      INITIAL_CLIENT_DISPLAY_NAME: "V17隔离客户",
      INITIAL_CLIENT_PHONE: "",
      INITIAL_CLIENT_EMAIL: "",
      ASTERISK_LIVE_CALL_ENABLED: "false",
      ASTERISK_BULK_CALL_ENABLED: "false",
      OUTBOUND_QUEUE_ENABLED: "false",
      DM_BROWSER_LIVE_SEND_ENABLED: "false",
      COMMENT_INTERCEPT_LIVE_SYNC_ENABLED: "false",
      COMMENT_INTERCEPT_ADAPTER_MODE: "disabled",
      REALTIME_CONVERSATION_MODE: "pipeline",
      VOICE_SAMPLE_STORAGE_ROOT: path.join(artifactDir, "voice-samples"),
    };
    report.runtime = {
      apiPort,
      frontendPort,
      databasePath,
      databaseUrl,
      credentialsAlias: credentials.username,
    };

    const migration = await runCommand(python, ["-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], {
      cwd: BACKEND_ROOT,
      env,
    });
    await fs.writeFile(report.artifacts.migrationLog, `${migration.stdout}\n${migration.stderr}`, "utf8");
    addCheck(report, "沙箱数据库: Alembic 迁移到 head", "pass", databasePath);

    backendStdout = await fs.open(report.artifacts.backendLog, "w");
    backendStderr = await fs.open(report.artifacts.backendLog, "a");
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
    const apiBase = `http://127.0.0.1:${apiPort}/api`;
    await waitForUrl(`${apiBase}/health`, options.timeoutMs, "ok");
    addCheck(report, "沙箱后端: 临时 API 可用", "pass", apiBase);

    frontendStdout = await fs.open(report.artifacts.frontendLog, "w");
    frontendStderr = await fs.open(report.artifacts.frontendLog, "a");
    const frontendEnv = {
      ...process.env,
      VITE_API_BASE_URL: apiBase,
    };
    const frontend = startProcess("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(frontendPort)], {
      cwd: FRONTEND_ROOT,
      env: frontendEnv,
      stdout: frontendStdout.createWriteStream(),
      stderr: frontendStderr.createWriteStream(),
    });
    children.push(frontend);
    const frontendUrl = `http://127.0.0.1:${frontendPort}/`;
    await waitForUrl(frontendUrl, options.timeoutMs, "视频号团购商家AI获客客户端");
    addCheck(report, "沙箱前端: 临时 Vite 可用", "pass", frontendUrl);

    await runPlaywright(report, options, artifactDir, { frontend: frontendUrl, apiBase }, credentials);
  } catch (error) {
    addCheck(report, "V17 stateful QA runner", "fail", error.stack || error.message);
  } finally {
    if (!options.keep) {
      for (const child of children.reverse()) stopProcess(child);
    }
    await backendStdout?.close().catch(() => {});
    await backendStderr?.close().catch(() => {});
    await frontendStdout?.close().catch(() => {});
    await frontendStderr?.close().catch(() => {});
  }

  summarize(report);
  await writeJson(report.artifacts.report, report);

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V17 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Trace: ${report.artifacts.trace}`);
    for (const check of report.checks) {
      const marker = check.status === "pass" ? "PASS" : check.status === "warn" ? "WARN" : "FAIL";
      console.log(`${marker} ${check.name}: ${check.detail}`);
    }
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
