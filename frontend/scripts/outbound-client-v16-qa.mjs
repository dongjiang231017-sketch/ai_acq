#!/usr/bin/env node
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");

const DEFAULT_URL = process.env.AI_ACQ_QA_URL || "http://127.0.0.1:4178/";
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";
const DEPLOYED_API = "http://101.132.63.159/ai-acq-api/api";
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v16-client-qa");

const tabs = ["外呼总览", "任务列表", "话术流程", "通话记录", "重拨规则", "实时监听"];

const tabExpectations = {
  外呼总览: ["真实线路接入", "实时语音管线", "实时通话"],
  任务列表: ["外呼任务操作表单", "外呼任务列表"],
  话术流程: ["话术流程"],
  通话记录: ["通话明细和转写"],
  重拨规则: ["重拨规则", "未接重拨", "忙线重拨"],
  实时监听: ["真实线路接入", "实时语音管线", "实时通话"],
};

const mutationDenyList = [
  /\/api\/outbound\/telephony\/test-call\b/,
  /\/api\/outbound\/telephony\/recover-line\b/,
  /\/api\/outbound\/tasks(?:\/|$)/,
  /\/api\/tasks(?:\/|$)/,
  /\/api\/leads(?:\/|$)/,
  /\/api\/collections\/tasks\/[^/]+\/run\b/,
  /\/api\/direct-messages\//,
  /\/api\/comment-intercepts\//,
];

function parseArgs(argv) {
  const options = {
    url: DEFAULT_URL,
    api: DEFAULT_API,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    json: false,
    headed: false,
    noTrace: false,
    allowLiveCall: false,
    phone: "",
    callerId: "",
    timeoutMs: 90000,
    cdp: "",
    desktopApp: "",
    cdpPort: 9225,
    apiExplicit: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--url" && next) {
      options.url = next;
      index += 1;
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      options.apiExplicit = true;
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
    } else if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--phone" && next) {
      options.phone = next;
      index += 1;
    } else if (arg === "--caller-id" && next) {
      options.callerId = next;
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Number(next);
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--no-trace") {
      options.noTrace = true;
    } else if (arg === "--allow-live-call") {
      options.allowLiveCall = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }

  if ((options.desktopApp || options.cdp) && !options.apiExplicit && options.api === DEFAULT_API) {
    options.api = DEPLOYED_API;
  }

  return options;
}

function printHelp() {
  console.log(`AI ACQ outbound client V16 QA

Usage:
  npm run qa:v16 -- --json
  npm run qa:v16 -- --url http://127.0.0.1:4178/ --api http://127.0.0.1:8017/api
  npm run qa:v16 -- --desktop-app /Applications/商家AI获客客户端.app --json

Safe by default:
  - Opens the client and navigates the outbound module.
  - Captures screenshots, trace, console, page errors, failed requests, and API evidence.
  - Blocks POST/PUT/PATCH/DELETE calls to outbound task, test-call, recovery, lead, DM, and collection mutation endpoints.
  - Does not click 单号试拨 unless --allow-live-call and --phone are both provided.
`);
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

async function launchBrowser(headed) {
  const launchOptions = {
    headless: !headed,
    args: ["--disable-blink-features=AutomationControlled"],
  };
  try {
    return await chromium.launch({ ...launchOptions, channel: "chrome" });
  } catch (channelError) {
    const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
    try {
      await fs.access(macChrome);
      return await chromium.launch({ ...launchOptions, executablePath: macChrome });
    } catch {
      try {
        return await chromium.launch(launchOptions);
      } catch (fallbackError) {
        fallbackError.message = `${fallbackError.message}\nChrome channel launch failed first: ${channelError.message}`;
        throw fallbackError;
      }
    }
  }
}

async function waitForCdp(cdpUrl, timeoutMs = 20000) {
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
  const child = spawn(executable, [`--remote-debugging-port=${options.cdpPort}`], {
    detached: true,
    stdio: "ignore",
  });
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
  throw new Error("No browser page found after connecting to CDP");
}

function addCheck(report, name, status, detail, data = undefined) {
  report.checks.push({ name, status, detail, data });
}

function statusRank(status) {
  if (status === "fail") return 3;
  if (status === "warn") return 2;
  return 1;
}

function summarizeStatus(report) {
  const max = report.checks.reduce((current, check) => Math.max(current, statusRank(check.status)), 1);
  const blockedMutations = report.browser.blockedMutations.length;
  const consoleErrors = report.browser.consoleMessages.filter((entry) => entry.type === "error").length;
  const pageErrors = report.browser.pageErrors.length;
  const failedRequests = report.browser.failedRequests.length;
  const score = Math.max(
    0,
    100 -
      report.checks.filter((check) => check.status === "fail").length * 18 -
      report.checks.filter((check) => check.status === "warn").length * 5 -
      blockedMutations * 20 -
      consoleErrors * 10 -
      pageErrors * 12 -
      failedRequests * 8 -
      Math.min(report.visual.totalIssues, 10) * 3,
  );

  report.summary = {
    status: max === 3 || blockedMutations > 0 || pageErrors > 0 ? "fail" : max === 2 || score < 90 ? "warn" : "pass",
    score,
    checks: report.checks.length,
    failures: report.checks.filter((check) => check.status === "fail").length,
    warnings: report.checks.filter((check) => check.status === "warn").length,
    blockedMutations,
    consoleErrors,
    pageErrors,
    failedRequests,
    visualIssues: report.visual.totalIssues,
  };
}

async function fetchJson(baseUrl, endpoint, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}${endpoint}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text.slice(0, 1000) };
    }
    return { ok: response.ok, status: response.status, body };
  } finally {
    clearTimeout(timeout);
  }
}

