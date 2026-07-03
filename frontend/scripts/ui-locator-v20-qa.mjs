#!/usr/bin/env node
import { chromium } from "playwright";
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v20-locator-healing-qa");
const DEFAULT_URL = process.env.AI_ACQ_QA_URL || "http://127.0.0.1:4178/";

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--url", "--timeout-ms", "--mode"]);
const ownFlags = new Set(["--json", "--batch", "--live", "--skip-v19", "--app-scan", "--headed", "--no-trace", "--help", "-h"]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    url: DEFAULT_URL,
    timeoutMs: 90000,
    json: false,
    batch: false,
    live: false,
    skipV19: false,
    appScan: false,
    headed: false,
    noTrace: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 1000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--url") options.url = next;
      if (arg === "--timeout-ms") options.timeoutMs = Math.max(10000, Number(next) || 90000);
      if (arg === "--mode") options.live = next === "live";
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--live") {
      options.live = true;
    } else if (arg === "--skip-v19") {
      options.skipV19 = true;
    } else if (arg === "--app-scan") {
      options.appScan = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--no-trace") {
      options.noTrace = true;
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
  console.log(`AI ACQ V20 UI locator healing QA

Default: run deterministic locator-healing contract, then V19 continuous real-flow diagnosis.
  npm run qa:v20 -- --repeat 2

Batch readiness:
  npm run qa:v20:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1

Only test locator healing:
  npm run qa:v20 -- --skip-v19

Optional non-mutating scan of a running app:
  npm run qa:v20 -- --app-scan --url http://127.0.0.1:4178/
`);
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

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
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

function runV19(options, artifactDir) {
  const args = [
    "scripts/self-healing-v19-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--artifact-root",
    path.join(artifactDir, "v19"),
  ];
  if (options.batch) args.push("--batch");
  if (options.live) args.push("--live");
  if (options.url) args.push("--url", options.url);
  if (options.timeoutMs) args.push("--timeout-ms", String(options.timeoutMs));
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 40 * 1024 * 1024,
    timeout: 12 * 60 * 1000,
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
    exitCode: result.status,
    signal: result.signal,
    parseError,
    report,
    stderrTail: String(result.stderr || "").slice(-4000),
    stdoutTail: report ? "" : String(result.stdout || "").slice(-4000),
  };
}

function roleFromElement(element) {
  const explicit = element.getAttribute("role");
  if (explicit) return explicit.toLowerCase();
  const tag = element.tagName.toLowerCase();
  if (tag === "button") return "button";
  if (tag === "a") return "link";
  if (tag === "select") return "combobox";
  if (tag === "textarea") return "textbox";
  if (tag === "input") {
    const type = (element.getAttribute("type") || "text").toLowerCase();
    if (["button", "submit", "reset"].includes(type)) return "button";
    if (["checkbox", "radio", "slider"].includes(type)) return type;
    return "textbox";
  }
  return "";
}

