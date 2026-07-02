const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const frontendRoot = path.resolve(__dirname, "..");
const platform = process.env.AI_ACQ_ASTERISK_RUNTIME_PLATFORM || process.platform;
const targetRoot = path.resolve(
  process.env.AI_ACQ_ASTERISK_RUNTIME_TARGET || path.join(frontendRoot, "electron", "asterisk", platform),
);
const mode = process.argv.includes("--copy") ? "copy" : "check";

function main() {
  if (mode === "copy") {
    const source = resolveSource();
    if (!source.binary) {
      fail(
        [
          "没有找到可复制的 Asterisk runtime。",
          "请设置 AI_ACQ_ASTERISK_RUNTIME_SOURCE=/path/to/asterisk-prefix，或设置 AI_ACQ_ASTERISK_BIN=/path/to/asterisk。",
          "macOS 开发机如果用 Homebrew，可先安装 Asterisk，再运行 npm run desktop:runtime:prepare。",
        ].join("\n"),
      );
    }
    copyRuntime(source);
  }

  const report = inspectRuntime(targetRoot);
  printReport(report);
  if (!report.ready) {
    fail("Asterisk runtime 不完整，不能打正式桌面安装包。");
  }
}

function resolveSource() {
  const explicitRoot = process.env.AI_ACQ_ASTERISK_RUNTIME_SOURCE
    ? path.resolve(process.env.AI_ACQ_ASTERISK_RUNTIME_SOURCE)
    : "";
  const explicitBinary = process.env.AI_ACQ_ASTERISK_BIN ? path.resolve(process.env.AI_ACQ_ASTERISK_BIN) : "";
  const systemBinary = commandPath("asterisk");
  const binary = [binaryInRoot(explicitRoot), explicitBinary, systemBinary].find((candidate) => isFile(candidate));
  const root = explicitRoot || rootFromBinary(binary);
  const modulesDir = process.env.AI_ACQ_ASTERISK_MODULE_DIR
    ? path.resolve(process.env.AI_ACQ_ASTERISK_MODULE_DIR)
    : findFirstDir([
        path.join(root, "lib", "asterisk", "modules"),
        path.join(root, "lib64", "asterisk", "modules"),
        path.join(path.dirname(path.dirname(binary || "")), "lib", "asterisk", "modules"),
        "/opt/homebrew/lib/asterisk/modules",
        "/usr/local/lib/asterisk/modules",
        "/usr/lib/asterisk/modules",
        "/usr/lib64/asterisk/modules",
      ]);
  const dataDir = findFirstDir([
    path.join(root, "share", "asterisk"),
    path.join(root, "var", "lib", "asterisk"),
    "/opt/homebrew/share/asterisk",
    "/usr/local/share/asterisk",
    "/usr/share/asterisk",
  ]);
  return { root, binary, modulesDir, dataDir };
}

function copyRuntime(source) {
  fs.rmSync(targetRoot, { recursive: true, force: true });
  fs.mkdirSync(path.join(targetRoot, "bin"), { recursive: true });
  fs.copyFileSync(source.binary, path.join(targetRoot, "bin", "asterisk"));
  fs.chmodSync(path.join(targetRoot, "bin", "asterisk"), 0o755);

  if (!source.modulesDir) {
    fail("找到了 Asterisk binary，但没有找到 modules 目录。请设置 AI_ACQ_ASTERISK_MODULE_DIR。");
  }
  copyDir(source.modulesDir, path.join(targetRoot, "lib", "asterisk", "modules"));

  if (source.dataDir) {
    copyDir(source.dataDir, path.join(targetRoot, "share", "asterisk"));
  }

  const dependencyReport = collectDependencyReport(source.binary);
  if (dependencyReport.length) {
    fs.writeFileSync(path.join(targetRoot, "DEPENDENCIES.txt"), dependencyReport.join("\n") + "\n");
  }
}

function inspectRuntime(root) {
  const binary = path.join(root, "bin", "asterisk");
  const modulesDir = path.join(root, "lib", "asterisk", "modules");
  const modules = isDir(modulesDir) ? fs.readdirSync(modulesDir).filter((name) => name.endsWith(".so")) : [];
  const requiredModules = ["app_audiosocket.so", "res_pjsip.so", "res_pjsip_outbound_registration.so", "chan_pjsip.so"];
  const missingModules = requiredModules.filter((name) => !modules.includes(name));
  return {
    root,
    platform,
    binary,
    binaryFound: isFile(binary),
    modulesDir,
    moduleCount: modules.length,
    missingModules,
    ready: isFile(binary) && modules.length > 0 && missingModules.length === 0,
  };
}

function printReport(report) {
  const lines = [
    `Asterisk runtime target: ${report.root}`,
    `platform: ${report.platform}`,
    `binary: ${report.binaryFound ? "PASS" : "FAIL"} ${report.binary}`,
    `modules: ${report.moduleCount > 0 ? "PASS" : "FAIL"} ${report.modulesDir} (${report.moduleCount})`,
    `required modules: ${report.missingModules.length ? `FAIL missing ${report.missingModules.join(", ")}` : "PASS"}`,
    `ready: ${report.ready ? "PASS" : "FAIL"}`,
  ];
  console.log(lines.join("\n"));
}

function binaryInRoot(root) {
  if (!root) return "";
  return [path.join(root, "bin", "asterisk"), path.join(root, "sbin", "asterisk")].find((candidate) => isFile(candidate)) || "";
}

function rootFromBinary(binary) {
  if (!binary) return "";
  const parent = path.dirname(binary);
  return path.basename(parent) === "bin" || path.basename(parent) === "sbin" ? path.dirname(parent) : parent;
}

function commandPath(command) {
  const result = spawnSync("sh", ["-lc", `command -v ${command}`], { encoding: "utf8" });
  if (result.status !== 0) return "";
  return String(result.stdout || "").trim().split("\n")[0] || "";
}

function collectDependencyReport(binary) {
  if (!isFile(binary)) return [];
  if (os.platform() === "darwin") {
    const result = spawnSync("otool", ["-L", binary], { encoding: "utf8" });
    return result.status === 0 ? String(result.stdout || "").split("\n").map((line) => line.trim()).filter(Boolean) : [];
  }
  if (os.platform() === "linux") {
    const result = spawnSync("ldd", [binary], { encoding: "utf8" });
    return result.status === 0 ? String(result.stdout || "").split("\n").map((line) => line.trim()).filter(Boolean) : [];
  }
  return [];
}

function findFirstDir(candidates) {
  return candidates.find((candidate) => isDir(candidate)) || "";
}

function copyDir(from, to) {
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.cpSync(from, to, { recursive: true, force: true, dereference: true });
}

function isFile(value) {
  try {
    return Boolean(value) && fs.statSync(value).isFile();
  } catch {
    return false;
  }
}

function isDir(value) {
  try {
    return Boolean(value) && fs.statSync(value).isDirectory();
  } catch {
    return false;
  }
}

function fail(message) {
  console.error(message);
  process.exit(1);
}

main();
