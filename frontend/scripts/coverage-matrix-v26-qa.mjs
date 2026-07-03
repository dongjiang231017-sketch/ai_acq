#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(REPO_ROOT, "backend");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v26-coverage-matrix-qa");

const ownOptionsWithValue = new Set(["--repeat", "--interval-ms", "--artifact-root", "--timeout-ms", "--from-report"]);

const productModules = [
  {
    key: "auth",
    name: "客户登录与账号",
    risk: "critical",
    prefixes: ["/auth"],
    uiPatterns: [/认证入口|认证负例|认证正例|认证状态/],
    expectedEvidence: "login, token, /auth/me, protected API access",
  },
  {
    key: "dashboard",
    name: "实时工作台",
    risk: "high",
    prefixes: ["/modules", "/outbound/overview", "/direct-messages/overview", "/intent/overview"],
    uiPatterns: [/AI外呼系统/],
    expectedEvidence: "module visibility and read-only KPI APIs",
  },
  {
    key: "collector",
    name: "线索采集",
    risk: "critical",
    prefixes: ["/collections"],
    uiPatterns: [/线索采集|采集/],
    expectedEvidence: "collection task list/raw records, safe plan or isolated task creation",
  },
  {
    key: "leads",
    name: "商家线索库",
    risk: "critical",
    prefixes: ["/leads"],
    uiPatterns: [/创建线索|线索写入|新线索归属/],
    expectedEvidence: "create lead, owner/createdBy, UI list visibility",
  },
  {
    key: "outbound",
    name: "AI外呼系统",
    risk: "critical",
    prefixes: ["/outbound"],
    uiPatterns: [/外呼任务|任务只创建不启动|危险请求/],
    expectedEvidence: "create task, preflight, realtime pipeline, records, live gates",
  },
  {
    key: "dm",
    name: "平台私信系统",
    risk: "critical",
    prefixes: ["/direct-messages"],
    uiPatterns: [/私信|DM|direct/i],
    expectedEvidence: "accounts/config/templates/tasks/messages and send/live-send gates",
  },
  {
    key: "intent",
    name: "意向客户池",
    risk: "high",
    prefixes: ["/intent"],
    uiPatterns: [/意向客户|工单|客户池/],
    expectedEvidence: "intent customers/events/work-orders visibility and state changes",
  },
  {
    key: "voice",
    name: "声音档案",
    risk: "critical",
    prefixes: ["/voice"],
    uiPatterns: [/声音档案|音色|授权/],
    expectedEvidence: "profiles/samples/provider/readiness plus preview/training safety gates",
  },
  {
    key: "reports",
    name: "数据报表",
    risk: "medium",
    prefixes: ["/reports"],
    uiPatterns: [/数据报表|报表|导出/],
    expectedEvidence: "overview/channels/sales/exports and export creation gate",
  },
  {
    key: "settings",
    name: "系统设置",
    risk: "critical",
    prefixes: ["/settings"],
    uiPatterns: [/系统设置|线路|合规|设置/],
    expectedEvidence: "settings/audit logs and guarded setting mutation",
  },
  {
    key: "comment_intercepts",
    name: "评论截流",
    risk: "high",
    prefixes: ["/direct-messages/intercepts"],
    uiPatterns: [/评论|截流|automation/i],
    expectedEvidence: "sources/comments/automation queue and live browser action gates",
  },
  {
    key: "learning",
    name: "学习与知识库",
    risk: "medium",
    prefixes: ["/learning"],
    uiPatterns: [/学习|知识|建议/],
    expectedEvidence: "learning overview/suggestions/knowledge visibility",
  },
];

