#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v22-correlation-qa");
const DEFAULT_API = process.env.AI_ACQ_API_URL || "http://127.0.0.1:8017/api";

const ownOptionsWithValue = new Set([
  "--repeat",
  "--interval-ms",
  "--artifact-root",
  "--from-report",
  "--api",
  "--timeout-ms",
  "--mode",
  "--auth-token",
]);

function parseArgs(argv) {
  const options = {
    repeat: 2,
    intervalMs: 1000,
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    fromReport: "",
    api: DEFAULT_API,
    timeoutMs: 120000,
    authToken: process.env.AI_ACQ_QA_AUTH_TOKEN || "",
    json: false,
    batch: false,
    live: false,
    skipV21: false,
    passThrough: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (ownOptionsWithValue.has(arg) && next) {
      if (arg === "--repeat") options.repeat = Math.max(1, Number(next) || 1);
      if (arg === "--interval-ms") options.intervalMs = Math.max(500, Number(next) || 1000);
      if (arg === "--artifact-root") options.artifactRoot = path.resolve(next);
      if (arg === "--from-report") options.fromReport = path.resolve(next);
      if (arg === "--api") options.api = next.replace(/\/$/, "");
      if (arg === "--timeout-ms") options.timeoutMs = Math.max(10000, Number(next) || 120000);
      if (arg === "--mode") options.live = next === "live";
      if (arg === "--auth-token") options.authToken = next;
      index += 1;
    } else if (arg === "--json") {
      options.json = true;
    } else if (arg === "--batch") {
      options.batch = true;
    } else if (arg === "--live") {
      options.live = true;
    } else if (arg === "--skip-v21") {
      options.skipV21 = true;
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
  console.log(`AI ACQ V22 cross-layer correlation QA

Default: run V21, then build a correlated evidence graph across UI trace, V19/V18 reports, read-only APIs, telephony, realtime events, DM, and persistence.
  npm run qa:v22 -- --repeat 2

Batch readiness:
  npm run qa:v22:batch -- --allowlist qa/v18-live-allowlist.example.json --max-calls 2 --max-sends 1

Evaluate an existing V21 report:
  npm run qa:v22 -- --from-report .playwright-cli/v21-evidence-eval-qa/<run>/report.json
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

async function exists(file) {
  if (!file) return false;
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

function redact(value, key = "") {
  if (typeof value === "string") {
    let next = value;
    if (/password|token|secret|authorization|cookie|key/i.test(key)) {
      return next ? "[redacted]" : "";
    }
    next = next.replace(/\b1[3-9]\d{9}\b/g, (match) => `${match.slice(0, 3)}****${match.slice(-4)}`);
    next = next.replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[token-redacted]");
    return next;
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

function traceparentFor(runId) {
  const traceId = randomBytes(16).toString("hex");
  const spanId = randomBytes(8).toString("hex");
  return {
    runId,
    traceId,
    spanId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V22`,
  };
}

function extractOptionValue(passThrough, name) {
  const index = passThrough.indexOf(name);
  if (index >= 0 && passThrough[index + 1]) return passThrough[index + 1];
  return "";
}

function phoneQuery(passThrough) {
  const phone = extractOptionValue(passThrough, "--phone");
  return phone ? `?phone=${encodeURIComponent(phone)}` : "";
}

function runV21(options, artifactDir, correlation) {
  const args = [
    "scripts/evidence-evaluator-v21-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--artifact-root",
    path.join(artifactDir, "v21"),
  ];
  if (options.batch) args.push("--batch");
  if (options.live) args.push("--live");
  args.push("--api", options.api);
  args.push(...options.passThrough.filter((arg) => arg !== "--json"));

  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: {
      ...process.env,
      AI_ACQ_QA_CORRELATION_ID: correlation.runId,
      AI_ACQ_QA_TRACEPARENT: correlation.traceparent,
    },
    encoding: "utf8",
    maxBuffer: 60 * 1024 * 1024,
    timeout: 16 * 60 * 1000,
  });
  const durationMs = Date.now() - startedAt;

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
    durationMs,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-4000),
    stderrTail: String(result.stderr || "").slice(-4000),
  };
}

