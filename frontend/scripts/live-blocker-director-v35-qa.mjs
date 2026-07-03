#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v35-live-blocker-director-qa");
const V34_SCRIPT = path.join("scripts", "live-evidence-v34-qa.mjs");

const ownOptionsWithValue = new Set(["--artifact-root", "--from-report", "--timeout-ms", "--repeat", "--interval-ms"]);
const passThroughWithValue = new Set([
  "--api",
  "--url",
  "--cdp",
  "--desktop-app",
  "--cdp-port",
  "--allowlist",
  "--max-calls",
  "--max-sends",
  "--interval-ms",
  "--batch-call-mode",
  "--username",
  "--password",
  "--phone",
  "--caller-id",
  "--merchant-name",
  "--city",
  "--category",
  "--contact-name",
  "--platform",
  "--platform-url",
  "--collection-provider",
  "--collection-keyword",
  "--collection-target",
  "--comment-platform",
  "--comment-source-url",
  "--dm-message",
]);

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    timeoutMs: 180000,
    repeat: 1,
    intervalMs: 1000,
    json: false,
    requireLive: false,
    liveBatch: false,
    planOnly: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      if (arg === "--timeout-ms") {
        options.timeoutMs = Math.max(10000, Number(next) || 180000);
        options.passThrough.push(arg, String(options.timeoutMs));
      }
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") {
        options.intervalMs = Math.max(0, Number(next) || 0);
        options.passThrough.push(arg, String(options.intervalMs));
      }
      index += 1;
    } else if (passThroughWithValue.has(arg) && next) {
      options.passThrough.push(arg, next);
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--require-live") {
      options.requireLive = true;
      options.passThrough.push(arg);
    } else if (arg === "--live-batch") {
      options.liveBatch = true;
      options.passThrough.push(arg);
    } else if (arg === "--plan-only") {
      options.planOnly = true;
      options.passThrough.push(arg);
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      options.passThrough.push(arg);
    }
  }
  return options;
}

function printHelp() {
  console.log(`AI ACQ V35 live blocker director QA

Usage:
  npm run qa:v35:plan -- --json
  npm run qa:v35:live-batch -- --allowlist <real-allowlist.json> --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write
  npm run qa:v35 -- --from-report <v34-report.json>

V35 reads or runs V34, then converts the first blocker into an operator-grade action plan, rerun command, checklist, and verification target. Plan mode never dials, sends, or writes.`);
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

function reportPathFromOutput(stdout) {
  return stdout?.match(/Report:\s*(.+report\.json)/)?.[1]?.trim() || "";
}

function runV34(options, artifactDir, round) {
  if (options.fromReport && round === 0) {
    const content = fsSync.readFileSync(options.fromReport, "utf8");
    return {
      command: `read ${options.fromReport}`,
      exitCode: 0,
      durationMs: 0,
      report: JSON.parse(content),
    };
  }

  const args = [
    V34_SCRIPT,
    "--artifact-root",
    path.join(artifactDir, `v34-round-${round + 1}`),
    "--timeout-ms",
    String(options.timeoutMs),
    ...options.passThrough.filter((arg) => arg !== "--json"),
  ];
  if (!options.requireLive && !args.includes("--plan-only")) args.push("--plan-only");

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    maxBuffer: 220 * 1024 * 1024,
    timeout: Math.max(options.timeoutMs + 30000, 90000),
  });

  let parsed = null;
  let parseError = "";
  const fallbackPath = reportPathFromOutput(result.stdout);
  if (fallbackPath) {
    parsed = JSON.parse(fsSync.readFileSync(fallbackPath, "utf8"));
  } else {
    try {
      parsed = parseJsonOutput(result.stdout);
    } catch (error) {
      parseError = error.message;
    }
  }

  if (!parsed) throw new Error(`V34 report missing; exit=${result.status}; ${parseError}`);
  return {
    command: `${process.execPath} ${args.join(" ")}`,
    exitCode: result.status,
    signal: result.signal,
    durationMs: Date.now() - startedAt,
    stdoutTail: result.stdout?.slice(-2000) || "",
    stderrTail: result.stderr?.slice(-2000) || "",
    report: parsed,
  };
}