async function collectCandidates(page) {
  return page.evaluate(() => {
    const quote = (value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const roleFor = (element) => {
      const explicit = element.getAttribute("role");
      if (explicit) return explicit.toLowerCase();
      const tag = element.tagName.toLowerCase();
      if (tag === "button") return "button";
      if (tag === "a") return "link";
      if (tag === "select") return "combobox";
      if (tag === "textarea") return "textbox";
      if (tag === "input") {
        const type = (element.getAttribute("type") || "text").toLowerCase();
        if (["button", "submit", "reset"].includes(type)) return "button";
        if (["checkbox", "radio", "range"].includes(type)) return type === "range" ? "slider" : type;
        return "textbox";
      }
      return "";
    };
    const labelFor = (element) => {
      if (element.labels?.length) return Array.from(element.labels).map((item) => item.innerText || item.textContent || "").join(" ").trim();
      const id = element.getAttribute("id");
      if (id) {
        const label = document.querySelector(`label[for="${quote(id)}"]`);
        if (label) return (label.innerText || label.textContent || "").trim();
      }
      const wrapper = element.closest("label");
      return wrapper ? (wrapper.innerText || wrapper.textContent || "").trim() : "";
    };
    const selectorFor = (element) => {
      const tag = element.tagName.toLowerCase();
      const testId = element.getAttribute("data-testid");
      if (testId) return `[data-testid="${quote(testId)}"]`;
      const id = element.getAttribute("id");
      if (id) return `#${CSS.escape(id)}`;
      const aria = element.getAttribute("aria-label");
      if (aria) return `${tag}[aria-label="${quote(aria)}"]`;
      const name = element.getAttribute("name");
      if (name) return `${tag}[name="${quote(name)}"]`;
      const placeholder = element.getAttribute("placeholder");
      if (placeholder) return `${tag}[placeholder="${quote(placeholder)}"]`;
      const parts = [];
      let current = element;
      while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
        const currentTag = current.tagName.toLowerCase();
        const siblings = Array.from(current.parentElement?.children || []).filter((item) => item.tagName === current.tagName);
        const index = siblings.indexOf(current) + 1;
        parts.unshift(`${currentTag}:nth-of-type(${Math.max(1, index)})`);
        current = current.parentElement;
      }
      return `body > ${parts.join(" > ")}`;
    };
    const interactive = Array.from(document.querySelectorAll("button, input, textarea, select, a, [role='button'], [role='textbox'], [role='tab']"));
    return interactive.map((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      const visible = rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      const disabled = Boolean(element.disabled || element.getAttribute("aria-disabled") === "true");
      const text = (element.innerText || element.value || element.textContent || "").trim().replace(/\s+/g, " ");
      const ariaLabel = element.getAttribute("aria-label") || "";
      const placeholder = element.getAttribute("placeholder") || "";
      const testId = element.getAttribute("data-testid") || "";
      const name = element.getAttribute("name") || "";
      const label = labelFor(element);
      return {
        selector: selectorFor(element),
        tag: element.tagName.toLowerCase(),
        type: element.getAttribute("type") || "",
        role: roleFor(element),
        text: text.slice(0, 160),
        ariaLabel: ariaLabel.slice(0, 160),
        label: label.slice(0, 160),
        placeholder: placeholder.slice(0, 160),
        testId: testId.slice(0, 160),
        name: name.slice(0, 160),
        visible,
        disabled,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      };
    });
  });
}

function scoreCandidate(intent, candidate) {
  if (!candidate.visible || candidate.disabled) return { score: 0, reasons: ["not_visible_or_disabled"] };
  const reasons = [];
  let score = 0;
  const haystacks = [
    candidate.text,
    candidate.ariaLabel,
    candidate.label,
    candidate.placeholder,
    candidate.testId,
    candidate.name,
  ].filter(Boolean).map((value) => value.toLowerCase());
  const names = (intent.names || []).map((value) => String(value).toLowerCase());

  if (intent.role && candidate.role === intent.role) {
    score += 35;
    reasons.push("role");
  }
  for (const name of names) {
    if (haystacks.some((item) => item === name)) {
      score += 40;
      reasons.push(`exact:${name}`);
      break;
    }
    if (haystacks.some((item) => item.includes(name) || name.includes(item))) {
      score += 28;
      reasons.push(`partial:${name}`);
      break;
    }
  }
  for (const token of intent.tokens || []) {
    const lower = String(token).toLowerCase();
    if (haystacks.some((item) => item.includes(lower))) {
      score += 8;
      reasons.push(`token:${lower}`);
    }
  }
  if (intent.tag && candidate.tag === intent.tag) {
    score += 8;
    reasons.push("tag");
  }
  if (intent.type && candidate.type === intent.type) {
    score += 8;
    reasons.push("type");
  }

  return { score, reasons };
}

async function tryVisible(locator, timeout = 800) {
  try {
    await locator.first().waitFor({ state: "visible", timeout });
    return true;
  } catch {
    return false;
  }
}

