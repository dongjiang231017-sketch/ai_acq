#!/usr/bin/env node
import { chromium, request } from "playwright";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v39-live-readiness-trace-qa");
const DEFAULT_ALLOWLIST = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");
const DEFAULT_URL = process.env.AI_ACQ_QA_URL || "http://127.0.0.1:4178/";
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_ALLOWLIST,
    url: DEFAULT_URL,
    api: DEFAULT_API,
    timeoutMs: 30000,
    strict: false,
    skipUi: false,
    skipApi: false,
    headed: false,
    noTrace: false,
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--allowlist" && next) {
      options.allowlistPath = path.resolve(next);
      index += 1;
    } else if (arg === "--url" && next) {
      options.url = next;
      index += 1;
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
    } else if (arg === "--skip-ui") {
      options.skipUi = true;
    } else if (arg === "--skip-api") {
      options.skipApi = true;
    } else if (arg === "--headed") {
      options.headed = true;
    } else if (arg === "--no-trace") {
      options.noTrace = true;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V39 live readiness trace QA

Usage:
  npm run qa:v39 -- --json --timeout-ms 30000
  npm run qa:v39:strict -- --allowlist <real-authorized-allowlist.json> --api <api-base> --url <client-url> --json

V39 runs V38, then adds trace-retained browser/API evidence without live calls, sends, writes, or account changes.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function makeTraceparent() {
  const bytes = randomBytes(24).toString("hex");
  return `00-${bytes.slice(0, 32)}-${bytes.slice(32, 48)}-01`;
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function runV38(options, artifactDir) {
  const args = [
    "scripts/live-readiness-bundle-v38-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v38"),
    "--allowlist",
    options.allowlistPath,
    "--timeout-ms",
    String(options.timeoutMs),
    "--json",
  ];
  if (options.strict) args.push("--strict");
  if (options.api) args.push("--api", options.api);

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: Math.max(options.timeoutMs + 20000, 30000),
    maxBuffer: 60 * 1024 * 1024,
  });
  let report = null;
  let parseError = "";
  try {
    report = parseJsonOutput(result.stdout);
  } catch (error) {
    parseError = error.message;
  }
  return {
    command: `${process.execPath} ${args.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : result.stdout?.slice(-2000) || "",
    stderrTail: result.stderr?.slice(-2000) || "",
  };
}

function correlationFromV38(v38) {
  const correlation = v38?.report?.correlation || {};
  return {
    id: correlation.id || `v39-${nowSlug()}`,
    traceparent: correlation.traceparent || makeTraceparent(),
    baggage: correlation.baggage || "ai-acq-qa-version=V39",
  };
}

function compactV38(report) {
  if (!report) return null;
  return {
    version: report.version || "",
    summary: report.summary || {},
    correlation: report.correlation || {},
    layers: report.layers || [],
    nested: report.nested || {},
    artifacts: report.artifacts || {},
  };
}

async function probeApi(options, correlation) {
  if (options.skipApi) return { skipped: true, probes: [], okCount: 0, total: 0 };
  const context = await request.newContext({
    baseURL: `${options.api.replace(/\/$/, "")}/`,
    extraHTTPHeaders: {
      "X-AI-ACQ-QA-Correlation-Id": correlation.id,
      "X-Request-ID": correlation.id,
      traceparent: correlation.traceparent,
      baggage: correlation.baggage,
    },
    timeout: Math.min(options.timeoutMs, 15000),
  });
  const endpoints = [
    "health",
    "outbound/telephony/config",
    "outbound/telephony/health",
    "direct-messages/config",
    "realtime/pipeline/status",
  ];
  const probes = [];
  try {
    for (const endpoint of endpoints) {
      const startedAt = Date.now();
      try {
        const response = await context.get(endpoint);
        probes.push({
          endpoint,
          ok: response.ok(),
          status: response.status(),
          durationMs: Date.now() - startedAt,
          contentType: response.headers()["content-type"] || "",
        });
      } catch (error) {
        probes.push({
          endpoint,
          ok: false,
          status: 0,
          durationMs: Date.now() - startedAt,
          error: error.message,
        });
      }
    }
  } finally {
    await context.dispose();
  }
  return {
    skipped: false,
    probes,
    okCount: probes.filter((probe) => probe.ok).length,
    total: probes.length,
  };
}

async function launchBrowser(headed) {
  const launchOptions = { headless: !headed, args: ["--disable-blink-features=AutomationControlled"] };
  try {
    return await chromium.launch({ ...launchOptions, channel: "chrome" });
  } catch {
    return chromium.launch(launchOptions);
  }
}

async function captureUi(options, artifactDir, correlation) {
  if (options.skipUi) return { skipped: true };
  const tracePath = path.join(artifactDir, "trace.zip");
  const screenshotPath = path.join(artifactDir, "client-readiness.png");
  const browser = await launchBrowser(options.headed);
  const consoleMessages = [];
  const pageErrors = [];
  const failedRequests = [];
  let context = null;
  try {
    context = await browser.newContext({
      viewport: { width: 1440, height: 980 },
      extraHTTPHeaders: {
        "X-AI-ACQ-QA-Correlation-Id": correlation.id,
        "X-Request-ID": correlation.id,
        traceparent: correlation.traceparent,
        baggage: correlation.baggage,
      },
    });
    if (!options.noTrace) await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    const page = await context.newPage();
    page.on("console", (message) => {
      const type = message.type();
      if (["error", "warning"].includes(type)) consoleMessages.push({ type, text: message.text().slice(0, 500) });
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("requestfailed", (requestInfo) => {
      failedRequests.push({
        url: requestInfo.url(),
        method: requestInfo.method(),
        failure: requestInfo.failure()?.errorText || "",
      });
    });
    const startedAt = Date.now();
    let opened = false;
    let title = "";
    let bodySnippet = "";
    try {
      await page.goto(options.url, { waitUntil: "domcontentloaded", timeout: Math.min(options.timeoutMs, 20000) });
      opened = true;
      title = await page.title();
      bodySnippet = (await page.locator("body").innerText({ timeout: 5000 }).catch(() => "")).slice(0, 1200);
      await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    } finally {
      if (!options.noTrace) await context.tracing.stop({ path: tracePath }).catch(() => {});
    }
    return {
      skipped: false,
      opened,
      url: options.url,
      title,
      durationMs: Date.now() - startedAt,
      screenshot: screenshotPath,
      trace: options.noTrace ? "" : tracePath,
      visibleSignals: {
        hasOutbound: bodySnippet.includes("AI外呼系统"),
        hasLeadCollection: bodySnippet.includes("线索采集"),
        hasPlatformDm: bodySnippet.includes("平台私信系统"),
        hasSettings: bodySnippet.includes("系统设置"),
      },
      consoleMessages,
      pageErrors,
      failedRequests,
    };
  } catch (error) {
    return {
      skipped: false,
      opened: false,
      url: options.url,
      error: error.message,
      trace: options.noTrace ? "" : tracePath,
      screenshot: "",
      consoleMessages,
      pageErrors,
      failedRequests,
    };
  } finally {
    await context?.close().catch(() => {});
    await browser.close().catch(() => {});
  }
}

function summarize(report, options) {
  const v38Status = report.v38?.summary?.status || (report.v38Run.exitCode === 0 ? "pass" : "fail");
  const apiWarn = !report.api.skipped && report.api.okCount === 0;
  const uiWarn = !report.ui.skipped && !report.ui.opened;
  const runtimeErrors =
    (report.ui.consoleMessages?.length || 0) + (report.ui.pageErrors?.length || 0) + (report.ui.failedRequests?.length || 0);
  const status = options.strict && v38Status === "fail" ? "fail" : v38Status === "pass" && !apiWarn && !uiWarn && runtimeErrors === 0 ? "pass" : "warn";
  const score = Math.max(
    0,
    Math.min(
      100,
      Math.round(
        (report.v38?.summary?.readinessScore || 0) * 0.55 +
          (report.api.skipped ? 10 : report.api.total ? (report.api.okCount / report.api.total) * 20 : 0) +
          (report.ui.skipped ? 10 : report.ui.opened ? 15 : 0) +
          (report.ui.trace ? 10 : 0) -
          Math.min(15, runtimeErrors * 3),
      ),
    ),
  );
  report.summary = {
    status,
    score,
    firstBlocker: report.v38?.summary?.firstBlocker || (uiWarn ? "ui_not_opened" : apiWarn ? "api_unreachable" : ""),
    v38Status,
    apiReady: report.api.skipped || report.api.okCount > 0,
    uiTraceReady: report.ui.skipped || Boolean(report.ui.trace),
    uiSkipped: Boolean(report.ui.skipped),
    uiOpened: Boolean(report.ui.opened),
    runtimeIssueCount: runtimeErrors,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
    nextCommand: report.v38?.summary?.nextCommand || "",
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V39 Live Readiness Trace QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`Next command: \`${report.summary.nextCommand || "n/a"}\``);
  lines.push("");
  lines.push("## Evidence");
  lines.push(`- V38 report: ${report.v38?.artifacts?.report || "n/a"}`);
  lines.push(`- API probes: ${report.api.okCount || 0}/${report.api.total || 0}`);
  lines.push(`- UI trace: ${report.ui.trace || "n/a"}`);
  lines.push(`- UI screenshot: ${report.ui.screenshot || "n/a"}`);
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const v38Run = runV38(options, artifactDir);
  const correlation = correlationFromV38(v38Run);
  const [api, ui] = await Promise.all([probeApi(options, correlation), captureUi(options, artifactDir, correlation)]);

  const report = {
    version: "V39",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      url: options.url,
      api: options.api,
      allowlist: options.allowlistPath,
      strict: options.strict,
      skipUi: options.skipUi,
      skipApi: options.skipApi,
    },
    researchBasis: [
      "Playwright Trace Viewer supports trace review with actions, DOM snapshots, screenshots, and network evidence.",
      "Playwright APIRequestContext supports API checks that can be composed with end-to-end evidence.",
      "OpenTelemetry and W3C trace context motivate carrying traceparent and baggage across UI/API probes.",
    ],
    correlation,
    v38Run: {
      command: v38Run.command,
      exitCode: v38Run.exitCode,
      durationMs: v38Run.durationMs,
      parseError: v38Run.parseError,
      stdoutTail: v38Run.stdoutTail,
      stderrTail: v38Run.stderrTail,
    },
    v38: compactV38(v38Run.report),
    api,
    ui,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "readiness-trace.md"),
      trace: ui.trace || "",
      screenshot: ui.screenshot || "",
    },
    summary: {},
  };
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V39 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Trace: ${report.artifacts.trace || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