async function collectApiEvidence(report, options) {
  const endpoints = [
    { name: "health", path: "/health", required: true },
    { name: "modules", path: "/modules", required: true },
    { name: "outboundOverview", path: "/outbound/overview", required: true },
    { name: "telephonyConfig", path: "/outbound/telephony/config", required: true },
    { name: "telephonyHealth", path: "/outbound/telephony/health", required: true },
    { name: "telephonyPreflight", path: "/outbound/telephony/preflight", required: true },
    { name: "realtimePipeline", path: "/outbound/realtime/pipeline", required: true },
    { name: "realtimeLiveEvents", path: "/outbound/realtime/live-events?limit=20", required: false },
    { name: "callRecords", path: "/outbound/records", required: false },
    { name: "liveCalls", path: "/outbound/live", required: false },
    { name: "callScripts", path: "/outbound/scripts", required: true },
    { name: "recallRules", path: "/outbound/recall-rules", required: true },
  ];

  for (const endpoint of endpoints) {
    try {
      const result = await fetchJson(options.api, endpoint.path);
      report.api[endpoint.name] = result;
      addCheck(
        report,
        `API ${endpoint.name}`,
        result.ok ? "pass" : endpoint.required ? "fail" : "warn",
        `${endpoint.path} -> HTTP ${result.status}`,
      );
    } catch (error) {
      report.api[endpoint.name] = { ok: false, error: error.message };
      addCheck(report, `API ${endpoint.name}`, endpoint.required ? "fail" : "warn", error.message);
    }
  }

  const config = report.api.telephonyConfig?.body;
  const health = report.api.telephonyHealth?.body;
  const preflight = report.api.telephonyPreflight?.body;
  const pipeline = report.api.realtimePipeline?.body;

  if (config) {
    addCheck(
      report,
      "业务配置: 真实线路模式",
      config.gatewayMode === "asterisk" ? "pass" : "fail",
      `gatewayMode=${config.gatewayMode}`,
    );
    addCheck(
      report,
      "业务配置: 语音网关中继可读",
      /dinstar|uc100|goip|trunk|gateway/i.test(config.voiceGatewayProfile?.trunkName || config.asteriskTrunkName || "")
        ? "pass"
        : "warn",
      `trunk=${config.voiceGatewayProfile?.trunkName || config.asteriskTrunkName || "unknown"}`,
    );
    addCheck(
      report,
      "安全门控: 批量外呼关闭",
      config.asteriskBulkCallEnabled === false ? "pass" : "fail",
      `asteriskBulkCallEnabled=${config.asteriskBulkCallEnabled}`,
    );
    addCheck(
      report,
      "业务容量: 通道池可读",
      Number(config.voiceGatewayProfile?.maxChannels || config.asteriskMaxChannels || 0) >= 1 ? "pass" : "fail",
      `maxChannels=${config.voiceGatewayProfile?.maxChannels || config.asteriskMaxChannels}`,
    );
  }

  if (health) {
    addCheck(
      report,
      "线路健康: AMI 可诊断",
      health.amiReachable || health.authenticated ? "pass" : "warn",
      `amiReachable=${health.amiReachable}, authenticated=${health.authenticated}, trunkStatus=${health.trunkStatus}`,
    );
    addCheck(
      report,
      "业务验收: Trunk 已注册可达",
      health.trunkReachable === true ? "pass" : "warn",
      `trunkReachable=${health.trunkReachable}, trunkStatus=${health.trunkStatus}`,
    );
    addCheck(
      report,
      "业务验收: 单号试拨就绪",
      health.readyForTestCall === true ? "pass" : "warn",
      `readyForTestCall=${health.readyForTestCall}, errors=${(health.errors || []).join(" | ") || "none"}`,
    );
    addCheck(
      report,
      "线路健康: Trunk 状态不伪成功",
      health.trunkReachable === true || health.readyForTestCall === false ? "pass" : "warn",
      `readyForTestCall=${health.readyForTestCall}, trunkReachable=${health.trunkReachable}`,
    );
  }

  if (preflight) {
    addCheck(
      report,
      "预检: 有步骤和下一步",
      Array.isArray(preflight.steps) && preflight.steps.length > 0 && Boolean(preflight.nextStep) ? "pass" : "fail",
      preflight.nextStep || "missing nextStep",
      { stepCount: Array.isArray(preflight.steps) ? preflight.steps.length : 0 },
    );
    addCheck(
      report,
      "安全门控: 单号试拨与批量外呼分离",
      preflight.readyForBulkTasks === true ? "warn" : "pass",
      `readyForSingleNumberTest=${preflight.readyForSingleNumberTest}, readyForBulkTasks=${preflight.readyForBulkTasks}`,
    );
  }

  if (pipeline) {
    addCheck(
      report,
      "实时语音: 管线可观测",
      Array.isArray(pipeline.steps) && pipeline.steps.length > 0 ? "pass" : "fail",
      `mode=${pipeline.mode}, bridgeMode=${pipeline.bridgeMode}, readyForAsteriskMedia=${pipeline.readyForAsteriskMedia}`,
    );
    addCheck(
      report,
      "实时语音: 路由选项存在",
      Array.isArray(pipeline.routeOptions) && pipeline.routeOptions.some((route) => route.isActive) ? "pass" : "warn",
      (pipeline.routeOptions || []).map((route) => `${route.key}:${route.isActive ? "active" : "idle"}`).join(", "),
    );
    addCheck(
      report,
      "实时语音: Asterisk 媒体桥就绪",
      pipeline.readyForAsteriskMedia === true ? "pass" : "warn",
      `bridgeMode=${pipeline.bridgeMode}, readyForAsteriskMedia=${pipeline.readyForAsteriskMedia}, nextStep=${pipeline.nextStep}`,
    );
  }
}