async function locateByStrategy(page, intent) {
  const attempts = [];
  if (intent.primary) {
    const locator = page.locator(intent.primary).first();
    const ok = await tryVisible(locator);
    attempts.push({ strategy: "primary", selector: intent.primary, ok });
    if (ok) return { locator, strategy: "primary", attempts, healed: false };
  }

  if (intent.role) {
    for (const name of intent.names || []) {
      const locator = page.getByRole(intent.role, { name: new RegExp(escapeRegExp(name), "i") }).first();
      const ok = await tryVisible(locator);
      attempts.push({ strategy: "role", role: intent.role, name, ok });
      if (ok) return { locator, strategy: "role", attempts, healed: true, detail: { name } };
    }
  }

  for (const name of intent.names || []) {
    const label = page.getByLabel(new RegExp(escapeRegExp(name), "i")).first();
    const labelOk = await tryVisible(label);
    attempts.push({ strategy: "label", name, ok: labelOk });
    if (labelOk) return { locator: label, strategy: "label", attempts, healed: true, detail: { name } };

    const placeholder = page.getByPlaceholder(new RegExp(escapeRegExp(name), "i")).first();
    const placeholderOk = await tryVisible(placeholder);
    attempts.push({ strategy: "placeholder", name, ok: placeholderOk });
    if (placeholderOk) return { locator: placeholder, strategy: "placeholder", attempts, healed: true, detail: { name } };

    const text = page.getByText(new RegExp(escapeRegExp(name), "i")).first();
    const textOk = await tryVisible(text);
    attempts.push({ strategy: "text", name, ok: textOk });
    if (textOk && intent.role !== "textbox") return { locator: text, strategy: "text", attempts, healed: true, detail: { name } };
  }

  const candidates = await collectCandidates(page);
  const ranked = candidates
    .map((candidate) => ({ candidate, ...scoreCandidate(intent, candidate) }))
    .sort((a, b) => b.score - a.score);
  const selected = ranked[0];
  const minimum = intent.minimumScore ?? 45;
  attempts.push({
    strategy: "dom_fingerprint",
    ok: Boolean(selected && selected.score >= minimum),
    minimum,
    selected: selected
      ? { selector: selected.candidate.selector, score: selected.score, reasons: selected.reasons, text: selected.candidate.text, label: selected.candidate.label }
      : null,
    topCandidates: ranked.slice(0, 5).map((item) => ({
      selector: item.candidate.selector,
      score: item.score,
      reasons: item.reasons,
      role: item.candidate.role,
      text: item.candidate.text,
      label: item.candidate.label,
      ariaLabel: item.candidate.ariaLabel,
      placeholder: item.candidate.placeholder,
    })),
  });

  if (selected && selected.score >= minimum) {
    return {
      locator: page.locator(selected.candidate.selector).first(),
      strategy: "dom_fingerprint",
      attempts,
      healed: true,
      detail: {
        selector: selected.candidate.selector,
        score: selected.score,
        confidence: Math.min(0.99, selected.score / 100),
        reasons: selected.reasons,
      },
    };
  }

  return { locator: null, strategy: "missing", attempts, healed: false };
}

async function healAndAct(page, report, intent, action) {
  const startedAt = new Date().toISOString();
  const result = await locateByStrategy(page, intent);
  const event = {
    id: intent.id,
    description: intent.description,
    action: action.type,
    startedAt,
    strategy: result.strategy,
    healed: result.healed,
    detail: result.detail || null,
    attempts: result.attempts,
    status: result.locator ? "pass" : "fail",
  };
  const healing = report.healing || report;
  healing.events.push(event);
  if (!result.locator) throw new Error(`V20 locator healing failed for ${intent.id}`);

  if (action.type === "fill") {
    await result.locator.fill(action.value);
  } else if (action.type === "click") {
    await result.locator.click();
  } else if (action.type === "select") {
    await result.locator.selectOption(action.value);
  }
  return event;
}