function probeSummary(v34) {
  const probes = v34.runtime?.probes || {};
  return Object.fromEntries(
    Object.entries(probes).map(([key, value]) => [
      key,
      {
        ok: Boolean(value.ok),
        status: value.status,
        endpoint: value.endpoint,
      },
    ]),
  );
}

function snapshotV34(run) {
  const v34 = run.report;
  return {
    command: run.command,
    exitCode: run.exitCode,
    durationMs: run.durationMs,
    status: v34.summary?.status || "unknown",
    score: v34.summary?.score ?? 0,
    canClaimRealLiveAcceptance: Boolean(v34.summary?.canClaimRealLiveAcceptance),
    firstBlocker: v34.summary?.firstBlocker || null,
    nextAction: v34.summary?.nextAction || "",
    report: v34.artifacts?.report || "",
    markdown: v34.artifacts?.markdown || "",
    graph: v34.artifacts?.graph || "",
    v33Report: v34.summary?.v33Report || "",
    v18Report: v34.summary?.v18Report || "",
    probes: probeSummary(v34),
  };
}

function commandForRerun(layer) {
  if (layer === "backend_api") {
    return "cd frontend && npm run qa:v35:plan -- --api <working-api-base> --json";
  }
  if (layer === "real_data_allowlist") {
    return "cd frontend && npm run qa:v35:live-batch -- --allowlist <real-authorized-allowlist.json> --max-calls <n> --max-sends <n> --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json";
  }
  if (layer === "confirmations") {
    return "cd frontend && npm run qa:v35:live-batch -- --allowlist <real-authorized-allowlist.json> --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json";
  }
  if (layer?.startsWith("v33_")) {
    return "cd frontend && npm run qa:v35:live-batch -- --allowlist <real-authorized-allowlist.json> --max-calls <n> --max-sends <n> --confirm-real-data --confirm-live-call --confirm-live-send --confirm-live-batch --confirm-production-write --json";
  }
  return "cd frontend && npm run qa:v35:plan -- --json";
}

