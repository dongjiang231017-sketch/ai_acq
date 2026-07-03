#!/usr/bin/env node
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v15-human-like-qa");
const DEFAULT_APP = "/Applications/商家AI获客客户端.app";
const DEFAULT_API = "http://127.0.0.1:8017/api";

const modules = ["实时工作台", "线索采集", "商家线索库", "AI外呼系统", "平台私信系统", "意向客户池", "声音档案", "数据报表", "系统设置"];
const tabMap = {
  AI外呼系统: ["外呼总览", "任务列表", "话术流程", "通话记录", "重拨规则", "实时监听"],
  平台私信系统: ["私信总览", "评论截流", "任务列表", "账号管理", "轮换规则", "消息模板", "会话记录", "回复监听"],
  意向客户池: ["客户池", "跟进工单", "客户详情", "分配规则"],
  声音档案: ["声音档案", "授权审核", "音色复刻", "使用记录"],
  数据报表: ["报表总览", "渠道分析", "销售绩效", "导出中心"],
  系统设置: ["设置总览", "电话线路", "平台账号", "合规保护"],
};

const expectedHttpFailures = [
  /\/api\/auth\/login$/,
  /\/api\/collections\/tasks\/[^/]+\/run$/,
  /\/api\/voice\/provider\/status/,
];

function parseArgs(argv) {
  const options = {
    app: DEFAULT_APP,
    api: DEFAULT_API,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    iterations: 21,
    cdpPort: 9235,
    headed: false,
    json: false,
    timeoutMs: 240000,
    username: "v15_client",
    password: "v15-client-pass-20260702",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--app" && next) {
      options.app = path.resolve(next);
      index += 1;
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--iterations" && next) {
      options.iterations = Number(next);
      index += 1;
    } else if (arg === "--cdp-port" && next) {
      options.cdpPort = Number(next);
      index += 1;
    } else if (arg === "--username" && next) {
      options.username = next;
      index += 1;
    } else if (arg === "--password" && next) {
      options.password = next;
      index += 1;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--json") {
      options.json = true;
    }
  }
  return options;
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function delay(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function resolveDesktopExecutable(appPath) {
  if (!appPath.endsWith(".app")) return appPath;
  const macosDir = path.join(appPath, "Contents", "MacOS");
  const candidate = path.join(macosDir, path.basename(appPath, ".app"));
  try {
    await fs.access(candidate);
    return candidate;
  } catch {
    const entries = await fs.readdir(macosDir);
    if (!entries.length) throw new Error(`No executable found under ${macosDir}`);
    return path.join(macosDir, entries[0]);
  }
}

async function waitForCdp(cdpUrl, timeoutMs) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(`${cdpUrl}/json/version`);
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`CDP not ready at ${cdpUrl}: ${lastError?.message || "timeout"}`);
}

