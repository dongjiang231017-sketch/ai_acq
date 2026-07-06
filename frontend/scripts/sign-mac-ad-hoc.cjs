const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

function run(command, args, options = {}) {
  try {
    execFileSync(command, args, { stdio: "inherit" });
  } catch (error) {
    if (options.optional) {
      console.warn(`[ai-acq] optional command failed: ${command} ${args.join(" ")}`);
      return;
    }
    throw error;
  }
}

module.exports = async function signMacAdHoc(context) {
  if (context.electronPlatformName !== "darwin") {
    return;
  }

  const productFilename =
    context.packager.appInfo.productFilename ||
    context.packager.appInfo.productName ||
    "商家AI获客客户端";
  const appPath = path.join(context.appOutDir, `${productFilename}.app`);

  if (!fs.existsSync(appPath)) {
    throw new Error(`macOS app bundle not found: ${appPath}`);
  }

  console.log(`[ai-acq] clearing macOS extended attributes: ${appPath}`);
  run("/usr/bin/xattr", ["-cr", appPath], { optional: true });

  console.log(`[ai-acq] ad-hoc signing macOS app bundle: ${appPath}`);
  run("/usr/bin/codesign", [
    "--force",
    "--deep",
    "--sign",
    "-",
    "--timestamp=none",
    appPath,
  ]);

  console.log(`[ai-acq] verifying macOS app bundle signature: ${appPath}`);
  run("/usr/bin/codesign", [
    "--verify",
    "--deep",
    "--strict",
    "--verbose=2",
    appPath,
  ]);
};