async function loadArtifactChain(v21Report) {
  const chain = {
    v21: { report: v21Report, path: v21Report?.artifacts?.report || "" },
    v20: { report: v21Report?.v20 || null, path: v21Report?.v20?.artifacts?.report || v21Report?.target?.fromReport || "" },
    v19: { report: null, path: "" },
    v18: { report: null, path: "" },
    loadErrors: [],
  };

  if ((!chain.v20.report || !chain.v20.report.summary) && chain.v20.path && await exists(chain.v20.path)) {
    try {
      chain.v20.report = await readJson(chain.v20.path);
    } catch (error) {
      chain.loadErrors.push({ artifact: "v20", path: chain.v20.path, error: error.message });
    }
  }

  chain.v19.path = chain.v20.report?.v19?.artifacts?.report || "";
  if (chain.v19.path && await exists(chain.v19.path)) {
    try {
      chain.v19.report = await readJson(chain.v19.path);
    } catch (error) {
      chain.loadErrors.push({ artifact: "v19", path: chain.v19.path, error: error.message });
    }
  }

  const latestRound = chain.v19.report?.rounds?.at(-1);
  chain.v18.path = latestRound?.v18ReportPath || chain.v19.report?.rounds?.findLast?.((round) => round.v18ReportPath)?.v18ReportPath || "";
  if (chain.v18.path && await exists(chain.v18.path)) {
    try {
      chain.v18.report = await readJson(chain.v18.path);
    } catch (error) {
      chain.loadErrors.push({ artifact: "v18", path: chain.v18.path, error: error.message });
    }
  }

  return chain;
}

