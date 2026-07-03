#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v19-self-healing-qa");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--mode"]);
const ownFlags = new Set(["--json", "--batch", "--live", "--until-pass", "--allow-repair", "--stop-on-critical", "--help", "-h"]);

function parseArgs(argv) {
  const options = {
    repeat: 3,
    intervalMs: 3000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    json: false,
    batch: false,
    live: false,
    untilPass: false,
    allowRepair: false,
    stopOnCritical: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 3000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--mode") options.live = next === "live";
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--live") {
      options.live = true;
    } else if (arg === "--until-pass") {
      options.untilPass = true;
    } else if (arg === "--allow-repair") {
      options.allowRepair = true;
    } else if (arg === "--stop-on-critical") {
      options.stopOnCritical = true;
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
  console.log(`AI ACQ V19 self-healing continuous QA

Plan mode, continuous diagnosis:
  npm run qa:v19 -- --json --repeat 3

Batch plan mode:
  npm run qa:v19:batch -- --json --repeat 3 --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1

Safe repair loop:
  npm run qa:v19 -- --json --repeat 3 --allow-repair

Live mode is only a controller around V18 live gates. You still need V18 confirmation flags:
  npm run qa:v19 -- --live --confirm-real-data --confirm-live-call --confirm-production-write ...
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

function extractApi(passThrough) {
  const index = passThrough.indexOf("--api");
  if (index >= 0 && passThrough[index + 1]) return passThrough[index + 1].replace(/\/$/, "");
  return DEFAULT_API;
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

function runV18(options, roundDir) {
  const args = ["scripts/live-business-v18-qa.mjs", options.live ? "--require-live" : "--plan-only", "--json", "--artifact-root", path.join(roundDir, "v18")];
  if (options.batch) args.push("--live-batch");
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 30 * 1024 * 1024,
    timeout: 10 * 60 * 1000,
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
    stdout: result.stdout,
    stderr: result.stderr,
    parseError,
    report,
  };
}

const blockerRules = [
  { category: "deployment_api", pattern: /\/(?:auth|collections)[^ ]* -> HTTP 404|authMe.*HTTP 404|collectionTasks.*HTTP 404|rawLeadRecords.*HTTP 404/i, action: "当前 API 版本缺少客户登录或线索采集路由；需要部署包含 auth/collections 的后端版本。" },
  { category: "confirmations", pattern: /blocked until|missing --confirm|--confirm-|未执行|生产写入|live batch is blocked/i, action: "需要显式确认参数，不能自动代替用户确认。" },
  { category: "backend_api", pattern: /fetch failed|ECONNREFUSED|ENOTFOUND|ETIMEDOUT|health.*(?:failed|unavailable)|API.*unavailable|service unavailable/i, action: "启动或修复后端 API 服务，确认 API base、端口、代理和健康检查。" },
  { category: "real_data", pattern: /真实数据|missing=|真实城市|真实品类|真实客户|真实商家|真实测试|no raw|no .*lead|没有.*线索/i, action: "补齐真实账号、城市、品类、商家、联系人、手机号或采集源。" },
  { category: "allowlist", pattern: /白名单|allowlist|phone is not a real dialable number|call\[\d+\]|send\[\d+\]/i, action: "修正 allowlist，使用授权真实号码/账号并保留预算上限。" },
  { category: "auth", pattern: /401|请先登录|客户账号登录|auth token|账号|密码/i, action: "提供真实账号密码，或允许本地账号生成并确认写入。" },
  { category: "ami", pattern: /AMI|Authentication failed|amiReachable|authenticated=false|后端连不上 Asterisk/i, action: "检查 Asterisk/AMI 服务、端口、manager.conf、凭据和防火墙。" },
  { category: "trunk", pattern: /Trunk|trunkReachable|trunkStatus|PJSIP|网关.*注册/i, action: "检查语音网关注册、PJSIP endpoint/contact、SIP 线路和路由。" },
  { category: "preflight", pattern: /预检|readyForTestCall=false|readyForSingleNumberTest|手机号级/i, action: "先让单号预检通过，再进入真实拨测或批量验收。" },
  { category: "live_call_switch", pattern: /ASTERISK_LIVE_CALL_ENABLED=false|真实业务: 单号试拨开关|asteriskLiveCallEnabled=false/i, action: "确认单号试拨稳定后打开 ASTERISK_LIVE_CALL_ENABLED。" },
  { category: "bulk_switch", pattern: /ASTERISK_BULK_CALL_ENABLED=false|批量开关|asteriskBulkCallEnabled=false/i, action: "确认受控批量测试后打开 ASTERISK_BULK_CALL_ENABLED，并限制白名单和数量。" },
  { category: "media_bridge", pattern: /媒体桥|AudioSocket|bridge=mock|mock_media|readyForAsteriskMedia=false/i, action: "启动或修复 AudioSocket/realtime bridge，确认 dialplan 接入 AudioSocket。" },
  { category: "asr_tts_llm", pattern: /ASR|TTS|LLM|Omni|human_speech|aiSpeech|真人语音|AI 首句|对话验收/i, action: "检查实时事件、模型 key、路由、音频捕获和打断恢复。" },
  { category: "dm_gateway", pattern: /私信|live send|browserLiveSendEnabled=false|gatewayMode=simulator|平台个人号|未登录/i, action: "切到 browser live-send，登录平台个人号，确认发送上限和风控状态。" },
  { category: "collection_provider", pattern: /采集|高德|amap|baidu|douyin|meituan|密钥|API key|fetched=0|未配置/i, action: "配置真实采集 provider key 或登录可用平台浏览器会话。" },
  { category: "backend_events", pattern: /live-events|事件|落库|records=0|messages=0|会话\/消息证据|通话记录落库/i, action: "对比事件日志、API 列表和数据库记录，定位写入链路。" },
  { category: "ui_runtime", pattern: /console|pageerror|failedRequests|UI|页面|浏览器|trace/i, action: "打开 trace/screenshot，定位前端状态或网络请求失败。" },
];

function collectBlockedChecks(v18Report) {
  if (!v18Report?.checks) return [];
  return v18Report.checks.filter((check) => check.status === "warn" || check.status === "fail");
}

function classifyBlockers(v18Report) {
  const categories = new Map();
  for (const check of collectBlockedChecks(v18Report)) {
    const text = `${check.name || ""} ${check.detail || ""}`;
    const matches = blockerRules.filter((rule) => rule.pattern.test(text));
    const selected = matches.length ? matches : [{ category: "unknown", action: "保留原始失败，人工分析。" }];
    for (const rule of selected) {
      if (!categories.has(rule.category)) {
        categories.set(rule.category, { category: rule.category, severity: "warn", count: 0, checks: [], action: rule.action });
      }
      const item = categories.get(rule.category);
      item.count += 1;
      item.checks.push({ name: check.name, status: check.status, detail: check.detail });
      if (check.status === "fail") item.severity = "fail";
    }
  }
  return Array.from(categories.values()).sort((a, b) => {
    const rank = (item) => (item.severity === "fail" ? 2 : 1);
    return rank(b) - rank(a) || b.count - a.count || a.category.localeCompare(b.category);
  });
}

async function apiRequest(api, endpoint, requestOptions = {}) {
  const response = await fetch(`${api}${endpoint}`, {
    method: requestOptions.method || "GET",
    headers: {
      Accept: "application/json",
      ...(requestOptions.body ? { "Content-Type": "application/json" } : {}),
    },
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

function runLocalCheck(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 5 * 1024 * 1024,
    timeout: 30000,
  });
  return {
    command: `${command} ${args.join(" ")}`,
    exitCode: result.status,
    stdout: String(result.stdout || "").slice(0, 4000),
    stderr: String(result.stderr || "").slice(0, 4000),
  };
}

async function attemptRepair(category, api) {
  if (["ami", "trunk", "preflight"].includes(category)) {
    const result = await apiRequest(api, "/outbound/telephony/recover-line", { method: "POST", body: {} });
    return {
      category,
      action: "POST /outbound/telephony/recover-line",
      status: result.ok ? "attempted" : "failed",
      detail: result.ok ? "line recovery endpoint accepted" : `HTTP ${result.status}`,
      result,
    };
  }

  if (category === "media_bridge" || category === "asr_tts_llm") {
    const python = path.join(BACKEND_ROOT, ".venv", "bin", "python");
    const check = runLocalCheck(python, ["-m", "app.tools.realtime_audio_bridge", "--check"], BACKEND_ROOT);
    return {
      category,
      action: "python -m app.tools.realtime_audio_bridge --check",
      status: check.exitCode === 0 ? "checked" : "failed",
      detail: check.exitCode === 0 ? "bridge check completed" : "bridge check failed",
      result: check,
    };
  }

  if (category === "backend_events") {
    const result = await apiRequest(api, "/outbound/realtime/live-events?limit=120");
    return {
      category,
      action: "GET /outbound/realtime/live-events?limit=120",
      status: result.ok ? "checked" : "failed",
      detail: result.ok ? `events=${Array.isArray(result.body?.events) ? result.body.events.length : "unknown"}` : `HTTP ${result.status}`,
      result,
    };
  }

  if (category === "dm_gateway") {
    const [config, accounts] = await Promise.all([
      apiRequest(api, "/direct-messages/config"),
      apiRequest(api, "/direct-messages/accounts"),
    ]);
    return {
      category,
      action: "GET /direct-messages/config + /accounts",
      status: config.ok && accounts.ok ? "checked" : "failed",
      detail: `config=${config.status}, accounts=${accounts.status}`,
      result: { config, accounts },
    };
  }

  return {
    category,
    action: "manual",
    status: "manual_required",
    detail: blockerRules.find((rule) => rule.category === category)?.action || "requires manual input",
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildTrend(rounds) {
  const scores = rounds.map((round) => round.v18?.summary?.score).filter((score) => Number.isFinite(score));
  const categoriesByRound = rounds.map((round) => new Set(round.blockers.map((blocker) => blocker.category)));
  const allCategories = Array.from(new Set(categoriesByRound.flatMap((set) => Array.from(set)))).sort();
  const categoryStats = allCategories.map((category) => {
    const present = categoriesByRound.filter((set) => set.has(category)).length;
    return {
      category,
      rounds: present,
      stability: present === rounds.length ? "persistent" : present === 1 ? "one-off" : "intermittent",
    };
  });
  return {
    scores,
    bestScore: scores.length ? Math.max(...scores) : null,
    lastScore: scores.length ? scores[scores.length - 1] : null,
    categoryStats,
  };
}

function summarize(report) {
  const latest = report.rounds[report.rounds.length - 1];
  const latestStatus = latest?.v18?.summary?.status || "fail";
  const critical = latest?.blockers?.filter((blocker) => blocker.severity === "fail") || [];
  const toolFailure = report.rounds.some((round) => round.parseError || !round.v18);
  report.summary = {
    status: latestStatus === "pass" ? "pass" : toolFailure || (report.target.mode === "live" && critical.length) ? "fail" : "warn",
    rounds: report.rounds.length,
    passedRounds: report.rounds.filter((round) => round.v18?.summary?.status === "pass").length,
    repairedActions: report.repairs.filter((repair) => ["attempted", "checked"].includes(repair.status)).length,
    latestV18Status: latestStatus,
    latestV18Score: latest?.v18?.summary?.score ?? null,
    persistentBlockers: report.trend.categoryStats.filter((item) => item.stability === "persistent").map((item) => item.category),
  };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const api = extractApi(options.passThrough);
  const report = {
    version: "V19",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      api,
      mode: options.live ? "live" : "plan",
      batch: options.batch,
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      untilPass: options.untilPass,
      allowRepair: options.allowRepair,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Retry is useful for detecting flakiness, but repeated retries should not hide persistent failures.",
      "Trace and artifact capture on retry/failure makes failures inspectable instead of anecdotal.",
      "Self-healing should distinguish broken test mechanics from broken product behavior and repair only safe mechanics automatically.",
      "Continuous testing should track recurring blockers and trends, not only the latest run.",
    ],
    rounds: [],
    repairs: [],
    trend: {},
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
    },
  };

  for (let roundIndex = 0; roundIndex < options.repeat; roundIndex += 1) {
    const roundDir = path.join(artifactDir, `round-${roundIndex + 1}`);
    await mkdirp(roundDir);
    const result = runV18(options, roundDir);
    const blockers = classifyBlockers(result.report);
    const round = {
      index: roundIndex + 1,
      startedAt: new Date().toISOString(),
      command: result.command,
      exitCode: result.exitCode,
      signal: result.signal,
      parseError: result.parseError,
      v18ReportPath: result.report?.artifacts?.report || null,
      v18: result.report
        ? {
            summary: result.report.summary,
            target: result.report.target,
            artifacts: result.report.artifacts,
          }
        : null,
      blockers,
      stdoutTail: result.report ? "" : String(result.stdout || "").slice(-4000),
      stderrTail: String(result.stderr || "").slice(-4000),
    };
    report.rounds.push(round);

    if (result.report?.summary?.status === "pass" && options.untilPass) break;

    if (options.allowRepair && blockers.length > 0) {
      for (const blocker of blockers) {
        const repair = await attemptRepair(blocker.category, api).catch((error) => ({
          category: blocker.category,
          action: "repair_exception",
          status: "failed",
          detail: error.message,
        }));
        repair.round = round.index;
        report.repairs.push(repair);
        if (options.stopOnCritical && repair.status === "failed") break;
      }
    }

    if (roundIndex < options.repeat - 1) await sleep(options.intervalMs);
  }

  report.trend = buildTrend(report.rounds);
  summarize(report);
  await writeJson(report.artifacts.report, report);

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V19 QA ${report.summary.status.toUpperCase()} rounds=${report.summary.rounds} latestScore=${report.summary.latestV18Score}`);
    console.log(`Report: ${report.artifacts.report}`);
    for (const item of report.trend.categoryStats) {
      console.log(`${item.stability.toUpperCase()} ${item.category}: ${item.rounds}/${report.rounds.length}`);
    }
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