async function screenshot(page, report, artifactDir, name) {
  const file = path.join(artifactDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  const artifacts = report.healing?.artifacts || report.artifacts;
  artifacts.screenshots.push(file);
}

async function pathExists(file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

async function launchBrowser(options) {
  const launchOptions = { headless: !options.headed };
  try {
    return { browser: await chromium.launch(launchOptions), launcher: "playwright-chromium" };
  } catch (error) {
    const firstError = error;
    try {
      return { browser: await chromium.launch({ ...launchOptions, channel: "chrome" }), launcher: "system-chrome-channel" };
    } catch {
      const candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
      ];
      for (const executablePath of candidates) {
        if (await pathExists(executablePath)) {
          return {
            browser: await chromium.launch({ ...launchOptions, executablePath }),
            launcher: `system-executable:${executablePath}`,
          };
        }
      }
      throw firstError;
    }
  }
}

function selfTestHtml() {
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>AI ACQ V20 Locator Healing Contract</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #172033; }
      main { max-width: 820px; display: grid; gap: 18px; }
      label { display: grid; gap: 6px; font-weight: 700; }
      input { font-size: 16px; padding: 10px 12px; border: 1px solid #b7c3d5; border-radius: 8px; }
      button { font-size: 15px; padding: 10px 14px; border: 1px solid #7da8f7; border-radius: 8px; background: #edf4ff; color: #17325d; cursor: pointer; }
      nav, section { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .status { padding: 12px; border-left: 4px solid #2f7cf6; background: #f6f9ff; }
    </style>
  </head>
  <body>
    <main>
      <h1>商家AI获客客户端测试壳</h1>
      <form aria-label="客户登录表单">
        <label>客户账号
          <input name="client_account" autocomplete="username" placeholder="请输入客户账号" data-testid="login-account-field" />
        </label>
        <label>登录密码
          <input aria-label="密码" type="password" autocomplete="current-password" data-testid="login-password-field" />
        </label>
        <button type="button" aria-label="进入工作台" data-testid="login-submit">登录</button>
      </form>
      <nav aria-label="功能模块">
        <button type="button" data-testid="nav-outbound" aria-label="AI外呼系统">外呼工作台</button>
        <button type="button" data-testid="nav-leads" aria-label="商家线索库">线索库</button>
      </nav>
      <section aria-label="外呼模块页面">
        <button type="button" role="tab" aria-label="实时监听">监听面板</button>
        <button type="button" role="tab" aria-label="任务列表">任务</button>
      </section>
      <div class="status" role="status">等待测试动作</div>
    </main>
    <script>
      const status = document.querySelector('[role="status"]');
      document.querySelector('[data-testid="login-submit"]').addEventListener('click', () => {
        status.textContent = '已登录，后端已连接';
      });
      document.querySelector('[data-testid="nav-outbound"]').addEventListener('click', () => {
        status.textContent = 'AI外呼系统已打开';
      });
      document.querySelector('[aria-label="实时监听"]').addEventListener('click', () => {
        status.textContent = '真实线路接入 · 实时语音管线 · 实时通话';
      });
    </script>
  </body>
</html>`;
}

async function runHealingContract(options, artifactDir) {
  const report = {
    status: "fail",
    events: [],
    appScan: null,
    artifacts: {
      trace: null,
      screenshots: [],
      candidates: path.join(artifactDir, "candidates.json"),
    },
    summary: null,
  };
  const launched = await launchBrowser(options);
  const browser = launched.browser;
  report.artifacts.browserLauncher = launched.launcher;
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  let traceStarted = false;
  try {
    if (!options.noTrace) {
      await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
      traceStarted = true;
    }
    await page.setContent(selfTestHtml(), { waitUntil: "domcontentloaded" });
    await screenshot(page, report, artifactDir, "01-contract-start");
    const intents = [
      {
        id: "login.account",
        description: "Fill client account even if the old selector is gone",
        primary: "[data-old-login-account='true']",
        role: "textbox",
        tag: "input",
        names: ["登录账号", "客户账号", "请输入客户账号"],
        tokens: ["account", "client", "账号"],
      },
      {
        id: "login.password",
        description: "Fill password even if the old selector is gone",
        primary: "[data-old-password='true']",
        role: "textbox",
        tag: "input",
        type: "password",
        names: ["密码", "登录密码"],
        tokens: ["password", "密码"],
      },
      {
        id: "login.submit",
        description: "Click login through role/name fallback",
        primary: "button.old-login-submit",
        role: "button",
        names: ["登录", "进入工作台"],
        tokens: ["login", "submit"],
      },
      {
        id: "nav.outbound",
        description: "Open outbound module through aria/test id fallback",
        primary: "[data-old-nav='outbound']",
        role: "button",
        names: ["AI外呼系统", "外呼工作台", "外呼"],
        tokens: ["outbound", "外呼"],
      },
      {
        id: "tab.realtime",
        description: "Open realtime monitor through tab semantics",
        primary: "section.outbound-tabs button:nth-child(99)",
        role: "tab",
        names: ["实时监听", "监听面板"],
        tokens: ["realtime", "监听"],
      },
    ];
    await healAndAct(page, report, intents[0], { type: "fill", value: "v20_client" });
    await healAndAct(page, report, intents[1], { type: "fill", value: "not-a-real-secret" });
    await healAndAct(page, report, intents[2], { type: "click" });
    await page.getByText("已登录", { exact: false }).waitFor({ state: "visible", timeout: 3000 });
    await healAndAct(page, report, intents[3], { type: "click" });
    await page.getByText("AI外呼系统已打开", { exact: false }).waitFor({ state: "visible", timeout: 3000 });
    await healAndAct(page, report, intents[4], { type: "click" });
    await page.getByText("真实线路接入", { exact: false }).waitFor({ state: "visible", timeout: 3000 });
    await screenshot(page, report, artifactDir, "02-contract-finished");
    await writeJson(report.artifacts.candidates, await collectCandidates(page));

    if (options.appScan) {
      report.appScan = await runAppScan(page, report, options, artifactDir);
    }

    report.status = report.events.every((event) => event.status === "pass") ? "pass" : "fail";
  } finally {
    if (traceStarted) {
      const tracePath = path.join(artifactDir, "trace.zip");
      await context.tracing.stop({ path: tracePath }).catch(() => {});
      report.artifacts.trace = tracePath;
    }
    await browser.close().catch(() => {});
  }
  const healedEvents = report.events.filter((event) => event.healed).length;
  report.summary = {
    status: report.status,
    events: report.events.length,
    healedEvents,
    primarySelectorMisses: report.events.filter((event) => event.attempts.some((attempt) => attempt.strategy === "primary" && !attempt.ok)).length,
    strategiesUsed: Array.from(new Set(report.events.map((event) => event.strategy))).sort(),
    trace: report.artifacts.trace,
    screenshots: report.artifacts.screenshots.length,
  };
  return report;
}

async function runAppScan(page, healingReport, options, artifactDir) {
  const scan = {
    url: options.url,
    status: "warn",
    error: null,
    interactiveCount: 0,
    outboundNavigation: null,
    screenshot: null,
  };
  try {
    await page.goto(options.url, { waitUntil: "domcontentloaded", timeout: options.timeoutMs });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    await screenshot(page, healingReport, artifactDir, "03-app-scan-entry");
    scan.screenshot = healingReport.artifacts.screenshots.at(-1);
    const candidates = await collectCandidates(page);
    scan.interactiveCount = candidates.filter((candidate) => candidate.visible).length;
    const result = await locateByStrategy(page, {
      id: "app.nav.outbound",
      primary: "[data-old-nav='outbound']",
      role: "button",
      names: ["AI外呼系统", "外呼工作台", "外呼"],
      tokens: ["外呼", "outbound"],
      minimumScore: 50,
    });
    scan.outboundNavigation = {
      strategy: result.strategy,
      healed: result.healed,
      found: Boolean(result.locator),
      attempts: result.attempts,
    };
    scan.status = result.locator ? "pass" : "warn";
  } catch (error) {
    scan.status = "warn";
    scan.error = error.message;
  }
  return scan;
}

function summarizeTop(report) {
  const healingStatus = report.healing?.summary?.status || "fail";
  const v19Status = report.v19?.summary?.status || (report.v19 ? "fail" : "skipped");
  const fail = healingStatus === "fail" || v19Status === "fail";
  const warn = !fail && (v19Status === "warn" || report.healing?.appScan?.status === "warn");
  report.summary = {
    status: fail ? "fail" : warn ? "warn" : "pass",
    healingStatus,
    v19Status,
    v19Score: report.v19?.summary?.latestV18Score ?? null,
    healedEvents: report.healing?.summary?.healedEvents ?? 0,
    persistentBlockers: report.v19?.summary?.persistentBlockers || [],
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V20",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      live: options.live,
      appScan: options.appScan,
      skipV19: options.skipV19,
      url: options.url,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Prefer user-facing locators and auto-waiting first; repair locators through accessibility and DOM evidence before broad retries.",
      "Keep trace, screenshot, and candidate fingerprints so a repaired UI step remains inspectable.",
      "Do not use locator healing to mask product failures; V19/V18 business evidence still decides workflow readiness.",
    ],
    healing: null,
    v19Execution: null,
    v19: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
    },
  };

  report.healing = await runHealingContract(options, artifactDir);

  if (!options.skipV19) {
    report.v19Execution = runV19(options, artifactDir);
    report.v19 = report.v19Execution.report
      ? {
          summary: report.v19Execution.report.summary,
          target: report.v19Execution.report.target,
          artifacts: report.v19Execution.report.artifacts,
          trend: report.v19Execution.report.trend,
        }
      : null;
  }

  summarizeTop(report);
  await writeJson(report.artifacts.report, report);

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V20 QA ${report.summary.status.toUpperCase()} healing=${report.summary.healingStatus} healedEvents=${report.summary.healedEvents} v19=${report.summary.v19Status}`);
    if (report.summary.v19Score !== null) console.log(`Latest V18 score through V19: ${report.summary.v19Score}`);
    if (report.summary.persistentBlockers.length) console.log(`Persistent blockers: ${report.summary.persistentBlockers.join(", ")}`);
    console.log(`Report: ${report.artifacts.report}`);
    if (report.healing?.artifacts?.trace) console.log(`Trace: ${report.healing.artifacts.trace}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