async function assertText(page, report, text, statusIfMissing = "fail") {
  const count = await page.getByText(text, { exact: false }).count();
  addCheck(report, `UI 文案: ${text}`, count > 0 ? "pass" : statusIfMissing, count > 0 ? "visible" : "missing");
}

async function safeClickButton(page, name, timeout = 6000) {
  const button = page.getByRole("button", { name: new RegExp(escapeRegExp(name)) }).first();
  await button.waitFor({ state: "visible", timeout });
  await button.click({ timeout });
}

async function safeClickOutboundTab(page, name, timeout = 6000) {
  const tabsRegion = page.locator("section.outbound-tabs, [aria-label='外呼模块页面']").first();
  await tabsRegion.waitFor({ state: "visible", timeout });
  const button = tabsRegion.getByRole("button", { name: new RegExp(`^${escapeRegExp(name)}$`) }).first();
  await button.waitFor({ state: "visible", timeout });
  await button.click({ timeout });
}

async function captureScreenshot(page, report, artifactDir, name) {
  const file = path.join(artifactDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  report.artifacts.screenshots.push(file);
  return file;
}

async function collectInteractiveSnapshot(page) {
  return page.evaluate(() => {
    function visible(element) {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 1 && rect.height > 1 && style.visibility !== "hidden" && style.display !== "none";
    }

    return Array.from(document.querySelectorAll("button, input, textarea, select, a, [role='button']"))
      .filter(visible)
      .slice(0, 160)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        role: element.getAttribute("role") || "",
        type: element.getAttribute("type") || "",
        text: (element.innerText || element.getAttribute("aria-label") || element.getAttribute("placeholder") || "").trim().slice(0, 120),
        disabled: Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true",
      }));
  });
}