function recipeFor(blocker) {
  const layer = blocker?.layer || "none";
  const recipes = {
    real_data_allowlist: {
      owner: "operator",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: [
        "authorized real call recipient phone",
        "authorized merchant/customer identity",
        "city/category/contact context",
        "approved private-message platform/account target",
        "approved message copy",
        "call/send budget and pacing",
      ],
      safeChecks: ["Validate allowlist schema", "Reject placeholders/example domains/non-dialable phone values", "Redact sensitive identifiers in reports"],
      acceptanceSignal: "V34 firstBlocker moves past real_data_allowlist and V33 reports real data acceptance.",
    },
    confirmations: {
      owner: "operator",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["--confirm-real-data", "--confirm-live-call", "--confirm-live-send", "--confirm-live-batch when batch", "--confirm-production-write"],
      safeChecks: ["Confirm max-calls/max-sends caps", "Confirm allowlist recipients match the approved test window"],
      acceptanceSignal: "V34 firstBlocker moves past confirmations.",
    },
    backend_api: {
      owner: "engineer",
      humanInputRequired: false,
      canAutoRepair: "safe-local-start-candidate",
      requiredInputs: ["working API base URL"],
      safeChecks: ["GET /health", "read-only telephony/DM/realtime probes", "use public API with --api when local backend is intentionally down"],
      acceptanceSignal: "All runtime probes needed for the scenario return non-error status.",
    },
    telephony_live_switch: {
      owner: "telephony",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["TELEPHONY_GATEWAY_MODE=asterisk", "ASTERISK_LIVE_CALL_ENABLED=true for approved single-number window"],
      safeChecks: ["GET /outbound/telephony/config", "GET /outbound/telephony/health"],
      acceptanceSignal: "V34 telephony_live_switch passes and AMI/trunk checks become the active layers.",
    },
    ami_auth: {
      owner: "telephony",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["ASTERISK_HOST", "ASTERISK_AMI_PORT", "ASTERISK_AMI_USERNAME", "ASTERISK_AMI_PASSWORD secret alias"],
      safeChecks: ["AMI login probe", "Asterisk manager ACL/permission check"],
      acceptanceSignal: "AMI authenticated/reachable probe passes.",
    },
    trunk_reachable: {
      owner: "telephony",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["registered UC100/Dinstar SIP trunk", "PJSIP endpoint reachable", "SIP/RTP firewall path"],
      safeChecks: ['Asterisk CLI: pjsip show endpoints', 'Asterisk CLI: pjsip show registrations'],
      acceptanceSignal: "trunkReachable=true and preflight advances to phone-level test.",
    },
    phone_preflight: {
      owner: "operator",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["one authorized phone from allowlist"],
      safeChecks: ["GET /outbound/telephony/preflight?phone=<redacted-authorized-phone>"],
      acceptanceSignal: "phone preflight readyForSingleNumberTest=true.",
    },
    media_bridge: {
      owner: "engineer",
      humanInputRequired: false,
      canAutoRepair: "service-start-candidate",
      requiredInputs: ["AudioSocket host/port", "ASR/TTS/LLM provider readiness", "selected voice profile"],
      safeChecks: ["GET /outbound/realtime/pipeline", "GET /outbound/realtime/live-events?limit=80"],
      acceptanceSignal: "readyForAsteriskMedia=true and V33 call evidence can verify media/human/AI speech.",
    },
    dm_live_switch: {
      owner: "operator",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["DM gateway browser live mode", "DM_BROWSER_LIVE_SEND_ENABLED=true for approved window"],
      safeChecks: ["GET /direct-messages/config", "caps and cooldown check"],
      acceptanceSignal: "DM live-send switch passes and account login becomes the active layer.",
    },
    dm_logged_account: {
      owner: "operator",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["logged-in platform personal account", "desktop-login-check status 可用/已登录", "same-platform account pool"],
      safeChecks: ["GET /direct-messages/accounts", "desktop-login-check after manual login"],
      acceptanceSignal: "At least one supported platform account is usable/logged in.",
    },
    v33_real_call_evidence: {
      owner: "qa",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["strict live call run after all preflight layers pass"],
      safeChecks: ["gateway accepted", "cellular confirmation", "media loop", "human speech", "AI speech", "conversation acceptance"],
      acceptanceSignal: "V33 canClaimRealCallAcceptance=true.",
    },
    v33_real_dm_evidence: {
      owner: "qa",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["strict live private-message run after DM account/live switch pass"],
      safeChecks: ["send action started", "conversation persisted", "message persisted"],
      acceptanceSignal: "V33 canClaimRealDmAcceptance=true.",
    },
    v33_real_live_acceptance: {
      owner: "qa",
      humanInputRequired: true,
      canAutoRepair: false,
      requiredInputs: ["both call and private-message evidence complete"],
      safeChecks: ["V33 report", "V18 report", "trace/screenshots/provider evidence"],
      acceptanceSignal: "V33 canClaimRealLiveAcceptance=true.",
    },
    none: {
      owner: "qa",
      humanInputRequired: false,
      canAutoRepair: false,
      requiredInputs: [],
      safeChecks: ["Preserve report artifacts", "Promote stable run to regression evidence"],
      acceptanceSignal: "Real live acceptance can be claimed.",
    },
  };
  const recipe = recipes[layer] || {
    owner: "engineer",
    humanInputRequired: true,
    canAutoRepair: false,
    requiredInputs: [blocker?.detail || "unknown blocker detail"],
    safeChecks: ["Inspect V34 blocker graph"],
    acceptanceSignal: "Blocker disappears on V34 rerun.",
  };
  return {
    layer,
    detail: blocker?.detail || "",
    ...recipe,
    rerunCommand: commandForRerun(layer),
  };
}

function buildChecklist(recipe) {
  const shared = [
    { item: "Never run live call/send without explicit confirmation flags", status: "required" },
    { item: "Keep max-calls/max-sends small for first live batch", status: "required" },
    { item: "Preserve V35, V34, V33, and V18 report paths", status: "required" },
    { item: "Redact raw phone numbers, passwords, cookies, tokens, and account secrets", status: "required" },
  ];
  const blockerItems = recipe.requiredInputs.map((item) => ({ item, status: recipe.humanInputRequired ? "needs-human" : "needs-check" }));
  const checks = recipe.safeChecks.map((item) => ({ item, status: "safe-check" }));
  return [...blockerItems, ...checks, ...shared];
}

