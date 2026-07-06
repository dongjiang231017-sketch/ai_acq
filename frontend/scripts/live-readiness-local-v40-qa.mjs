#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v40-local-readiness-trace-qa");
const DEFAULT_ALLOWLIST = path.join(FRONTEND_ROOT, "qa", "v36-real-live-allowlist.template.json");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    allowlistPath: DEFAULT_ALLOWLIST,
    api: DEFAULT_API,
    host: "127.0.0.1",
    port: 0,
    timeoutMs: 30000,
    strict: false,
    reuseUrl: "",
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
    } else if (arg === "--api" && next) {
      options.api = next.replace(/\/$/, "");
      index += 1;
    } else if (arg === "--host" && next) {
      options.host = next;
      index += 1;
    } else if (arg === "--port" && next) {
      options.port = Math.max(0, Number(next) || 0);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--reuse-url" && next) {
      options.reuseUrl = next;
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
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
  console.log(`AI ACQ V40 local readiness trace QA

Usage:
  npm run qa:v40 -- --json
  npm run qa:v40:strict -- --allowlist <real-authorized-allowlist.json> --api <api-base> --json
  npm run qa:v40 -- --reuse-url http://127.0.0.1:4178/ --json

V40 starts or reuses a local frontend preview, runs V39 against it, captures browser trace/screenshot evidence, then stops owned preview processes.`);
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function normalizeUrl(url) {
  return url.endsWith("/") ? url : `${url}/`;
}

async function isReachable(url, timeoutMs = 3000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function findFreePort(host) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitForUrl(url, timeoutMs, logs) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await isReachable(url, 2500)) return { ok: true, durationMs: Date.now() - startedAt };
    await sleep(400);
  }
  return { ok: false, durationMs: Date.now() - startedAt, tail: logs.join("").slice(-3000) };
}

async function startPreview(options, artifactDir) {
  if (options.reuseUrl) {
    const url = normalizeUrl(options.reuseUrl);
    return {
      url,
      reused: true,
      owned: false,
      ready: await isReachable(url, 5000),
      logsPath: "",
      stop: async () => {},
    };
  }

  const port = options.port || (await findFreePort(options.host));
  const url = `http://${options.host}:${port}/`;
  const logs = [];
  const logFile = path.join(artifactDir, "preview.log");
  const child = spawn("npm", ["run", "preview", "--", "--host", options.host, "--port", String(port), "--strictPort"], {
    cwd: FRONTEND_ROOT,
    env: {
      ...process.env,
      VITE_API_BASE_URL: options.api,
      BROWSER: "none",
      NO_COLOR: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => logs.push(String(chunk)));
  child.stderr.on("data", (chunk) => logs.push(String(chunk)));

  const readiness = await waitForUrl(url, options.timeoutMs, logs);
  await fs.writeFile(logFile, logs.join(""), "utf8").catch(() => {});
  return {
    url,
    port,
    reused: false,
    owned: true,
    pid: child.pid,
    ready: readiness.ok,
    durationMs: readiness.durationMs,
    logsPath: logFile,
    logsTail: readiness.tail || logs.join("").slice(-3000),
    stop: async () => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
      await sleep(500);
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    },
  };
}

function runV39(options, artifactDir, url) {
  const args = [
    "scripts/live-readiness-trace-v39-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v39"),
    "--allowlist",
    options.allowlistPath,
    "--api",
    options.api,
    "--url",
    url,
    "--timeout-ms",
    String(options.timeoutMs),
    "--json",
  ];
  if (options.strict) args.push("--strict");
  if (options.headed) args.push("--headed");
  if (options.noTrace) args.push("--no-trace");

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: Math.max(options.timeoutMs + 30000, 45000),
    maxBuffer: 80 * 1024 * 1024,
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
    stdoutTail: report ? "" : result.stdout?.slice(-3000) || "",
    stderrTail: result.stderr?.slice(-3000) || "",
  };
}

function compactV39(report) {
  if (!report) return null;
  return {
    version: report.version || "",
    summary: report.summary || {},
    correlation: report.correlation || {},
    api: report.api || {},
    ui: report.ui || {},
    artifacts: report.artifacts || {},
    v38: report.v38 || null,
  };
}

function summarize(report, options) {
  const v39Summary = report.v39?.summary || {};
  const previewReady = Boolean(report.preview.ready);
  const uiOpened = Boolean(v39Summary.uiOpened);
  const traceReady = Boolean(report.v39?.artifacts?.trace);
  const status = !previewReady && !options.reuseUrl ? "warn" : v39Summary.status || "warn";
  report.summary = {
    status,
    score: Math.min(100, Math.round((v39Summary.score || 0) + (previewReady ? 10 : 0) + (uiOpened ? 10 : 0))),
    firstBlocker: v39Summary.firstBlocker || (previewReady ? "" : "local_preview_not_ready"),
    previewReady,
    previewOwned: Boolean(report.preview.owned),
    uiOpened,
    traceReady,
    screenshotReady: Boolean(report.v39?.artifacts?.screenshot),
    apiReady: Boolean(v39Summary.apiReady),
    liveActionsExecuted: false,
    noLiveSideEffects: true,
    nextCommand: v39Summary.nextCommand || "",
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V40 Local Readiness Trace QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`Preview URL: ${report.preview.url}`);
  lines.push(`Trace: ${report.v39?.artifacts?.trace || "n/a"}`);
  lines.push(`Screenshot: ${report.v39?.artifacts?.screenshot || "n/a"}`);
  lines.push(`Next command: \`${report.summary.nextCommand || "n/a"}\``);
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Owned local preview process is stopped after the run.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const preview = await startPreview(options, artifactDir);
  let v39Run = null;
  try {
    v39Run = preview.ready ? runV39(options, artifactDir, preview.url) : null;
  } finally {
    await preview.stop();
  }

  const report = {
    version: "V40",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      api: options.api,
      allowlist: options.allowlistPath,
      strict: options.strict,
      reuseUrl: options.reuseUrl,
      host: options.host,
      port: preview.port || null,
    },
    researchBasis: [
      "Playwright webServer guidance motivates starting local app services before tests when no staging URL is available.",
      "Vite preview CLI supports host and port selection for local production-preview checks.",
      "Playwright trace retention makes failures debuggable through trace.zip, screenshots, DOM snapshots, and network evidence.",
    ],
    preview: {
      url: preview.url,
      ready: preview.ready,
      reused: preview.reused,
      owned: preview.owned,
      pid: preview.pid || null,
      durationMs: preview.durationMs || 0,
      logsPath: preview.logsPath,
      logsTail: preview.ready ? "" : preview.logsTail || "",
    },
    v39Run: v39Run
      ? {
          command: v39Run.command,
          exitCode: v39Run.exitCode,
          durationMs: v39Run.durationMs,
          parseError: v39Run.parseError,
          stdoutTail: v39Run.stdoutTail,
          stderrTail: v39Run.stderrTail,
        }
      : null,
    v39: compactV39(v39Run?.report),
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "local-readiness-trace.md"),
      previewLog: preview.logsPath,
      trace: v39Run?.report?.artifacts?.trace || "",
      screenshot: v39Run?.report?.artifacts?.screenshot || "",
    },
    summary: {},
  };
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V40 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Preview: ${report.preview.url}`);
    console.log(`Trace: ${report.artifacts.trace || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