async function collectVisualIssues(page) {
  return page.evaluate(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight;

    function visible(element) {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 1 && rect.height > 1 && style.visibility !== "hidden" && style.display !== "none";
    }

    function elementText(element) {
      return (element.innerText || element.getAttribute("aria-label") || element.getAttribute("placeholder") || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 140);
    }

    const clipped = [];
    const clipSelector = "button, input, textarea, select, h1, h2, h3, p, span, strong, small, label, td, th";
    for (const element of Array.from(document.querySelectorAll(clipSelector))) {
      if (!visible(element)) continue;
      if (element.closest(".outbound-tabs")) continue;
      if (element.closest(".table-wrap")) continue;
      const style = window.getComputedStyle(element);
      if (style.textOverflow === "ellipsis") continue;
      const text = elementText(element);
      if (text.length < 2) continue;
      const rect = element.getBoundingClientRect();
      const overflowX = element.scrollWidth > element.clientWidth + 3 && rect.width < viewportWidth * 0.96;
      const overflowY = element.scrollHeight > element.clientHeight + 3 && rect.height < viewportHeight * 0.96;
      if (overflowX || overflowY) {
        clipped.push({
          text,
          tag: element.tagName.toLowerCase(),
          className: String(element.className || "").slice(0, 120),
          overflowX,
          overflowY,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight,
        });
      }
    }

    const overflow = [];
    for (const element of Array.from(document.querySelectorAll("body *"))) {
      if (!visible(element)) continue;
      if (element.closest(".outbound-tabs")) continue;
      if (element.closest(".table-wrap")) continue;
      const rect = element.getBoundingClientRect();
      if (rect.right > viewportWidth + 4 || rect.left < -4) {
        overflow.push({
          text: elementText(element),
          tag: element.tagName.toLowerCase(),
          className: String(element.className || "").slice(0, 120),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          viewportWidth,
        });
      }
    }

    return {
      viewport: { width: viewportWidth, height: viewportHeight },
      clipped: clipped.slice(0, 25),
      overflow: overflow.slice(0, 25),
    };
  });
}