function summarize(report, options) {
  const latest =
    report.rounds.at(-1) ||
    (report.errors.length
      ? {
          score: 0,
          firstBlocker: {
            layer: "v35_runner",
            status: "fail",
            detail: report.errors.at(-1)?.message || "V35 runner failed before V34 report was parsed",
          },
          nextAction: "Inspect V35 runner error, then rerun qa:v35:plan.",
          canClaimRealLiveAcceptance: false,
        }
      : {});
  const blocker = latest.firstBlocker || null;
  const recipe = recipeFor(blocker);
  const resolved = Boolean(latest.canClaimRealLiveAcceptance);
  const status = resolved ? "pass" : options.requireLive && blocker?.status === "fail" ? "fail" : "warn";
  const score = resolved ? 100 : Math.max(0, Math.min(95, (latest.score || 0) + (recipe.layer === "real_data_allowlist" ? 5 : 10)));
  report.director = {
    status,
    score,
    firstBlocker: blocker,
    nextAction: latest.nextAction || recipe.acceptanceSignal,
    recipe,
    checklist: buildChecklist(recipe),
    rerunCommand: recipe.rerunCommand,
    realLiveReady: resolved,
    liveActionsExecuted: false,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V35 Live Blocker Director QA");
  lines.push("");
  lines.push(`Status: ${report.director.status}`);
  lines.push(`Score: ${report.director.score}/100`);
  lines.push(`First blocker: ${report.director.firstBlocker?.layer || "none"}`);
  lines.push(`Next action: ${report.director.nextAction}`);
  lines.push(`Rerun command: \`${report.director.rerunCommand}\``);
  lines.push("");
  lines.push("## Checklist");
  for (const item of report.director.checklist) lines.push(`- ${item.status}: ${item.item}`);
  lines.push("");
  lines.push("## Latest V34");
  const latest = report.rounds.at(-1) || {};
  lines.push(`- Report: ${latest.report || ""}`);
  lines.push(`- Graph: ${latest.graph || ""}`);
  lines.push(`- V33: ${latest.v33Report || ""}`);
  lines.push(`- V18: ${latest.v18Report || ""}`);
  return `${lines.join("\n")}\n`;
}

function redact(value) {
  return JSON.parse(
    JSON.stringify(value, (key, item) => {
      if (/password|secret|token|cookie|phone/i.test(key) && typeof item === "string" && item) return "[redacted]";
      return item;
    }),
  );
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const report = {
    version: "V35",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      requireLive: options.requireLive,
      liveBatch: options.liveBatch,
      repeat: options.repeat,
    },
    researchBasis: [
      "Playwright codegen/locator guidance favors user-facing role/text/test-id locators for resilient replay plans.",
      "OpenTelemetry log/trace correlation motivates preserving correlation ids across evidence and operator checklists.",
      "Asterisk CEL/AMI event evidence is needed to distinguish real call progress from a clicked UI button.",
    ],
    rounds: [],
    errors: [],
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "director.md"),
    },
    director: {},
  };

  for (let round = 0; round < options.repeat; round += 1) {
    try {
      const run = runV34(options, artifactDir, round);
      report.rounds.push(snapshotV34(run));
    } catch (error) {
      report.errors.push({ round: round + 1, message: error.stack || error.message });
    }
    if (round < options.repeat - 1) await sleep(options.intervalMs);
  }

  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V35 QA ${report.director.status.toUpperCase()} score=${report.director.score}/100 realLive=${report.director.realLiveReady}`);
    console.log(`First blocker: ${report.director.firstBlocker?.layer || "none"}`);
    console.log(`Next action: ${report.director.nextAction}`);
    console.log(`Rerun: ${report.director.rerunCommand}`);
    console.log(`Report: ${report.artifacts.report}`);
  }

  process.exit(report.director.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