async function readOnlyProbe(options, endpoint, correlation, required = false) {
  const startedAt = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Math.min(options.timeoutMs, 30000));
  const url = `${options.api}${endpoint}`;
  const headers = {
    Accept: "application/json",
    "X-AI-ACQ-QA-Correlation-Id": correlation.runId,
    "X-Request-ID": correlation.runId,
    traceparent: correlation.traceparent,
    baggage: correlation.baggage,
  };
  if (options.authToken) headers.Authorization = `Bearer ${options.authToken}`;
  try {
    const response = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      headers,
    });
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text.slice(0, 1000) };
    }
    return {
      endpoint,
      url,
      method: "GET",
      required,
      ok: response.ok,
      status: response.status,
      durationMs: Date.now() - startedAt,
      echoedCorrelationId: response.headers.get("x-ai-acq-qa-correlation-id") || response.headers.get("x-request-id") || "",
      body,
    };
  } catch (error) {
    return {
      endpoint,
      url,
      method: "GET",
      required,
      ok: false,
      status: 0,
      durationMs: Date.now() - startedAt,
      error: error.name === "AbortError" ? "probe timeout" : error.message,
      body: null,
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function collectProbes(options, correlation) {
  const endpoints = [
    ["health", "/health", true],
    ["auth", "/auth/me", false],
    ["collectionTasks", "/collections/tasks", false],
    ["rawLeadRecords", "/collections/raw-records", false],
    ["telephonyConfig", "/outbound/telephony/config", true],
    ["telephonyHealth", "/outbound/telephony/health", true],
    ["telephonyPreflight", `/outbound/telephony/preflight${phoneQuery(options.passThrough)}`, true],
    ["realtimePipeline", "/outbound/realtime/pipeline", true],
    ["liveEvents", "/outbound/realtime/live-events?limit=120", false],
    ["callRecords", "/outbound/records", false],
    ["dmConfig", "/direct-messages/config", false],
    ["dmAccounts", "/direct-messages/accounts", false],
    ["dmConversations", "/direct-messages/conversations", false],
    ["dmMessages", "/direct-messages/messages", false],
  ];
  const entries = {};
  for (const [name, endpoint, required] of endpoints) {
    entries[name] = await readOnlyProbe(options, endpoint, correlation, required);
  }
  return entries;
}

function checkStatus(checks, pattern) {
  return (checks || []).find((check) => pattern.test(`${check.name || ""} ${check.detail || ""}`))?.status || "missing";
}

function statusFromProbe(probe, warnStatuses = [401, 403, 404]) {
  if (!probe) return "missing";
  if (probe.ok) return "pass";
  if (warnStatuses.includes(probe.status)) return "warn";
  return probe.required ? "fail" : "warn";
}

function node(id, layer, status, detail, data = {}) {
  return { id, layer, status, detail, data };
}

function edge(from, to, status, evidence, action = "") {
  return { from, to, status, evidence, action };
}

function edgeStatus(...statuses) {
  if (statuses.includes("fail")) return "fail";
  if (statuses.includes("missing") || statuses.includes("warn")) return "warn";
  return "pass";
}

function actionForLayer(layer) {
  const map = {
    artifact_chain: "Open the first missing report path; rerun V21 if the nested V20/V19/V18 chain is incomplete.",
    backend_api: "Start or repair the API service, then verify /api/health and proxy/API base before UI testing.",
    auth_account: "Provide a real customer account or enable an isolated seeded account path for this run.",
    lead_collection: "Configure a real provider/browser session and prove collected raw records before outbound actions.",
    telephony_ami: "Check AMI host/port/credentials/manager.conf and firewall; rerun preflight after authentication passes.",
    telephony_trunk: "Check gateway registration, PJSIP endpoint/contact, SIP route, SIM/line availability, and number matching.",
    telephony_preflight: "Make single-number preflight pass before live call or batch acceptance.",
    media_bridge: "Start AudioSocket/realtime bridge and confirm dialplan routes answered calls into it.",
    realtime_events: "Compare live-events, call records, and audio evidence for call_connected, speech, TTS, and disconnect.",
    dm_gateway: "Switch DM gateway to browser live-send, log in a supported platform account, and verify quota/risk state.",
    event_persistence: "Cross-check records/messages/events after the UI action; add backend persistence assertions if missing.",
    safety_gate: "Keep live calls/sends/batch/production writes blocked until explicit flags and allowlists are present.",
    ui_trace: "Open Playwright trace/screenshots and inspect console/network/page errors before editing product code.",
  };
  return map[layer] || "Inspect nested evidence and add a targeted verifier for this layer.";
}

function buildGraph(chain, probes, correlation) {
  const v21 = chain.v21.report;
  const v20 = chain.v20.report;
  const v19 = chain.v19.report;
  const v18 = chain.v18.report;
  const checks = v18?.checks || [];
  const persistentBlockers = v21?.v20?.summary?.persistentBlockers || v20?.summary?.persistentBlockers || v19?.summary?.persistentBlockers || [];
  const traceExists = Boolean(v21?.evaluation?.artifacts?.traceExists || v20?.healing?.artifacts?.trace);
  const nodes = [
    node("qa_run", "correlation", "pass", `runId=${correlation.runId}`, { traceparent: correlation.traceparent }),
    node("v21_evaluation", "artifact_chain", v21?.summary?.canClaimToolingReady ? "pass" : "fail", `score=${v21?.summary?.score ?? "missing"}`, { path: chain.v21.path }),
    node("v20_ui_replay", "ui_trace", v20?.summary?.healingStatus === "pass" ? "pass" : "fail", `healing=${v20?.summary?.healingStatus || "missing"}`, { path: chain.v20.path, trace: v20?.healing?.artifacts?.trace || "" }),
    node("v19_diagnosis", "artifact_chain", v19?.summary?.status || "missing", `persistent=${persistentBlockers.join(", ") || "none"}`, { path: chain.v19.path }),
    node("v18_real_flow", "artifact_chain", v18?.summary?.status || "missing", `score=${v18?.summary?.score ?? "missing"}`, { path: chain.v18.path }),
    node("backend_api", "backend_api", statusFromProbe(probes.health), probes.health?.ok ? "/health ok" : probes.health?.error || `HTTP ${probes.health?.status || "missing"}`),
    node("auth_account", "auth_account", edgeStatus(statusFromProbe(probes.auth), checkStatus(checks, /auth|登录|账号|密码|V18 真实数据/i)), `authMe=HTTP ${probes.auth?.status || 0}`),
    node("lead_collection", "lead_collection", edgeStatus(statusFromProbe(probes.collectionTasks), statusFromProbe(probes.rawLeadRecords), checkStatus(checks, /采集|collection|raw/i)), `tasks=${probes.collectionTasks?.status || 0}, raw=${probes.rawLeadRecords?.status || 0}`),
    node("telephony_config", "telephony_ami", statusFromProbe(probes.telephonyConfig), `HTTP ${probes.telephonyConfig?.status || 0}`),
    node("telephony_health", "telephony_trunk", statusFromProbe(probes.telephonyHealth), `HTTP ${probes.telephonyHealth?.status || 0}`),
    node("telephony_preflight", "telephony_preflight", statusFromProbe(probes.telephonyPreflight), `HTTP ${probes.telephonyPreflight?.status || 0}`),
    node("media_bridge", "media_bridge", statusFromProbe(probes.realtimePipeline), `HTTP ${probes.realtimePipeline?.status || 0}`),
    node("realtime_events", "realtime_events", statusFromProbe(probes.liveEvents), `events=${Array.isArray(probes.liveEvents?.body?.events) ? probes.liveEvents.body.events.length : "unknown"}`),
    node("dm_gateway", "dm_gateway", edgeStatus(statusFromProbe(probes.dmConfig), statusFromProbe(probes.dmAccounts), checkStatus(checks, /私信|DM|direct/i)), `config=${probes.dmConfig?.status || 0}, accounts=${probes.dmAccounts?.status || 0}`),
    node("event_persistence", "event_persistence", edgeStatus(statusFromProbe(probes.callRecords), statusFromProbe(probes.dmMessages), checkStatus(checks, /落库|records|messages|事件/i)), `records=${probes.callRecords?.status || 0}, messages=${probes.dmMessages?.status || 0}`),
    node("safety_gates", "safety_gate", persistentBlockers.some((item) => /confirm|real_data|allowlist/.test(item)) ? "warn" : "pass", `blockers=${persistentBlockers.join(", ") || "none"}`),
  ];

  const edges = [
    edge("qa_run", "v21_evaluation", v21 ? "pass" : "fail", chain.v21.path || "V21 report in memory", actionForLayer("artifact_chain")),
    edge("v21_evaluation", "v20_ui_replay", chain.v20.report ? "pass" : "fail", chain.v20.path || "missing V20 artifact", actionForLayer("artifact_chain")),
    edge("v20_ui_replay", "v19_diagnosis", chain.v19.report ? "pass" : "warn", chain.v19.path || "missing V19 artifact", actionForLayer("artifact_chain")),
    edge("v19_diagnosis", "v18_real_flow", chain.v18.report ? "pass" : "warn", chain.v18.path || "missing V18 artifact", actionForLayer("artifact_chain")),
    edge("qa_run", "backend_api", statusFromProbe(probes.health), probes.health?.ok ? "/health ok" : probes.health?.error || `HTTP ${probes.health?.status || 0}`, actionForLayer("backend_api")),
    edge("v20_ui_replay", "backend_api", traceExists ? "pass" : "warn", traceExists ? "trace artifact exists" : "missing trace artifact", actionForLayer("ui_trace")),
    edge("backend_api", "auth_account", edgeStatus(statusFromProbe(probes.health), statusFromProbe(probes.auth)), `authMe HTTP ${probes.auth?.status || 0}`, actionForLayer("auth_account")),
    edge("backend_api", "lead_collection", edgeStatus(statusFromProbe(probes.collectionTasks), statusFromProbe(probes.rawLeadRecords)), `collection probes ${probes.collectionTasks?.status || 0}/${probes.rawLeadRecords?.status || 0}`, actionForLayer("lead_collection")),
    edge("backend_api", "telephony_config", edgeStatus(statusFromProbe(probes.health), statusFromProbe(probes.telephonyConfig)), "telephony config probe", actionForLayer("telephony_ami")),
    edge("telephony_config", "telephony_health", edgeStatus(statusFromProbe(probes.telephonyConfig), statusFromProbe(probes.telephonyHealth)), "AMI/trunk health probe", actionForLayer("telephony_trunk")),
    edge("telephony_health", "telephony_preflight", edgeStatus(statusFromProbe(probes.telephonyHealth), statusFromProbe(probes.telephonyPreflight)), "phone-level preflight probe", actionForLayer("telephony_preflight")),
    edge("telephony_preflight", "media_bridge", edgeStatus(statusFromProbe(probes.telephonyPreflight), statusFromProbe(probes.realtimePipeline)), "realtime pipeline probe", actionForLayer("media_bridge")),
    edge("media_bridge", "realtime_events", edgeStatus(statusFromProbe(probes.realtimePipeline), statusFromProbe(probes.liveEvents)), "live events probe", actionForLayer("realtime_events")),
    edge("backend_api", "dm_gateway", edgeStatus(statusFromProbe(probes.dmConfig), statusFromProbe(probes.dmAccounts)), "DM config/account probes", actionForLayer("dm_gateway")),
    edge("realtime_events", "event_persistence", edgeStatus(statusFromProbe(probes.callRecords), statusFromProbe(probes.dmMessages)), "records/messages probes", actionForLayer("event_persistence")),
    edge("safety_gates", "v18_real_flow", persistentBlockers.some((item) => /confirm|real_data|allowlist/.test(item)) ? "warn" : "pass", "live actions remain gated by V18 confirmations", actionForLayer("safety_gate")),
  ];

  const brokenEdges = edges.filter((item) => item.status !== "pass");
  return {
    nodes,
    edges,
    brokenEdges,
    persistentBlockers,
    loadedArtifacts: {
      v21: chain.v21.path,
      v20: chain.v20.path,
      v19: chain.v19.path,
      v18: chain.v18.path,
      trace: v20?.healing?.artifacts?.trace || v21?.evaluation?.artifacts?.trace || "",
    },
  };
}

function evaluate(report) {
  const graph = report.graph;
  const probes = report.probes;
  const requiredProbeNames = ["health", "telephonyConfig", "telephonyHealth", "telephonyPreflight", "realtimePipeline"];
  const requiredProbePasses = requiredProbeNames.filter((name) => probes[name]?.ok).length;
  const requiredProbeAttempts = requiredProbeNames.filter((name) => probes[name]).length;
  const responseEchoes = Object.values(probes).filter((probe) => probe.echoedCorrelationId === report.correlation.runId).length;
  const artifactCount = ["v21", "v20", "v19", "v18"].filter((name) => Boolean(report.artifactChain[name]?.report)).length;
  const traceExists = Boolean(graph.loadedArtifacts.trace);
  const businessLayers = new Set(graph.nodes.map((item) => item.layer));
  const eventProbeNames = ["liveEvents", "callRecords", "dmMessages"];
  const eventProbeAttempts = eventProbeNames.filter((name) => probes[name]).length;
  const eventEvidence = eventProbeNames.filter((name) => probes[name]?.ok || [401, 403, 404].includes(probes[name]?.status)).length;

  const dimensions = {
    correlationIdentity: {
      status: responseEchoes > 0 ? "pass" : "warn",
      score: responseEchoes > 0 ? 15 : 11,
      detail: responseEchoes > 0 ? `correlation echoed by ${responseEchoes} responses` : "traceparent/correlation headers were sent; backend echo middleware not observed",
    },
    nestedArtifactChain: {
      status: artifactCount >= 3 && traceExists ? "pass" : artifactCount >= 2 ? "warn" : "fail",
      score: Math.min(20, artifactCount * 4 + (traceExists ? 4 : 0)),
      detail: `loaded=${artifactCount}/4, trace=${traceExists}`,
    },
    apiProbeCoverage: {
      status: requiredProbePasses === requiredProbeNames.length ? "pass" : requiredProbeAttempts === requiredProbeNames.length ? "warn" : "fail",
      score: requiredProbeAttempts === requiredProbeNames.length
        ? requiredProbePasses === requiredProbeNames.length ? 20 : 18
        : Math.round((requiredProbeAttempts / requiredProbeNames.length) * 12),
      detail: `required read-only probes attempted ${requiredProbeAttempts}/${requiredProbeNames.length}, passed ${requiredProbePasses}/${requiredProbeNames.length}`,
    },
    businessLayerMapping: {
      status: graph.nodes.length >= 10 && graph.brokenEdges.length > 0 ? "pass" : "warn",
      score: Math.min(20, businessLayers.size * 2),
      detail: `layers=${businessLayers.size}, brokenEdges=${graph.brokenEdges.length}`,
    },
    eventEvidence: {
      status: eventEvidence >= 2 ? "pass" : eventProbeAttempts === eventProbeNames.length ? "warn" : "fail",
      score: eventEvidence >= 2 ? 15 : eventProbeAttempts === eventProbeNames.length ? 11 : Math.min(8, eventProbeAttempts * 2),
      detail: `event/persistence probes attempted ${eventProbeAttempts}/3, usable ${eventEvidence}/3`,
    },
    actionabilitySpeed: {
      status: report.v21Execution?.durationMs && report.v21Execution.durationMs < 60000 ? "pass" : "warn",
      score: report.v21Execution?.durationMs && report.v21Execution.durationMs < 60000 ? 10 : 7,
      detail: report.v21Execution?.durationMs ? `${report.v21Execution.durationMs}ms` : "existing report evaluation",
    },
  };

  const score = Object.values(dimensions).reduce((sum, item) => sum + item.score, 0);
  const v21ToolingReady = Boolean(report.v21?.summary?.canClaimToolingReady);
  const v21RealReady = Boolean(report.v21?.summary?.canClaimRealBusinessReady);
  const hardToolFailure = dimensions.nestedArtifactChain.status === "fail" || !report.v21;
  return {
    status: hardToolFailure ? "fail" : v21RealReady && graph.brokenEdges.length === 0 ? "pass" : "warn",
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: v21ToolingReady && dimensions.nestedArtifactChain.status !== "fail",
      canClaimRealBusinessReady: v21RealReady && graph.brokenEdges.length === 0,
      liveActionsStillGated: true,
      runtimeReadinessScore: Math.round((requiredProbePasses / requiredProbeNames.length) * 100),
    },
    topBrokenEdge: graph.brokenEdges[0] || null,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V22 Cross-Layer Correlation QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Correlation: ${report.correlation.runId}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Broken Edges");
  if (!report.graph.brokenEdges.length) {
    lines.push("- No broken edges.");
  } else {
    for (const item of report.graph.brokenEdges.slice(0, 12)) {
      lines.push(`- ${item.from} -> ${item.to}: ${item.status}; ${item.evidence}; next=${item.action}`);
    }
  }
  lines.push("");
  lines.push("## Artifact Chain");
  lines.push(`- V22 report: ${report.artifacts.report}`);
  lines.push(`- V21 report: ${report.artifactChain.v21.path || ""}`);
  lines.push(`- V20 report: ${report.artifactChain.v20.path || ""}`);
  lines.push(`- V19 report: ${report.artifactChain.v19.path || ""}`);
  lines.push(`- V18 report: ${report.artifactChain.v18.path || ""}`);
  lines.push(`- Trace: ${report.graph.loadedArtifacts.trace || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const correlation = traceparentFor(randomUUID());
  const report = {
    version: "V22",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      api: options.api,
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      live: options.live,
      fromReport: options.fromReport,
      passThrough: options.passThrough,
      hasAuthToken: Boolean(options.authToken),
    },
    researchBasis: [
      "Playwright trace artifacts should be connected to backend/API evidence instead of read as isolated UI proof.",
      "Distributed tracing concepts such as traceparent, baggage, and correlation IDs make cross-service failures diagnosable.",
      "Real acceptance still requires V18 live confirmations; V22 only strengthens diagnosis and evidence routing.",
    ],
    correlation,
    v21Execution: null,
    v21: null,
    artifactChain: null,
    probes: {},
    graph: null,
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "correlation.md"),
    },
  };

  if (options.fromReport) {
    report.v21 = await readJson(options.fromReport);
    report.v21Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV21) {
    report.v21Execution = runV21(options, artifactDir, correlation);
    report.v21 = report.v21Execution.report;
  }

  report.artifactChain = await loadArtifactChain(report.v21);
  report.probes = await collectProbes(options, correlation);
  report.graph = buildGraph(report.artifactChain, report.probes, correlation);
  report.evaluation = evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    runtimeReadinessScore: report.evaluation.readinessDecision.runtimeReadinessScore,
    topBrokenEdge: report.evaluation.topBrokenEdge,
    graphNodes: report.graph.nodes.length,
    graphEdges: report.graph.edges.length,
    brokenEdges: report.graph.brokenEdges.length,
  };

  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V22 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    if (report.summary.topBrokenEdge) {
      console.log(`Top broken edge: ${report.summary.topBrokenEdge.from} -> ${report.summary.topBrokenEdge.to}: ${report.summary.topBrokenEdge.action}`);
    }
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Correlation: ${report.artifacts.markdown}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