async function runBrowserQa(report, options, artifactDir) {
  let launchedDesktop = null;
  if (options.desktopApp) {
    launchedDesktop = await launchDesktopApp(options, report);
    options.cdp = launchedDesktop.cdpUrl;
  }

  const browser = options.cdp ? await chromium.connectOverCDP(options.cdp) : await launchBrowser(options.headed);
  report.browser.launch = options.cdp ? `cdp:${options.cdp}` : options.headed ? "headed" : "headless";

  try {
    const context = options.cdp
      ? browser.contexts()[0]
      : await browser.newContext({
          viewport: { width: 1440, height: 1100 },
          locale: "zh-CN",
          timezoneId: "Asia/Shanghai",
        });
    if (!context) throw new Error("No browser context available");
    const page = options.cdp ? await firstUsefulPage(browser) : await context.newPage();
    await page.setViewportSize({ width: 1440, height: 1100 }).catch(() => {});
    let traceStarted = false;
    const finishTrace = async () => {
      if (!traceStarted || options.noTrace || report.artifacts.trace) return;
      const tracePath = path.join(artifactDir, "trace.zip");
      await context.tracing.stop({ path: tracePath });
      report.artifacts.trace = tracePath;
      traceStarted = false;
    };

    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) {
        report.browser.consoleMessages.push({
          type: message.type(),
          text: message.text().slice(0, 1000),
          location: message.location(),
        });
      }
    });
    page.on("pageerror", (error) => {
      report.browser.pageErrors.push({ message: error.message, stack: error.stack });
    });
    page.on("requestfailed", (request) => {
      const failure = request.failure();
      const url = request.url();
      if (/favicon|sockjs-node|hmr|__vite_ping/.test(url)) return;
      report.browser.failedRequests.push({
        method: request.method(),
        url,
        failure: failure?.errorText || "unknown",
      });
    });

    await page.route("**/*", async (route) => {
      const request = route.request();
      const method = request.method().toUpperCase();
      const url = request.url();
      const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
      const isDenied = isMutation && mutationDenyList.some((pattern) => pattern.test(url));
      const isAllowedLiveCall =
        options.allowLiveCall && method === "POST" && /\/api\/outbound\/telephony\/test-call\b/.test(url);
      if (isDenied && !isAllowedLiveCall) {
        report.browser.blockedMutations.push({ method, url });
        await route.abort("blockedbyclient");
        return;
      }
      await route.continue();
    });

    if (!options.noTrace) {
      await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
      traceStarted = true;
    }

    if (!options.cdp) {
      await page.goto(options.url, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    }
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await assertText(page, report, "商家AI获客", "fail");

    const outboundButton = page.getByRole("button", { name: /AI外呼系统/ }).first();
    const outboundVisible = await outboundButton.isVisible({ timeout: 3000 }).catch(() => false);
    if (!outboundVisible) {
      const bodyText = await page.locator("body").innerText({ timeout: 3000 }).catch(() => "");
      report.browser.interactiveBefore = await collectInteractiveSnapshot(page).catch(() => []);
      await captureScreenshot(page, report, artifactDir, "auth-gate-or-unexpected-entry");
      report.visual.desktop = await collectVisualIssues(page).catch(() => ({ clipped: [], overflow: [] }));
      report.visual.mobile = { clipped: [], overflow: [] };
      report.visual.totalIssues = report.visual.desktop.clipped.length + report.visual.desktop.overflow.length;
      addCheck(
        report,
        "入口状态: 外呼工作台可进入",
        /客户账号登录|登录进入获客工作台|申请开通/.test(bodyText) ? "warn" : "fail",
        /客户账号登录|登录进入获客工作台|申请开通/.test(bodyText)
          ? "target is at customer login/auth gate; provide credentials/session or use installed desktop app mode for the current validated client"
          : `AI外呼系统 entry not found. Visible text: ${bodyText.slice(0, 500)}`,
      );
      addCheck(
        report,
        "视觉检查: 入口页无明显裁切溢出",
        report.visual.totalIssues === 0 ? "pass" : report.visual.totalIssues <= 8 ? "warn" : "fail",
        `visualIssues=${report.visual.totalIssues}`,
      );
      await finishTrace();
      if (!options.cdp) await context.close();
      return;
    }
    await outboundButton.waitFor({ state: "visible", timeout: 10000 });
    await outboundButton.click();
    await page.getByRole("heading", { name: /AI外呼系统/ }).waitFor({ state: "visible", timeout: 10000 });
    await captureScreenshot(page, report, artifactDir, "01-outbound-entry");

    for (const text of ["在线坐席", "进行中通话", "需接管", "异常静默", "真实线路接入", "客户交付状态", "预检结论", "单号试拨"]) {
      await assertText(page, report, text, "fail");
    }

    report.browser.interactiveBefore = await collectInteractiveSnapshot(page);
    const dangerousLabels = ["单号试拨", "恢复线路", "新建任务", "启动任务"];
    report.browser.dangerousControls = report.browser.interactiveBefore.filter((control) =>
      dangerousLabels.some((label) => control.text.includes(label)),
    );
    addCheck(
      report,
      "安全门控: 危险控件识别",
      report.browser.dangerousControls.length > 0 ? "pass" : "warn",
      `found=${report.browser.dangerousControls.map((control) => control.text).join(" | ") || "none"}`,
    );

    await safeClickButton(page, "预检线路");
    await page.waitForTimeout(1200);
    await captureScreenshot(page, report, artifactDir, "02-after-preflight-refresh");

    const searchBox = page.getByPlaceholder(/搜索商家|任务|客户/).first();
    if ((await searchBox.count()) > 0) {
      await searchBox.fill("南昌");
      await page.waitForTimeout(300);
      await searchBox.fill("");
      addCheck(report, "UI 交互: 顶部搜索可输入和清空", "pass", "search input accepted safe text");
    } else {
      addCheck(report, "UI 交互: 顶部搜索可输入和清空", "warn", "search input not found");
    }

    for (const tab of tabs) {
      await safeClickOutboundTab(page, tab);
      await page.waitForTimeout(700);
      await captureScreenshot(page, report, artifactDir, `tab-${tabs.indexOf(tab) + 1}-${tab}`);
      for (const expected of tabExpectations[tab]) {
        await assertText(page, report, expected, tab === "外呼总览" ? "fail" : "warn");
      }
    }

    if (options.allowLiveCall) {
      if (!options.phone.trim()) {
        addCheck(report, "真实单号试拨门控", "fail", "--allow-live-call requires --phone");
      } else {
        await safeClickButton(page, "实时监听");
        await page.getByPlaceholder("输入自己的手机号").fill(options.phone.trim());
        if (options.callerId.trim()) {
          await page.getByPlaceholder("默认 AI获客").fill(options.callerId.trim());
        }
        await safeClickButton(page, "单号试拨");
        await page.waitForTimeout(3000);
        await captureScreenshot(page, report, artifactDir, "live-call-result");
        addCheck(report, "真实单号试拨门控", "warn", "live call was explicitly allowed and clicked");
      }
    } else {
      addCheck(report, "真实单号试拨门控", "pass", "not clicked; requires --allow-live-call --phone");
    }

    report.visual.desktop = await collectVisualIssues(page);
    await page.setViewportSize({ width: 390, height: 900 });
    await page.waitForTimeout(700);
    await captureScreenshot(page, report, artifactDir, "mobile-outbound-realtime");
    report.visual.mobile = await collectVisualIssues(page);
    report.visual.totalIssues =
      report.visual.desktop.clipped.length +
      report.visual.desktop.overflow.length +
      report.visual.mobile.clipped.length +
      report.visual.mobile.overflow.length;
    addCheck(
      report,
      "视觉检查: 桌面/移动端无明显裁切溢出",
      report.visual.totalIssues === 0 ? "pass" : report.visual.totalIssues <= 8 ? "warn" : "fail",
      `visualIssues=${report.visual.totalIssues}`,
    );

    if (!options.noTrace) {
      await finishTrace();
    }

    if (!options.cdp) await context.close();
  } finally {
    await browser.close();
    if (launchedDesktop?.child?.pid) {
      try {
        process.kill(launchedDesktop.child.pid);
      } catch {
        // The app may have already exited or handed off to an existing instance.
      }
    }
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const report = {
    version: "V16",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      url: options.url,
      api: options.api,
      mode: options.desktopApp ? "desktop-app" : options.cdp ? "cdp" : "browser",
      cdp: options.cdp || null,
      desktopApp: options.desktopApp || null,
      allowLiveCall: options.allowLiveCall,
      liveCallPhoneProvided: Boolean(options.phone.trim()),
    },
    summary: null,
    checks: [],
    api: {},
    browser: {
      launch: "",
      consoleMessages: [],
      pageErrors: [],
      failedRequests: [],
      blockedMutations: [],
      dangerousControls: [],
      interactiveBefore: [],
    },
    visual: {
      desktop: { clipped: [], overflow: [] },
      mobile: { clipped: [], overflow: [] },
      totalIssues: 0,
    },
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      screenshots: [],
      trace: null,
    },
  };

  try {
    await collectApiEvidence(report, options);
    await runBrowserQa(report, options, artifactDir);
  } catch (error) {
    addCheck(report, "V16 QA runner", "fail", error.stack || error.message);
  }

  summarizeStatus(report);
  await writeJson(report.artifacts.report, report);

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V16 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}`);
    console.log(`Report: ${report.artifacts.report}`);
    if (report.artifacts.trace) console.log(`Trace: ${report.artifacts.trace}`);
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