async function firstUsefulPage(browser) {
  const deadline = Date.now() + 30000;
  let fallback = null;
  while (Date.now() < deadline) {
    const pages = browser
      .contexts()
      .flatMap((context) => context.pages())
      .filter((page) => !page.url().startsWith("devtools://"));
    fallback = fallback || pages[0] || null;
    for (const page of pages) {
      const title = await page.title().catch(() => "");
      if (/商家AI|视频号|AI获客/.test(title) || /app\.asar|index\.html/.test(page.url())) return page;
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  if (fallback) return fallback;
  throw new Error("No Electron page found");
}

function addCheck(report, name, status, detail, data = undefined) {
  report.checks.push({ name, status, detail, data });
}

function addCoverage(report, key) {
  report.coverage[key] = (report.coverage[key] || 0) + 1;
}

async function screenshot(page, report, artifactDir, name) {
  const file = path.join(artifactDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  report.artifacts.screenshots.push(file);
}

async function clickButton(page, name, report, coverageKey = name, timeout = 6000) {
  const exact = page.getByRole("button", { name: new RegExp(`^${escapeRegExp(name)}$`) });
  const fuzzy = page.getByRole("button", { name: new RegExp(escapeRegExp(name)) });
  const target = (await exact.count()) ? exact.first() : fuzzy.first();
  await target.waitFor({ state: "visible", timeout });
  await target.click();
  addCoverage(report, coverageKey);
  await delay(160);
}

async function fillByLabel(scope, label, value, timeout = 4000) {
  const field = scope.getByLabel(label, { exact: true });
  await field.waitFor({ state: "visible", timeout });
  await field.fill(value);
}

async function safeStep(report, name, fn) {
  try {
    const detail = await fn();
    addCheck(report, name, "pass", detail || "ok");
    return true;
  } catch (error) {
    addCheck(report, name, "fail", error.message || String(error));
    return false;
  }
}

async function apiRequest(report, pathName, options = {}) {
  const token = report.state.accessToken;
  const response = await fetch(`${report.options.api}${pathName}`, {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
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

async function registerFromFrontend(page, report) {
  await clickButton(page, "申请开通", report, "auth.register.switch");
  const suffix = Date.now().toString(36);
  await fillByLabel(page, "公司名称", `V15前端注册公司-${suffix}`);
  await fillByLabel(page, "商户/项目", `V15前端注册项目-${suffix}`);
  await fillByLabel(page, "联系人", "V15前端测试员");
  await fillByLabel(page, "联系手机号", `138${String(Date.now()).slice(-8)}`);
  await fillByLabel(page, "登录账号", `v15_front_${suffix}`);
  await fillByLabel(page, "联系邮箱", `v15-front-${suffix}@example.test`);
  await clickButton(page, "提交申请", report, "auth.register.submit");
  await page.getByText("申请已提交", { exact: false }).waitFor({ state: "visible", timeout: 10000 });
  addCheck(report, "前端注册申请: 提交成功", "pass", "registration request created from login page");
}

async function loginFromFrontend(page, report, options) {
  await page.getByRole("heading", { name: /登录进入获客工作台/ }).waitFor({ state: "visible", timeout: 30000 });
  await registerFromFrontend(page, report);
  await fillByLabel(page, "登录账号", options.username);
  await fillByLabel(page, "密码", "wrong-password");
  await clickButton(page, "登录", report, "auth.login.negative");
  await page.getByText("账号或密码错误", { exact: false }).waitFor({ state: "visible", timeout: 10000 });
  await fillByLabel(page, "登录账号", options.username);
  await fillByLabel(page, "密码", options.password);
  await clickButton(page, "登录", report, "auth.login.positive");
  await page.getByText("当前商户：", { exact: false }).waitFor({ state: "visible", timeout: 30000 });
  const authState = await page.evaluate(() => {
    const raw = window.localStorage.getItem("ai_acq_client_auth");
    return raw ? JSON.parse(raw) : null;
  });
  report.state.accessToken = authState?.accessToken || "";
  addCheck(report, "前端登录: 生成账号登录成功", report.state.accessToken ? "pass" : "fail", options.username);
}

async function createLead(page, report, iteration) {
  const suffix = `${iteration}-${Date.now().toString(36)}`;
  const panel = page.locator("article.panel").filter({ hasText: "新增商家线索" }).first();
  await fillByLabel(panel, "商家名称", `V15前端链路线索-${suffix}`);
  await fillByLabel(panel, "城市", "南昌");
  await fillByLabel(panel, "品类", "本地餐饮");
  await fillByLabel(panel, "联系人", "V15客户");
  await fillByLabel(panel, "电话", `TEST-V15-${suffix}`);
  await clickButton(panel, "保存线索", report, "leads.create");
  await page.getByText(`V15前端链路线索-${suffix}`, { exact: false }).waitFor({ state: "visible", timeout: 10000 });
  return `lead ${suffix}`;
}

async function createCollectorTask(page, report, iteration, shouldRun) {
  const suffix = `${iteration}-${Date.now().toString(36)}`;
  const panel = page.locator("article.panel").filter({ hasText: "新建采集任务" }).first();
  await fillByLabel(panel, "任务名称", `V15采集链路-${suffix}`);
  await fillByLabel(panel, "每组目标数", "1");
  await fillByLabel(panel, "城市", "南昌");
  await fillByLabel(panel, "品类", "餐饮");
  await fillByLabel(panel, "关键词", "团购");
  await clickButton(panel, "创建采集任务", report, "collector.create");
  await page.getByText("采集任务已创建", { exact: false }).waitFor({ state: "visible", timeout: 10000 });
  if (shouldRun) {
    const runButtons = page.getByRole("button", { name: /^运行$/ });
    if ((await runButtons.count()) > 0) {
      await runButtons.first().click();
      addCoverage(report, "collector.run.expected-gate");
      await delay(800);
    }
  }
  return `collector ${suffix}`;
}

async function createOutboundTask(page, report, iteration) {
  const suffix = `${iteration}-${Date.now().toString(36)}`;
  await clickButton(page, "任务列表", report, "outbound.tab.任务列表");
  const panel = page.locator("article.panel").filter({ hasText: "外呼任务操作表单" }).first();
  await fillByLabel(panel, "任务名称", `V15外呼链路-${suffix}`);
  await fillByLabel(panel, "并发数量", "1");
  await clickButton(panel, "创建外呼任务", report, "outbound.create");
  await page.getByText(`V15外呼链路-${suffix}`, { exact: false }).waitFor({ state: "visible", timeout: 10000 });
  return `outbound ${suffix}`;
}

async function exerciseDm(page, report, iteration) {
  if (iteration === 1) {
    await clickButton(page, "账号管理", report, "dm.tab.账号管理");
    const panel = page.locator("article.panel").filter({ hasText: "平台个人号管理" }).first();
    await fillByLabel(panel, "个人号名称", `V15美团个人号-${Date.now().toString(36)}`);
    await clickButton(panel, "保存账号", report, "dm.account.create");
    await delay(600);
  }
  if (iteration === 2) {
    await clickButton(page, "消息模板", report, "dm.tab.消息模板");
    const panel = page.locator("article.panel").filter({ hasText: "私信模板表单" }).first();
    await fillByLabel(panel, "模板名称", `V15模板-${Date.now().toString(36)}`);
    try {
      await fillByLabel(panel, "私信内容", "您好，看到您店铺适合做本地生活获客，方便进一步了解吗？");
    } catch {
      await panel.locator("textarea").first().fill("您好，看到您店铺适合做本地生活获客，方便进一步了解吗？");
    }
    await clickButton(panel, "保存模板", report, "dm.template.create");
    await delay(600);
  }
}

async function exerciseVoice(page, report, iteration) {
  if (iteration !== 1) return;
  await clickButton(page, "声音档案", report, "voice.tab.声音档案");
  const panel = page.locator("article.panel").filter({ hasText: "新增授权克隆档案" }).first();
  await fillByLabel(panel, "档案名称", `V15授权档案-${Date.now().toString(36)}`);
  await fillByLabel(panel, "授权人", "V15授权测试");
  await fillByLabel(panel, "授权材料 / 说明", "QA 创建档案，不上传真实声音样本，不调用外部复刻服务。");
  await clickButton(panel, "新增克隆档案", report, "voice.profile.create");
  await delay(700);
}

async function exerciseReports(page, report, iteration) {
  if (iteration % 4 !== 0) return;
  await clickButton(page, "导出中心", report, "reports.tab.导出中心");
  const createButtons = page.getByRole("button", { name: /创建导出|点击创建导出任务|导出经营总览|导出渠道报表|导出销售报表/ });
  if ((await createButtons.count()) > 0) {
    await createButtons.first().click();
    addCoverage(report, "reports.export.create");
    await delay(500);
  }
}

async function exerciseSettings(page, report, iteration) {
  if (iteration % 5 !== 0) return;
  await clickButton(page, "电话线路", report, "settings.tab.电话线路");
  const save = page.getByRole("button", { name: /保存设置|保存配置/ }).first();
  if ((await save.count()) > 0) {
    await save.click();
    addCoverage(report, "settings.save");
    await delay(500);
  }
}

async function navigateModule(page, report, moduleName) {
  await clickButton(page, moduleName, report, `module.${moduleName}`, 10000);
  await delay(220);
  for (const tab of tabMap[moduleName] || []) {
    await clickButton(page, tab, report, `${moduleName}.tab.${tab}`, 7000).catch((error) => {
      addCheck(report, `Tab click: ${moduleName}/${tab}`, "warn", error.message);
    });
  }
}

async function runIteration(page, report, iteration, artifactDir) {
  addCoverage(report, `iteration.${iteration}`);
  for (const moduleName of modules) {
    await safeStep(report, `第 ${iteration} 轮模块: ${moduleName}`, async () => {
      await navigateModule(page, report, moduleName);
      if (moduleName === "商家线索库") return createLead(page, report, iteration);
      if (moduleName === "线索采集") return createCollectorTask(page, report, iteration, iteration === 3);
      if (moduleName === "AI外呼系统" && iteration % 3 === 0) return createOutboundTask(page, report, iteration);
      if (moduleName === "平台私信系统") return exerciseDm(page, report, iteration);
      if (moduleName === "声音档案") return exerciseVoice(page, report, iteration);
      if (moduleName === "数据报表") return exerciseReports(page, report, iteration);
      if (moduleName === "系统设置") return exerciseSettings(page, report, iteration);
      return "visited";
    });
  }
  if (iteration === 1 || iteration % 5 === 0 || iteration === report.options.iterations) {
    await screenshot(page, report, artifactDir, `iteration-${String(iteration).padStart(2, "0")}`);
  }
}

function summarize(report) {
  const failures = report.checks.filter((check) => check.status === "fail").length;
  const warnings = report.checks.filter((check) => check.status === "warn").length;
  const unexpectedHttp = report.browser.httpFailures.filter((entry) => !expectedHttpFailures.some((pattern) => pattern.test(entry.url)));
  const score = Math.max(
    0,
    100 - failures * 10 - warnings * 3 - report.browser.consoleErrors.length * 5 - report.browser.pageErrors.length * 8 - unexpectedHttp.length * 8,
  );
  report.summary = {
    status: failures || report.browser.pageErrors.length || unexpectedHttp.length ? "fail" : score < 90 ? "warn" : "pass",
    score,
    iterations: report.options.iterations,
    checks: report.checks.length,
    failures,
    warnings,
    consoleErrors: report.browser.consoleErrors.length,
    pageErrors: report.browser.pageErrors.length,
    httpFailures: report.browser.httpFailures.length,
    unexpectedHttpFailures: unexpectedHttp.length,
    coverageKeys: Object.keys(report.coverage).length,
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.iterations < 20) throw new Error("V15 QA requires at least 20 iterations");

  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V15 Human-like QA Explore",
    generatedAt: new Date().toISOString(),
    options: { ...options, password: "<redacted>" },
    summary: null,
    checks: [],
    coverage: {},
    state: { accessToken: "" },
    browser: {
      consoleErrors: [],
      pageErrors: [],
      requestFailures: [],
      httpFailures: [],
    },
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      trace: path.join(artifactDir, "trace.zip"),
      screenshots: [],
    },
  };

  const userDataDir = path.join(artifactDir, "electron-user-data");
  const executable = await resolveDesktopExecutable(options.app);
  const cdpUrl = `http://127.0.0.1:${options.cdpPort}`;
  let child = null;
  let browser = null;

  try {
    child = spawn(executable, [`--remote-debugging-port=${options.cdpPort}`], {
      detached: true,
      stdio: "ignore",
      env: {
        ...process.env,
        AI_ACQ_DESKTOP_USER_DATA_DIR: userDataDir,
      },
    });
    child.unref();
    await waitForCdp(cdpUrl, 30000);
    browser = await chromium.connectOverCDP(cdpUrl);
    const page = await firstUsefulPage(browser);
    const context = page.context();
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });

    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) {
        const location = message.location();
        if (/\/api\/auth\/login\b/.test(location.url || "") && /401|Unauthorized/i.test(message.text())) return;
        report.browser.consoleErrors.push({ type: message.type(), text: message.text().slice(0, 800), location: message.location() });
      }
    });
    page.on("pageerror", (error) => {
      report.browser.pageErrors.push({ message: error.message, stack: error.stack });
    });
    page.on("requestfailed", (request) => {
      const url = request.url();
      if (/favicon|devtools/.test(url)) return;
      report.browser.requestFailures.push({ method: request.method(), url, failure: request.failure()?.errorText || "unknown" });
    });
    page.on("response", (response) => {
      const url = response.url();
      if (url.startsWith(options.api) && response.status() >= 400) {
        report.browser.httpFailures.push({ method: response.request().method(), url, status: response.status() });
      }
    });

    await page.bringToFront();
    await page.waitForLoadState("domcontentloaded", { timeout: 30000 }).catch(() => {});
    await page.evaluate(() => window.localStorage.clear()).catch(() => {});
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
    await screenshot(page, report, artifactDir, "00-login");
    await loginFromFrontend(page, report, options);
    await screenshot(page, report, artifactDir, "01-after-login");

    for (let iteration = 1; iteration <= options.iterations; iteration += 1) {
      await runIteration(page, report, iteration, artifactDir);
    }

    const [leads, collectionTasks, outboundTasks, exports] = await Promise.all([
      apiRequest(report, "/leads"),
      apiRequest(report, "/collections/tasks"),
      apiRequest(report, "/outbound/tasks"),
      apiRequest(report, "/reports/exports"),
    ]);
    addCheck(report, "API 对账: 前端操作写入数据", leads.ok && collectionTasks.ok && outboundTasks.ok && exports.ok ? "pass" : "fail", "read back core state after frontend run", {
      leads: Array.isArray(leads.body) ? leads.body.length : null,
      collectionTasks: Array.isArray(collectionTasks.body) ? collectionTasks.body.length : null,
      outboundTasks: Array.isArray(outboundTasks.body) ? outboundTasks.body.length : null,
      exports: Array.isArray(exports.body) ? exports.body.length : null,
    });

    await context.tracing.stop({ path: report.artifacts.trace }).catch(() => {});
  } catch (error) {
    addCheck(report, "V15 QA runner", "fail", error.stack || error.message);
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (child?.pid) {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {
        try {
          process.kill(child.pid, "SIGTERM");
        } catch {
          // Already closed.
        }
      }
    }
  }

  summarize(report);
  await writeJson(report.artifacts.report, report);
  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V15 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}`);
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
