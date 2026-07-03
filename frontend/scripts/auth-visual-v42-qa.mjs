#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const DEFAULT_ARTIFACT_ROOT = path.join(FRONTEND_ROOT, ".playwright-cli", "v42-auth-visual-qa");
const DEFAULT_BASELINE = path.join(FRONTEND_ROOT, "qa", "v42-auth-visual-baseline.json");

function parseArgs(argv) {
  const options = {
    artifactRoot: DEFAULT_ARTIFACT_ROOT,
    baselinePath: DEFAULT_BASELINE,
    timeoutMs: 180000,
    readinessTimeoutMs: 30000,
    strict: false,
    updateBaseline: false,
    skipV41: false,
    fromReport: "",
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === "--artifact-root" && next) {
      options.artifactRoot = path.resolve(next);
      index += 1;
    } else if (arg === "--baseline" && next) {
      options.baselinePath = path.resolve(next);
      index += 1;
    } else if (arg === "--timeout-ms" && next) {
      options.timeoutMs = Math.max(30000, Number(next) || 180000);
      index += 1;
    } else if (arg === "--readiness-timeout-ms" && next) {
      options.readinessTimeoutMs = Math.max(10000, Number(next) || 30000);
      index += 1;
    } else if (arg === "--from-report" && next) {
      options.fromReport = path.resolve(next);
      index += 1;
    } else if (arg === "--strict") {
      options.strict = true;
    } else if (arg === "--update-baseline") {
      options.updateBaseline = true;
    } else if (arg === "--skip-v41") {
      options.skipV41 = true;
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
  console.log(`AI ACQ V42 authenticated visual regression QA

Usage:
  npm run qa:v42 -- --json
  npm run qa:v42:update-baseline -- --json
  npm run qa:v42 -- --from-report <v41-report.json> --json

V42 runs or reads V41, extracts the authenticated business-workspace screenshot, computes a local visual fingerprint, and compares it with a baseline without executing live calls or sends.`);
}

function nowSlug() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function mkdirp(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(file, value) {
  await mkdirp(path.dirname(file));
  await fs.writeFile(file, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function parseJsonOutput(stdout) {
  const text = stdout || "";
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end < start) throw new Error("no JSON object found in command output");
  return JSON.parse(text.slice(start, end + 1));
}

function runV41(options, artifactDir) {
  if (options.fromReport) {
    return {
      command: `read ${options.fromReport}`,
      exitCode: 0,
      signal: null,
      durationMs: 0,
      parseError: "",
      report: JSON.parse(fsSync.readFileSync(options.fromReport, "utf8")),
      stdoutTail: "",
      stderrTail: "",
    };
  }
  if (options.skipV41) {
    return {
      command: "skip-v41",
      exitCode: 0,
      signal: null,
      durationMs: 0,
      parseError: "",
      report: null,
      stdoutTail: "",
      stderrTail: "",
    };
  }
  const args = [
    "scripts/auth-readiness-v41-qa.mjs",
    "--artifact-root",
    path.join(artifactDir, "v41"),
    "--timeout-ms",
    String(options.timeoutMs),
    "--readiness-timeout-ms",
    String(options.readinessTimeoutMs),
    "--json",
  ];
  const startedAt = Date.now();
  const result = spawnSync(process.execPath, args, {
    cwd: FRONTEND_ROOT,
    env: process.env,
    encoding: "utf8",
    timeout: Math.max(options.timeoutMs + 60000, 240000),
    maxBuffer: 120 * 1024 * 1024,
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

function readUInt32(buffer, offset) {
  return buffer.readUInt32BE(offset);
}

function paeth(left, up, upLeft) {
  const p = left + up - upLeft;
  const pa = Math.abs(p - left);
  const pb = Math.abs(p - up);
  const pc = Math.abs(p - upLeft);
  if (pa <= pb && pa <= pc) return left;
  if (pb <= pc) return up;
  return upLeft;
}

function decodePng(file) {
  const buffer = fsSync.readFileSync(file);
  const signature = "89504e470d0a1a0a";
  if (buffer.subarray(0, 8).toString("hex") !== signature) {
    throw new Error("not a PNG file");
  }
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const idat = [];
  while (offset < buffer.length) {
    const length = readUInt32(buffer, offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;
    if (type === "IHDR") {
      width = readUInt32(data, 0);
      height = readUInt32(data, 4);
      bitDepth = data[8];
      colorType = data[9];
    } else if (type === "IDAT") {
      idat.push(data);
    } else if (type === "IEND") {
      break;
    }
  }
  if (bitDepth !== 8) throw new Error(`unsupported PNG bit depth ${bitDepth}`);
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : colorType === 0 ? 1 : 0;
  if (!channels) throw new Error(`unsupported PNG color type ${colorType}`);
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const pixels = Buffer.alloc(width * height * channels);
  let inputOffset = 0;
  let outputOffset = 0;
  let prior = Buffer.alloc(stride);
  for (let row = 0; row < height; row += 1) {
    const filter = raw[inputOffset];
    inputOffset += 1;
    const scanline = raw.subarray(inputOffset, inputOffset + stride);
    inputOffset += stride;
    const current = Buffer.alloc(stride);
    for (let index = 0; index < stride; index += 1) {
      const x = scanline[index];
      const left = index >= channels ? current[index - channels] : 0;
      const up = prior[index] || 0;
      const upLeft = index >= channels ? prior[index - channels] || 0 : 0;
      if (filter === 0) current[index] = x;
      else if (filter === 1) current[index] = (x + left) & 255;
      else if (filter === 2) current[index] = (x + up) & 255;
      else if (filter === 3) current[index] = (x + Math.floor((left + up) / 2)) & 255;
      else if (filter === 4) current[index] = (x + paeth(left, up, upLeft)) & 255;
      else throw new Error(`unsupported PNG filter ${filter}`);
    }
    current.copy(pixels, outputOffset);
    outputOffset += stride;
    prior = current;
  }
  return { width, height, channels, pixels };
}

function rgbToHueBucket(red, green, blue) {
  const r = red / 255;
  const g = green / 255;
  const b = blue / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  if (delta < 0.08) return -1;
  let hue = 0;
  if (max === r) hue = ((g - b) / delta) % 6;
  else if (max === g) hue = (b - r) / delta + 2;
  else hue = (r - g) / delta + 4;
  const degrees = (hue * 60 + 360) % 360;
  return Math.floor(degrees / 10);
}

function luma(red, green, blue) {
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function pixelAt(image, x, y) {
  const index = (y * image.width + x) * image.channels;
  if (image.channels === 1) {
    const value = image.pixels[index];
    return [value, value, value, 255];
  }
  const red = image.pixels[index];
  const green = image.pixels[index + 1];
  const blue = image.pixels[index + 2];
  const alpha = image.channels === 4 ? image.pixels[index + 3] : 255;
  return [red, green, blue, alpha];
}

function averageHash(image, size = 16) {
  const values = [];
  for (let gy = 0; gy < size; gy += 1) {
    for (let gx = 0; gx < size; gx += 1) {
      const x0 = Math.floor((gx * image.width) / size);
      const x1 = Math.max(x0 + 1, Math.floor(((gx + 1) * image.width) / size));
      const y0 = Math.floor((gy * image.height) / size);
      const y1 = Math.max(y0 + 1, Math.floor(((gy + 1) * image.height) / size));
      let total = 0;
      let count = 0;
      for (let y = y0; y < y1; y += Math.max(1, Math.floor((y1 - y0) / 4))) {
        for (let x = x0; x < x1; x += Math.max(1, Math.floor((x1 - x0) / 4))) {
          const [red, green, blue] = pixelAt(image, x, y);
          total += luma(red, green, blue);
          count += 1;
        }
      }
      values.push(total / Math.max(1, count));
    }
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return values.map((value) => (value >= mean ? "1" : "0")).join("");
}

function hammingRatio(left, right) {
  if (!left || !right || left.length !== right.length) return 1;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) diff += 1;
  }
  return Number((diff / left.length).toFixed(3));
}

function fingerprintPng(file) {
  const image = decodePng(file);
  const totalPixels = image.width * image.height;
  const step = Math.max(1, Math.floor(Math.sqrt(totalPixels / 150000)));
  const colors = new Set();
  const hueBuckets = new Map();
  let visiblePixels = 0;
  let lumaSum = 0;
  let lumaSqSum = 0;
  let minLuma = 255;
  let maxLuma = 0;
  let edgeSum = 0;
  let edgeCount = 0;
  for (let y = 0; y < image.height; y += step) {
    for (let x = 0; x < image.width; x += step) {
      const [red, green, blue, alpha] = pixelAt(image, x, y);
      if (alpha <= 4) continue;
      visiblePixels += 1;
      const luminosity = luma(red, green, blue);
      lumaSum += luminosity;
      lumaSqSum += luminosity * luminosity;
      minLuma = Math.min(minLuma, luminosity);
      maxLuma = Math.max(maxLuma, luminosity);
      colors.add(`${red >> 4}:${green >> 4}:${blue >> 4}`);
      const hue = rgbToHueBucket(red, green, blue);
      if (hue >= 0) hueBuckets.set(hue, (hueBuckets.get(hue) || 0) + 1);
      if (x + step < image.width) {
        const [rightRed, rightGreen, rightBlue] = pixelAt(image, x + step, y);
        edgeSum += Math.abs(luminosity - luma(rightRed, rightGreen, rightBlue));
        edgeCount += 1;
      }
      if (y + step < image.height) {
        const [downRed, downGreen, downBlue] = pixelAt(image, x, y + step);
        edgeSum += Math.abs(luminosity - luma(downRed, downGreen, downBlue));
        edgeCount += 1;
      }
    }
  }
  const meanLuminance = lumaSum / Math.max(1, visiblePixels);
  const variance = lumaSqSum / Math.max(1, visiblePixels) - meanLuminance * meanLuminance;
  const hueCount = Array.from(hueBuckets.values()).reduce((sum, value) => sum + value, 0);
  const topHue = Math.max(0, ...hueBuckets.values());
  return {
    width: image.width,
    height: image.height,
    sampledPixels: visiblePixels,
    visibleRatio: Number((visiblePixels / Math.ceil(image.width / step) / Math.ceil(image.height / step)).toFixed(3)),
    meanLuminance: Number(meanLuminance.toFixed(2)),
    luminanceStd: Number(Math.sqrt(Math.max(0, variance)).toFixed(2)),
    luminanceSpread: Number((maxLuma - minLuma).toFixed(2)),
    colorDiversity: colors.size,
    topHueRatio: Number((topHue / Math.max(1, hueCount)).toFixed(3)),
    edgeEnergy: Number((edgeSum / Math.max(1, edgeCount)).toFixed(2)),
    hash: averageHash(image),
  };
}

function addIssue(issues, severity, code, detail) {
  issues.push({ severity, code, detail });
}

function inspectVisual(metrics, baseline, options) {
  const issues = [];
  if (metrics.width < 1000 || metrics.height < 800) {
    addIssue(issues, "high", "AUTH_SCREENSHOT_TOO_SMALL", `${metrics.width}x${metrics.height}`);
  }
  if (metrics.visibleRatio < 0.98) {
    addIssue(issues, "high", "AUTH_SCREENSHOT_TRANSPARENT_OR_EMPTY", `visibleRatio=${metrics.visibleRatio}`);
  }
  if (metrics.luminanceStd < 12 || metrics.luminanceSpread < 28) {
    addIssue(issues, "high", "AUTH_SCREENSHOT_LOW_INFORMATION", `std=${metrics.luminanceStd}, spread=${metrics.luminanceSpread}`);
  }
  if (metrics.colorDiversity < 80) {
    addIssue(issues, "high", "AUTH_SCREENSHOT_LOW_COLOR_DIVERSITY", `colorDiversity=${metrics.colorDiversity}`);
  }
  if (metrics.edgeEnergy < 2) {
    addIssue(issues, "high", "AUTH_SCREENSHOT_LOW_EDGE_ENERGY", `edgeEnergy=${metrics.edgeEnergy}`);
  }
  if (metrics.topHueRatio > 0.88 && metrics.colorDiversity < 90) {
    addIssue(issues, "medium", "AUTH_SCREENSHOT_ONE_HUE_RISK", `topHueRatio=${metrics.topHueRatio}, colorDiversity=${metrics.colorDiversity}`);
  }
  if (!baseline) {
    addIssue(issues, options.strict ? "high" : "medium", "AUTH_VISUAL_BASELINE_MISSING", "run qa:v42:update-baseline after reviewing the screenshot");
    return issues;
  }
  if (metrics.width !== baseline.metrics.width) {
    addIssue(issues, "high", "AUTH_VISUAL_WIDTH_DRIFT", `${baseline.metrics.width}->${metrics.width}`);
  }
  const heightDelta = Math.abs(metrics.height - baseline.metrics.height);
  if (heightDelta > Math.max(120, baseline.metrics.height * 0.15)) {
    addIssue(issues, "medium", "AUTH_VISUAL_HEIGHT_DRIFT", `${baseline.metrics.height}->${metrics.height}`);
  }
  const hashDrift = hammingRatio(metrics.hash, baseline.metrics.hash);
  if (hashDrift > 0.6) {
    addIssue(issues, "high", "AUTH_VISUAL_HASH_DRIFT_HIGH", `hamming=${hashDrift}`);
  } else if (hashDrift > 0.42) {
    addIssue(issues, "medium", "AUTH_VISUAL_HASH_DRIFT_MEDIUM", `hamming=${hashDrift}`);
  }
  if (Math.abs(metrics.meanLuminance - baseline.metrics.meanLuminance) > 36) {
    addIssue(issues, "medium", "AUTH_VISUAL_LUMINANCE_DRIFT", `${baseline.metrics.meanLuminance}->${metrics.meanLuminance}`);
  }
  if (metrics.luminanceStd < baseline.metrics.luminanceStd * 0.45) {
    addIssue(issues, "high", "AUTH_VISUAL_STRUCTURE_COLLAPSED", `std ${baseline.metrics.luminanceStd}->${metrics.luminanceStd}`);
  }
  if (metrics.colorDiversity < baseline.metrics.colorDiversity * 0.45) {
    addIssue(issues, "high", "AUTH_VISUAL_COLOR_COLLAPSED", `colorDiversity ${baseline.metrics.colorDiversity}->${metrics.colorDiversity}`);
  }
  if (metrics.edgeEnergy < baseline.metrics.edgeEnergy * 0.35) {
    addIssue(issues, "high", "AUTH_VISUAL_EDGE_COLLAPSED", `edgeEnergy ${baseline.metrics.edgeEnergy}->${metrics.edgeEnergy}`);
  }
  return issues;
}

function summarize(report, options) {
  const high = report.visual.issues.filter((issue) => issue.severity === "high").length;
  const medium = report.visual.issues.filter((issue) => issue.severity === "medium").length;
  const low = report.visual.issues.filter((issue) => issue.severity === "low").length;
  const baselineReady = Boolean(report.visual.baseline?.path);
  const v41Ready = Boolean(report.v41?.summary?.status === "pass" && report.v41?.summary?.authenticatedReplayReady);
  const score = Math.max(0, 100 - high * 35 - medium * 12 - low * 4);
  const status = high > 0 || (options.strict && medium > 0) || !v41Ready ? "fail" : medium > 0 ? "warn" : "pass";
  report.summary = {
    status,
    score,
    firstBlocker: !v41Ready
      ? "v41_authenticated_readiness"
      : high > 0 || (options.strict && medium > 0)
        ? report.visual.issues[0]?.code || "visual_regression"
        : "",
    visualReady: high === 0,
    baselineReady,
    v41Ready,
    high,
    medium,
    low,
    liveActionsExecuted: false,
    noLiveSideEffects: true,
  };
}

function renderMarkdown(report) {
  const lines = [];
  lines.push("# V42 Authenticated Visual QA");
  lines.push("");
  lines.push(`Status: ${report.summary.status}`);
  lines.push(`Score: ${report.summary.score}/100`);
  lines.push(`First blocker: ${report.summary.firstBlocker || "n/a"}`);
  lines.push(`V41 report: ${report.v41?.artifacts?.report || "n/a"}`);
  lines.push(`Screenshot: ${report.visual.screenshot || "n/a"}`);
  lines.push(`Baseline: ${report.visual.baseline?.path || "n/a"}`);
  lines.push(`Metrics: ${JSON.stringify({ width: report.visual.metrics.width, height: report.visual.metrics.height, colorDiversity: report.visual.metrics.colorDiversity, edgeEnergy: report.visual.metrics.edgeEnergy, hashDrift: report.visual.hashDrift })}`);
  if (report.visual.issues.length) {
    lines.push("");
    lines.push("## Issues");
    for (const issue of report.visual.issues) lines.push(`- ${issue.severity} ${issue.code}: ${issue.detail}`);
  }
  lines.push("");
  lines.push("## Guarantees");
  lines.push("- No live call executed.");
  lines.push("- No private message sent.");
  lines.push("- No account change or production write executed.");
  lines.push("- Visual baseline stores only derived image metrics, not auth tokens or storageState content.");
  return `${lines.join("\n")}\n`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const artifactDir = path.join(options.artifactRoot, nowSlug());
  await mkdirp(artifactDir);

  const v41Run = runV41(options, artifactDir);
  const v41 = v41Run.report;
  const screenshot = v41?.v17?.authReplay?.screenshot || "";
  if (!screenshot) throw new Error("V41 report does not include an authenticated replay screenshot");
  const metrics = fingerprintPng(screenshot);
  let baseline = null;
  if (fsSync.existsSync(options.baselinePath)) {
    baseline = JSON.parse(fsSync.readFileSync(options.baselinePath, "utf8"));
  }
  if (options.updateBaseline) {
    baseline = {
      version: "V42-auth-visual-baseline/v1",
      generatedAt: new Date().toISOString(),
      metrics,
    };
    await writeJson(options.baselinePath, baseline);
  }
  const issues = inspectVisual(metrics, baseline, options);
  const hashDrift = baseline?.metrics?.hash ? hammingRatio(metrics.hash, baseline.metrics.hash) : null;
  const report = {
    version: "V42",
    generatedAt: new Date().toISOString(),
    project: "ai_acq/frontend",
    target: {
      baseline: options.baselinePath,
      strict: options.strict,
      updateBaseline: options.updateBaseline,
      fromReport: options.fromReport,
      skipV41: options.skipV41,
    },
    researchBasis: [
      "Playwright authentication guidance supports storageState reuse for authenticated tests.",
      "Playwright visual comparison guidance motivates screenshot baselines for UI regression detection.",
      "Playwright project-dependency guidance motivates trace-visible setup evidence before dependent checks.",
    ],
    v41Run: {
      command: v41Run.command,
      exitCode: v41Run.exitCode,
      durationMs: v41Run.durationMs,
      parseError: v41Run.parseError,
      stdoutTail: v41Run.stdoutTail,
      stderrTail: v41Run.stderrTail,
    },
    v41: v41
      ? {
          summary: v41.summary || {},
          artifacts: v41.artifacts || {},
          v40: v41.v40 ? { summary: v41.v40.summary || {}, artifacts: v41.v40.artifacts || {} } : null,
          v17: v41.v17
            ? {
                summary: v41.v17.summary || {},
                authReplay: v41.v17.authReplay || {},
                artifacts: {
                  report: v41.v17.artifacts?.report || "",
                  trace: v41.v17.artifacts?.trace || "",
                },
              }
            : null,
        }
      : null,
    visual: {
      screenshot,
      metrics,
      baseline: baseline ? { path: options.baselinePath, generatedAt: baseline.generatedAt || "", sourceReport: baseline.sourceReport || "" } : null,
      hashDrift,
      issues,
    },
    liveActionsExecuted: false,
    artifacts: {
      root: artifactDir,
      report: path.join(artifactDir, "report.json"),
      markdown: path.join(artifactDir, "auth-visual.md"),
      baseline: options.baselinePath,
    },
    summary: {},
  };
  summarize(report, options);
  await writeJson(report.artifacts.report, report);
  await fs.writeFile(report.artifacts.markdown, renderMarkdown(report), "utf8");

  if (options.json) {
    console.log(JSON.stringify(report, null, 2));
  } else {
    console.log(`V42 QA ${report.summary.status.toUpperCase()} score=${report.summary.score}/100 blocker=${report.summary.firstBlocker || "n/a"}`);
    console.log(`Report: ${report.artifacts.report}`);
    console.log(`Screenshot: ${report.visual.screenshot}`);
    console.log(`Baseline: ${report.visual.baseline?.path || "n/a"}`);
  }
  process.exit(report.summary.status === "fail" ? 1 : 0);
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