const dangerousRoutePatterns = [
  /\/outbound\/telephony\/test-call$/,
  /\/outbound\/telephony\/recover-line$/,
  /\/outbound\/tasks\/:param\/start$/,
  /\/direct-messages\/tasks\/:param\/start$/,
  /\/direct-messages\/sync-replies$/,
  /\/direct-messages\/accounts\/:param\/login-window$/,
  /\/direct-messages\/intercepts\/sources\/:param\/sync$/,
  /\/direct-messages\/intercepts\/sources\/:param\/browser-capture$/,
  /\/direct-messages\/intercepts\/sources\/:param\/browser-dm-actions$/,
  /\/collections\/tasks\/:param\/run$/,
  /\/voice\/profiles\/:param\/training-jobs$/,
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
    skipV25: false,
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
    } else if (arg === "--skip-v25") {
      options.skipV25 = true;
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
  console.log(`AI ACQ V26 coverage matrix QA

Default: run V25, inventory backend routes and product modules, then produce a risk-weighted coverage matrix from actual evidence.
  npm run qa:v26 -- --repeat 2

Evaluate an existing V25 report:
  npm run qa:v26 -- --from-report .playwright-cli/v25-ui-state-sync-qa/<run>/report.json
`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function readText(file) {
  return fs.readFile(file, "utf8");
}

async function readJson(file) {
  return JSON.parse(await fs.readFile(file, "utf8"));
}

async function writeJson(file, value) {
  await fs.writeFile(file, `${JSON.stringify(redact(value), null, 2)}\n`, "utf8");
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

function isSensitiveKey(key) {
  const normalized = String(key || "").replace(/[-_]/g, "").toLowerCase();
  return /(password|token|secret|authorization|cookie|apikey|accesskey|privatekey|secretkey)/.test(normalized);
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

function traceContext(runId) {
  const traceId = randomBytes(16).toString("hex");
  const spanId = randomBytes(8).toString("hex");
  return {
    runId,
    traceId,
    spanId,
    traceparent: `00-${traceId}-${spanId}-01`,
    baggage: `ai_acq_qa_run=${encodeURIComponent(runId)},ai_acq_qa_version=V26`,
  };
}

function runV25(options, artifactDir, correlation) {
  const args = [
    "scripts/ui-state-sync-v25-qa.mjs",
    "--json",
    "--repeat",
    String(options.repeat),
    "--interval-ms",
    String(options.intervalMs),
    "--timeout-ms",
    String(options.timeoutMs),
    "--artifact-root",
    artifactDir,
  ];
  if (options.batch) args.push("--batch");
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
    maxBuffer: 120 * 1024 * 1024,
    timeout: 25 * 60 * 1000,
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
    durationMs: Date.now() - startedAt,
    parseError,
    report,
    stdoutTail: report ? "" : String(result.stdout || "").slice(-5000),
    stderrTail: String(result.stderr || "").slice(-5000),
  };
}

function normalizeApiPath(value) {
  if (!value) return "/";
  let pathName = value;
  try {
    if (/^https?:\/\//.test(value)) pathName = new URL(value).pathname;
  } catch {
    pathName = value;
  }
  pathName = pathName.replace(/^\/api\b/, "") || "/";
  pathName = pathName.replace(/\/+$/, "") || "/";
  return pathName;
}

function normalizeRoutePath(value) {
  const normalized = normalizeApiPath(value).replace(/\{[^}]+\}/g, ":param");
  return normalized || "/";
}

function joinPaths(prefix, endpoint) {
  const left = prefix === "/" ? "" : prefix;
  const right = endpoint === "/" || endpoint === "" ? "" : endpoint;
  return normalizeRoutePath(`${left}${right}` || "/");
}

function routeRegex(routePath) {
  const escaped = routePath
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\\?:param/g, "[^/]+");
  return new RegExp(`^${escaped}$`);
}

async function routePrefixes() {
  const routerText = await readText(path.join(BACKEND_ROOT, "app", "api", "router.py"));
  const prefixes = new Map();
  const includeRegex = /api_router\.include_router\((\w+)\.router(?:,\s*prefix="([^"]*)")?/g;
  for (const match of routerText.matchAll(includeRegex)) {
    prefixes.set(match[1], match[2] || "");
  }
  return prefixes;
}

async function scanBackendRoutes() {
  const prefixes = await routePrefixes();
  const routes = [];
  for (const [moduleName, prefix] of prefixes.entries()) {
    const file = path.join(BACKEND_ROOT, "app", "api", `${moduleName}.py`);
    let text = "";
    try {
      text = await readText(file);
    } catch {
      continue;
    }
    const routeRegexPattern = /@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"/g;
    for (const match of text.matchAll(routeRegexPattern)) {
      const method = match[1].toUpperCase();
      const pathName = joinPaths(prefix, match[2]);
      routes.push({
        moduleName,
        method,
        path: pathName,
        source: path.relative(REPO_ROOT, file),
        dangerous: method !== "GET" && dangerousRoutePatterns.some((pattern) => pattern.test(pathName)),
      });
    }
  }
  return routes.sort((a, b) => `${a.path} ${a.method}`.localeCompare(`${b.path} ${b.method}`));
}

function evidenceFromV25(v25) {
  const evidence = [];
  const push = (method, endpoint, source, status = null, extra = {}) => {
    if (!endpoint) return;
    evidence.push({
      method: (method || "GET").toUpperCase(),
      path: normalizeApiPath(endpoint),
      source,
      status,
      ...extra,
    });
  };

  for (const response of v25?.v17?.browser?.apiResponses || []) {
    push(response.method, response.url, "v17.browser.apiResponses", response.status, {
      correlationEchoed: response.correlationEchoed,
    });
  }

  for (const response of v25?.v17?.apiResponses || []) {
    push(response.method, response.url, "v17.apiResponses", response.status, {
      correlationEchoed: response.correlationEchoed,
    });
  }

  for (const check of v25?.v24?.propagation?.checks || []) {
    push(check.method || "GET", check.endpoint, "v24.propagation", check.status, {
      correlationEchoed: Object.values(check.assertions || {}).every(Boolean),
    });
  }

  for (const step of Object.values(v25?.v24?.stateful?.steps || {})) {
    push(step.method, step.endpoint, "v24.stateful", step.status, {
      correlationEchoed: Object.values(step.assertions || {}).every(Boolean),
    });
  }

  push("POST", v25?.v24?.auth?.login?.endpoint, "v24.auth", v25?.v24?.auth?.login?.status, {
    correlationEchoed: Object.values(v25?.v24?.auth?.login?.assertions || {}).every(Boolean),
  });
  push("GET", v25?.v24?.auth?.me?.endpoint, "v24.auth", v25?.v24?.auth?.me?.status, {
    correlationEchoed: Object.values(v25?.v24?.auth?.me?.assertions || {}).every(Boolean),
  });

  const v22 = v25?.v24?.v22 || v25?.v24?.v22Execution?.report;
  for (const probe of Object.values(v22?.probes || {})) {
    push(probe.method || "GET", probe.endpoint, "v22.probes", probe.status, {
      correlationEchoed: Boolean(probe.echoedCorrelationId),
    });
  }

  const unique = new Map();
  for (const item of evidence) {
    const key = `${item.method} ${item.path} ${item.source}`;
    if (!unique.has(key)) unique.set(key, item);
  }
  return [...unique.values()];
}

function routeCovered(route, evidence) {
  const matcher = routeRegex(route.path);
  return evidence.some((item) => item.method === route.method && matcher.test(item.path));
}

function prefixMatches(prefixes, routeOrEvidencePath) {
  return prefixes.some((prefix) => routeOrEvidencePath === prefix || routeOrEvidencePath.startsWith(`${prefix}/`));
}

function moduleMatrix(routes, evidence, v25) {
  const uiChecks = v25?.v17?.checks || [];
  return productModules.map((module) => {
    const moduleRoutes = routes.filter((route) => prefixMatches(module.prefixes, route.path));
    const moduleEvidence = evidence.filter((item) => prefixMatches(module.prefixes, item.path));
    const readRoutes = moduleRoutes.filter((route) => route.method === "GET");
    const mutationRoutes = moduleRoutes.filter((route) => route.method !== "GET");
    const coveredReadRoutes = readRoutes.filter((route) => routeCovered(route, evidence));
    const coveredMutationRoutes = mutationRoutes.filter((route) => routeCovered(route, evidence));
    const safeMutationRoutes = mutationRoutes.filter((route) => !route.dangerous);
    const coveredSafeMutations = safeMutationRoutes.filter((route) => routeCovered(route, evidence));
    const uiCovered = uiChecks.some((check) => module.uiPatterns.some((pattern) => pattern.test(`${check.name} ${check.detail}`)));
    const correlationEchoes = moduleEvidence.filter((item) => item.correlationEchoed === true).length;
    let status = "missing";
    if (uiCovered && coveredSafeMutations.length > 0) {
      status = "stateful-ui";
    } else if (coveredSafeMutations.length > 0) {
      status = "stateful-api";
    } else if (uiCovered && coveredReadRoutes.length > 0) {
      status = "ui-read";
    } else if (coveredReadRoutes.length > 0) {
      status = "read-only";
    } else if (uiCovered) {
      status = "ui-only";
    }

    const riskWeight = module.risk === "critical" ? 3 : module.risk === "high" ? 2 : 1;
    const coveragePoints = status === "stateful-ui"
      ? 4
      : status === "stateful-api"
        ? 3
        : status === "ui-read"
          ? 2.5
          : status === "read-only" || status === "ui-only"
            ? 1.5
            : 0;

    return {
      key: module.key,
      name: module.name,
      risk: module.risk,
      riskWeight,
      status,
      score: coveragePoints,
      expectedEvidence: module.expectedEvidence,
      routes: moduleRoutes.length,
      readRoutes: readRoutes.length,
      mutationRoutes: mutationRoutes.length,
      dangerousRoutes: mutationRoutes.filter((route) => route.dangerous).length,
      coveredReadRoutes: coveredReadRoutes.length,
      coveredMutationRoutes: coveredMutationRoutes.length,
      coveredSafeMutations: coveredSafeMutations.length,
      evidenceCount: moduleEvidence.length,
      correlationEchoes,
      uiCovered,
      uncoveredSafeRoutes: moduleRoutes
        .filter((route) => !route.dangerous && !routeCovered(route, evidence))
        .slice(0, 10)
        .map((route) => `${route.method} ${route.path}`),
    };
  });
}

function routeCoverage(routes, evidence) {
  const rows = routes.map((route) => ({
    ...route,
    covered: routeCovered(route, evidence),
  }));
  return {
    total: rows.length,
    covered: rows.filter((route) => route.covered).length,
    safeTotal: rows.filter((route) => !route.dangerous).length,
    safeCovered: rows.filter((route) => !route.dangerous && route.covered).length,
    getTotal: rows.filter((route) => route.method === "GET").length,
    getCovered: rows.filter((route) => route.method === "GET" && route.covered).length,
    mutationTotal: rows.filter((route) => route.method !== "GET").length,
    mutationCovered: rows.filter((route) => route.method !== "GET" && route.covered).length,
    dangerousTotal: rows.filter((route) => route.dangerous).length,
    dangerousCovered: rows.filter((route) => route.dangerous && route.covered).length,
    rows,
  };
}

function nextJourneys(matrix) {
  return matrix
    .filter((item) => item.status !== "stateful-ui")
    .sort((a, b) => (b.riskWeight * (4 - b.score)) - (a.riskWeight * (4 - a.score)))
    .slice(0, 8)
    .map((item) => ({
      module: item.name,
      risk: item.risk,
      currentStatus: item.status,
      nextTarget: item.uncoveredSafeRoutes[0] || item.expectedEvidence,
      suggestedGate: item.key === "dm"
        ? "add isolated DM account/template/task UI state replay without live send"
        : item.key === "voice"
          ? "add isolated voice profile/provider status UI replay without external training"
          : item.key === "settings"
            ? "add guarded settings read/audit UI replay and dry-run mutation check"
            : item.key === "collector"
              ? "add isolated collection task create/read replay without provider run"
              : "add UI replay plus safe API state assertion for this module",
    }));
}

function evaluate(report) {
  const matrix = report.coverage.modules;
  const route = report.coverage.routes;
  const v25Ready = Boolean(report.v25?.summary?.uiStateSyncReady);
  const critical = matrix.filter((item) => item.risk === "critical");
  const criticalCovered = critical.filter((item) => item.status !== "missing").length;
  const criticalStatefulUi = critical.filter((item) => item.status === "stateful-ui").length;
  const weightedEarned = matrix.reduce((sum, item) => sum + item.score * item.riskWeight, 0);
  const weightedMax = matrix.reduce((sum, item) => sum + 4 * item.riskWeight, 0);
  const weightedCoverage = Math.round((weightedEarned / Math.max(1, weightedMax)) * 100);
  const safeRouteCoverage = Math.round((route.safeCovered / Math.max(1, route.safeTotal)) * 100);
  const dimensions = {
    v25Evidence: {
      status: v25Ready ? "pass" : "fail",
      score: v25Ready ? 20 : 0,
      detail: `V25 uiStateSyncReady=${v25Ready}`,
    },
    routeInventory: {
      status: route.total >= 40 ? "pass" : "warn",
      score: route.total >= 40 ? 15 : 10,
      detail: `routes=${route.total}, safe=${route.safeTotal}`,
    },
    observedSafeRouteCoverage: {
      status: safeRouteCoverage >= 35 ? "pass" : safeRouteCoverage >= 15 ? "warn" : "fail",
      score: Math.min(20, Math.round(safeRouteCoverage / 5)),
      detail: `safe routes covered ${route.safeCovered}/${route.safeTotal} (${safeRouteCoverage}%)`,
    },
    riskWeightedModuleCoverage: {
      status: weightedCoverage >= 45 ? "pass" : weightedCoverage >= 25 ? "warn" : "fail",
      score: Math.min(25, Math.round(weightedCoverage / 4)),
      detail: `risk-weighted coverage ${weightedCoverage}%`,
    },
    criticalJourneyCoverage: {
      status: criticalCovered === critical.length ? "pass" : criticalCovered >= 4 ? "warn" : "fail",
      score: Math.round((criticalCovered / Math.max(1, critical.length)) * 10),
      detail: `critical modules with any evidence ${criticalCovered}/${critical.length}; stateful UI ${criticalStatefulUi}/${critical.length}`,
    },
    actionability: {
      status: report.nextJourneys.length > 0 ? "pass" : "warn",
      score: report.nextJourneys.length > 0 ? 10 : 5,
      detail: `next journeys=${report.nextJourneys.length}`,
    },
  };
  const score = Object.values(dimensions).reduce((sum, item) => sum + item.score, 0);
  const broadCoverageReady = critical.every((item) => ["stateful-ui", "stateful-api", "ui-read", "read-only"].includes(item.status))
    && weightedCoverage >= 70
    && safeRouteCoverage >= 60;
  const hardFailure = !v25Ready || route.total === 0 || report.v25Execution?.parseError;
  return {
    status: hardFailure ? "fail" : broadCoverageReady && report.v25?.summary?.canClaimRealBusinessReady ? "pass" : "warn",
    score,
    dimensions,
    readinessDecision: {
      canClaimToolingReady: !hardFailure,
      canClaimBroadBusinessCoverage: broadCoverageReady,
      canClaimRealBusinessReady: Boolean(report.v25?.summary?.canClaimRealBusinessReady) && broadCoverageReady,
      liveActionsStillGated: true,
      weightedCoverage,
      safeRouteCoverage,
      criticalCovered,
      criticalTotal: critical.length,
    },
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V26 Coverage Matrix QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`Tooling ready: ${report.summary.canClaimToolingReady}`);
  lines.push(`Broad business coverage: ${report.summary.canClaimBroadBusinessCoverage}`);
  lines.push(`Real business ready: ${report.summary.canClaimRealBusinessReady}`);
  lines.push("");
  lines.push("## Dimensions");
  for (const [name, item] of Object.entries(report.evaluation.dimensions)) {
    lines.push(`- ${name}: ${item.status} (${item.score}) - ${item.detail}`);
  }
  lines.push("");
  lines.push("## Module Matrix");
  for (const item of report.coverage.modules) {
    lines.push(`- ${item.name} [${item.risk}]: ${item.status}; read ${item.coveredReadRoutes}/${item.readRoutes}; safe mutations ${item.coveredSafeMutations}/${Math.max(0, item.mutationRoutes - item.dangerousRoutes)}; UI=${item.uiCovered}; echo=${item.correlationEchoes}`);
  }
  lines.push("");
  lines.push("## Next Journeys");
  for (const item of report.nextJourneys) {
    lines.push(`- ${item.module}: ${item.suggestedGate}; target=${item.nextTarget}`);
  }
  lines.push("");
  lines.push("## Artifacts");
  lines.push(`- V26 report: ${report.artifacts.report}`);
  lines.push(`- V26 matrix: ${report.artifacts.matrix}`);
  lines.push(`- V25 report: ${report.v25?.artifacts?.report || report.target.fromReport || ""}`);
  lines.push(`- V25 trace: ${report.v25?.summary?.v17Trace || ""}`);
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);
  const correlation = traceContext(randomUUID());
  const report = {
    version: "V26",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      repeat: options.repeat,
      intervalMs: options.intervalMs,
      batch: options.batch,
      fromReport: options.fromReport,
      passThrough: options.passThrough,
    },
    researchBasis: [
      "Risk-based testing needs an explicit coverage matrix so effort follows product risk and observed gaps, not only happy-path success.",
      "Playwright trace evidence and API testing evidence are strongest when mapped back to product modules and backend routes.",
      "Trace-context/correlation evidence should identify not only whether one flow passed, but which modules were never exercised.",
    ],
    correlation,
    v25Execution: null,
    v25: null,
    coverage: null,
    nextJourneys: [],
    evaluation: null,
    summary: null,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "coverage.md"),
      matrix: path.join(artifactDir, "matrix.json"),
    },
  };

  if (options.fromReport) {
    report.v25 = await readJson(options.fromReport);
    report.v25Execution = { command: `read ${options.fromReport}`, exitCode: 0, durationMs: null, parseError: null };
  } else if (!options.skipV25) {
    report.v25Execution = runV25(options, path.join(artifactDir, "v25"), correlation);
    report.v25 = report.v25Execution.report;
  }

  const routes = await scanBackendRoutes();
  const evidence = evidenceFromV25(report.v25);
  const routeMatrix = routeCoverage(routes, evidence);
  const modules = moduleMatrix(routes, evidence, report.v25);
  report.coverage = {
    routes: routeMatrix,
    modules,
    evidence,
  };
  report.nextJourneys = nextJourneys(modules);
  report.evaluation = evaluate(report);
  report.summary = {
    status: report.evaluation.status,
    score: report.evaluation.score,
    canClaimToolingReady: report.evaluation.readinessDecision.canClaimToolingReady,
    canClaimBroadBusinessCoverage: report.evaluation.readinessDecision.canClaimBroadBusinessCoverage,
    canClaimRealBusinessReady: report.evaluation.readinessDecision.canClaimRealBusinessReady,
    weightedCoverage: report.evaluation.readinessDecision.weightedCoverage,
    safeRouteCoverage: report.evaluation.readinessDecision.safeRouteCoverage,
    criticalCovered: report.evaluation.readinessDecision.criticalCovered,
    criticalTotal: report.evaluation.readinessDecision.criticalTotal,
    nextJourney: report.nextJourneys[0] || null,
    v25Report: report.v25?.artifacts?.report || options.fromReport || "",
  };

  await writeJson(report.artifacts.matrix, report.coverage);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(redact(report)), "utf8");

  if (options.json) {
    console.log(JSON.stringify(redact(report), null, 2));
  } else {
    console.log(`V26 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 toolingReady=${report.summary.canClaimToolingReady} broadCoverage=${report.summary.canClaimBroadBusinessCoverage} realBusinessReady=${report.summary.canClaimRealBusinessReady}`);
    console.log(`Coverage: weighted=${report.summary.weightedCoverage}% safeRoutes=${report.summary.safeRouteCoverage}% critical=${report.summary.criticalCovered}/${report.summary.criticalTotal}`);
    if (report.summary.nextJourney) {
      console.log(`Next journey: ${report.summary.nextJourney.module} - ${report.summary.nextJourney.suggestedGate}`);
    }
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Matrix: ${report.artifacts.matrix}`);
  }

  process.exitCode = report.summary.status === "fail" ? 1 : 0;
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
