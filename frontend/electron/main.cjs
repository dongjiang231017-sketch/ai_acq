const { app, BrowserWindow, dialog, ipcMain, shell, webContents } = require("electron");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const { Readable } = require("stream");
const { pipeline } = require("stream/promises");
const packageJson = require("../package.json");
const { createAsteriskSidecar } = require("./asterisk-sidecar.cjs");

const REMOTE_FRONTEND_URL = process.env.AI_ACQ_REMOTE_FRONTEND_URL || "http://101.132.63.159/ai-acq/";
const REMOTE_FRONTEND_TIMEOUT_MS =
  Number.parseInt(process.env.AI_ACQ_REMOTE_FRONTEND_TIMEOUT_MS || "8000", 10) || 8000;
const REMOTE_FRONTEND_RENDER_WAIT_MS =
  Number.parseInt(process.env.AI_ACQ_REMOTE_FRONTEND_RENDER_WAIT_MS || "1200", 10) || 1200;
const UPDATE_MANIFEST_URL = process.env.AI_ACQ_UPDATE_MANIFEST_URL || "http://101.132.63.159/ai-acq-downloads/latest.json";

const PLATFORM_SESSION_DOMAINS = {
  "美团": ["meituan.com"],
  "饿了么": ["ele.me", "eleme.cn", "eleme.io"],
  "抖音": ["douyin.com", "bytedance.com", "snssdk.com"],
  "视频号": ["channels.weixin.qq.com", "weixin.qq.com", "wx.qq.com"],
};

const SESSION_MARKERS = ["auth", "login", "passport", "session", "sid", "sso", "ticket", "token", "uid", "user"];

const userDataDir = process.env.AI_ACQ_DESKTOP_USER_DATA_DIR
  ? path.resolve(process.env.AI_ACQ_DESKTOP_USER_DATA_DIR)
  : app.getPath("userData");
app.setPath("userData", userDataDir);
const asteriskSidecar = createAsteriskSidecar({ userDataDir });

function compareVersions(left, right) {
  const leftParts = String(left || "0").split(".").map((part) => Number.parseInt(part, 10) || 0);
  const rightParts = String(right || "0").split(".").map((part) => Number.parseInt(part, 10) || 0);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const delta = (leftParts[index] || 0) - (rightParts[index] || 0);
    if (delta !== 0) return delta;
  }
  return 0;
}

function absoluteDownloadUrl(pathname) {
  if (!pathname) return "";
  if (/^https?:\/\//i.test(pathname)) return pathname;
  return new URL(pathname, UPDATE_MANIFEST_URL).toString();
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "pipe", ...options });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} exited ${code}: ${stderr || stdout}`));
    });
  });
}

function quitForUpdate() {
  setTimeout(() => {
    app.quit();
    const forcedExit = setTimeout(() => app.exit(0), 3000);
    forcedExit.unref?.();
  }, 500);
}

function selectUpdateFile(manifest) {
  return selectUpdateAsset(manifest)?.path || "";
}

function selectUpdateAsset(manifest, { preferAutoInstall = false } = {}) {
  const files = manifest?.files || {};
  const candidates = [];
  if (process.platform === "darwin") {
    const archLabel = process.arch === "arm64" ? "MacArm64" : "MacX64";
    const dmgKey = process.arch === "arm64" ? "macArm64Dmg" : "macX64Dmg";
    const zipKey = process.arch === "arm64" ? "macArm64Zip" : "macX64Zip";
    const dmgCandidate = { key: dmgKey, path: files[`stable${archLabel}Dmg`] || files[dmgKey] };
    const zipCandidate = { key: zipKey, path: files[`stable${archLabel}Zip`] || files[zipKey] };
    candidates.push(...(preferAutoInstall ? [zipCandidate, dmgCandidate] : [dmgCandidate, zipCandidate]));
  } else if (process.platform === "win32") {
    candidates.push({ key: "windowsX64Setup", path: files.stableWindowsX64Setup || files.windowsX64Setup });
  } else {
    candidates.push({ key: "linuxAppImage", path: files.stableLinuxAppImage || files.linuxAppImage });
  }
  const selected = candidates.find((candidate) => candidate.path);
  if (!selected) return null;
  return {
    ...selected,
    url: absoluteDownloadUrl(selected.path),
    sha256: manifest?.sha256?.[selected.key] || "",
  };
}

async function fetchUpdateManifest() {
  const response = await fetch(`${UPDATE_MANIFEST_URL}?t=${Date.now()}`, {
    headers: { Accept: "application/json", "Cache-Control": "no-cache" },
  });
  if (!response.ok) throw new Error(`更新清单请求失败：HTTP ${response.status}`);
  return response.json();
}

async function sha256File(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(filePath);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("error", reject);
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

async function downloadUpdateAsset(asset, version) {
  if (!asset?.url) throw new Error("缺少客户端更新下载地址");
  const updatesDir = path.join(userDataDir, "updates", String(version || Date.now()));
  await fs.promises.mkdir(updatesDir, { recursive: true });
  const fileName = path.basename(new URL(asset.url).pathname) || `ai-acq-client-update-${Date.now()}`;
  const filePath = path.join(updatesDir, fileName);
  try {
    const response = await fetch(`${asset.url}?t=${Date.now()}`, {
      headers: { "Cache-Control": "no-cache" },
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(filePath));
  } catch (error) {
    await fs.promises.rm(filePath, { force: true });
    if (process.platform !== "darwin") {
      const reason = error instanceof Error ? error.message : "网络错误";
      throw new Error(`客户端下载失败：${reason}`);
    }
    try {
      await runCommand("/usr/bin/curl", [
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "20",
        "--max-time",
        "900",
        "--retry",
        "2",
        "--output",
        filePath,
        asset.url,
      ]);
    } catch (curlError) {
      const reason = curlError instanceof Error ? curlError.message : "网络错误";
      throw new Error(`客户端下载失败，fetch/curl 都没有成功：${reason}`);
    }
  }
  const digest = await sha256File(filePath);
  if (asset.sha256 && digest !== asset.sha256) {
    await fs.promises.rm(filePath, { force: true });
    throw new Error("客户端下载校验失败，已停止安装。");
  }
  return {
    filePath,
    sha256: digest,
    bytes: (await fs.promises.stat(filePath)).size,
  };
}

function currentMacAppBundlePath() {
  const executable = process.execPath || "";
  const marker = ".app/Contents/MacOS/";
  const index = executable.indexOf(marker);
  return index >= 0 ? executable.slice(0, index + ".app".length) : "";
}

function targetMacAppBundlePath(currentApp) {
  if (currentApp.startsWith("/Volumes/") || currentApp.includes("/AppTranslocation/")) {
    return path.join("/Applications", path.basename(currentApp));
  }
  return currentApp;
}

async function findFirstAppBundle(rootDir) {
  const entries = await fs.promises.readdir(rootDir, { withFileTypes: true });
  for (const entry of entries) {
    const itemPath = path.join(rootDir, entry.name);
    if (entry.isDirectory() && entry.name.endsWith(".app")) return itemPath;
  }
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.endsWith(".app")) continue;
    const nested = await findFirstAppBundle(path.join(rootDir, entry.name));
    if (nested) return nested;
  }
  return "";
}

async function canWriteDirectory(dir) {
  try {
    await fs.promises.access(dir, fs.constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

async function installMacZipUpdate(zipPath, version) {
  const currentApp = currentMacAppBundlePath();
  if (!currentApp) throw new Error("无法定位当前客户端 App，不能自动替换。");
  const targetApp = targetMacAppBundlePath(currentApp);
  const runningFromDiskImage = currentApp !== targetApp;
  const stagingDir = path.join(path.dirname(zipPath), `staged-${version || Date.now()}`);
  await fs.promises.rm(stagingDir, { recursive: true, force: true });
  await fs.promises.mkdir(stagingDir, { recursive: true });
  await runCommand("/usr/bin/ditto", ["-x", "-k", zipPath, stagingDir]);
  const sourceApp = await findFirstAppBundle(stagingDir);
  if (!sourceApp) throw new Error("更新包内没有找到客户端 App。");

  const scriptPath = path.join(path.dirname(zipPath), "install-ai-acq-update.sh");
  const logPath = path.join(path.dirname(zipPath), "install-ai-acq-update.log");
  const script = `#!/bin/bash
set -euo pipefail
APP_PID=${process.pid}
CURRENT=${shellQuote(currentApp)}
TARGET=${shellQuote(targetApp)}
SOURCE=${shellQuote(sourceApp)}
STAGING=${shellQuote(stagingDir)}
ZIP=${shellQuote(zipPath)}
LOG=${shellQuote(logPath)}
{
  echo "AI ACQ update start $(date)"
  echo "current=$CURRENT"
  echo "target=$TARGET"
  echo "source=$SOURCE"
  WAITED=0
  while /bin/kill -0 "$APP_PID" 2>/dev/null; do
    if [ "$WAITED" -ge 60 ]; then
      echo "Timed out waiting for old client process $APP_PID to exit"
      exit 1
    fi
    sleep 1
    WAITED=$((WAITED + 1))
  done
  BACKUP=""
  restore_backup() {
    if [ -n "$BACKUP" ] && [ -d "$BACKUP" ] && [ ! -d "$TARGET" ]; then
      mv "$BACKUP" "$TARGET" || true
    fi
  }
  trap 'CODE=$?; if [ "$CODE" -ne 0 ]; then echo "AI ACQ update failed with code $CODE at $(date)"; restore_backup; exit "$CODE"; fi' EXIT
  if [ -d "$TARGET" ]; then
    BACKUP="$TARGET.backup-$(date +%Y%m%d%H%M%S)"
    mv "$TARGET" "$BACKUP"
  fi
  /usr/bin/ditto "$SOURCE" "$TARGET"
  /usr/bin/xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true
  /usr/bin/open -n "$TARGET"
  rm -rf "$BACKUP" "$STAGING" "$ZIP" "$0" 2>/dev/null || true
  echo "AI ACQ update done $(date)"
} >> "$LOG" 2>&1
`;
  await fs.promises.writeFile(scriptPath, script, { mode: 0o755 });
  const targetParent = path.dirname(targetApp);
  const writable = await canWriteDirectory(targetParent);
  if (writable) {
    spawn("/bin/bash", [scriptPath], { detached: true, stdio: "ignore" }).unref();
  } else {
    const command = `/bin/bash ${shellQuote(scriptPath)}`;
    spawn("/usr/bin/osascript", ["-e", `do shell script ${JSON.stringify(command)} with administrator privileges`], {
      detached: true,
      stdio: "ignore",
    }).unref();
  }
  quitForUpdate();
  return {
    status: "installing",
    message: writable
      ? runningFromDiskImage
        ? "更新包已校验，客户端将安装到“应用程序”并自动重启。"
        : "更新包已校验，客户端将自动重启完成升级。"
      : "更新包已校验，系统可能会要求输入本机密码以替换应用。",
    installerPath: scriptPath,
    logPath,
  };
}

async function installDownloadedUpdate(downloaded, asset, version) {
  const lowerPath = downloaded.filePath.toLowerCase();
  if (process.platform === "darwin") {
    if (lowerPath.endsWith(".zip")) return installMacZipUpdate(downloaded.filePath, version);
    await shell.openPath(downloaded.filePath);
    return { status: "manual", message: "已打开更新包，请按系统提示完成升级。", installerPath: downloaded.filePath };
  }
  if (process.platform === "win32") {
    spawn(downloaded.filePath, ["/S"], { detached: true, stdio: "ignore" }).unref();
    quitForUpdate();
    return { status: "installing", message: "更新包已校验，正在启动 Windows 安装程序。", installerPath: downloaded.filePath };
  }
  await shell.openPath(downloaded.filePath || asset.url);
  return { status: "manual", message: "已打开更新包，请按系统提示完成升级。", installerPath: downloaded.filePath };
}

async function installClientUpdate({ owner = null } = {}) {
  const currentVersion = app.getVersion();
  const manifest = await fetchUpdateManifest();
  const updateAvailable = compareVersions(manifest.version, currentVersion) > 0;
  if (!updateAvailable) {
    return {
      status: "up-to-date",
      currentVersion,
      latestVersion: manifest.version || "",
      message: "当前客户端已是最新版本。",
    };
  }
  const asset = selectUpdateAsset(manifest, { preferAutoInstall: true });
  if (!asset?.url) throw new Error("更新清单里没有适合当前系统的安装包。");
  const downloaded = await downloadUpdateAsset(asset, manifest.version);
  const installResult = await installDownloadedUpdate(downloaded, asset, manifest.version);
  if (owner && installResult.status === "manual") {
    await dialog.showMessageBox(owner, {
      type: "info",
      title: "更新包已打开",
      message: "请按系统提示完成升级",
      detail: installResult.message,
    });
  }
  return {
    ...installResult,
    currentVersion,
    latestVersion: manifest.version || "",
    latestRevision: manifest.revision || "",
    updateUrl: asset.url,
    sha256: downloaded.sha256,
    bytes: downloaded.bytes,
  };
}

async function checkClientUpdate({ prompt = false, owner = null } = {}) {
  const currentVersion = app.getVersion();
  const manifest = await fetchUpdateManifest();
  const asset = selectUpdateAsset(manifest);
  const autoInstallAsset = selectUpdateAsset(manifest, { preferAutoInstall: true });
  const updateUrl = asset?.url || "";
  const updateAvailable = compareVersions(manifest.version, currentVersion) > 0;
  const result = {
    currentVersion,
    latestVersion: manifest.version || "",
    latestRevision: manifest.revision || "",
    updateAvailable,
    updateUrl,
    autoInstallSupported: Boolean(autoInstallAsset?.url),
    manifestUrl: UPDATE_MANIFEST_URL,
    remoteFrontendUrl: REMOTE_FRONTEND_URL,
    onlineFrontendEnabled: app.isPackaged && process.env.AI_ACQ_DESKTOP_REMOTE_FRONTEND === "true",
    appName: packageJson.productName || packageJson.name || app.getName(),
    message: updateAvailable
      ? `发现客户端 ${manifest.version}，当前 ${currentVersion}。`
      : "当前客户端已是最新。",
  };

  if (prompt && updateAvailable && updateUrl) {
    const dialogOptions = {
      type: "info",
      title: "发现新版本",
      message: "发现新版本客户端",
      detail: `${result.message}\n\n可以在客户端内下载并校验更新包，安装完成后会自动重启客户端。`,
      buttons: ["立即在线升级", "打开下载", "稍后"],
      defaultId: 0,
      cancelId: 2,
    };
    const { response } = owner
      ? await dialog.showMessageBox(owner, dialogOptions)
      : await dialog.showMessageBox(dialogOptions);
    if (response === 0) {
      try {
        await installClientUpdate({ owner });
      } catch (error) {
        const message = error instanceof Error ? error.message : "在线升级失败。";
        const fallback = owner
          ? await dialog.showMessageBox(owner, {
              type: "error",
              title: "在线升级失败",
              message,
              detail: "可以打开下载地址手动完成本次更新。",
              buttons: ["打开下载", "稍后"],
              defaultId: 0,
              cancelId: 1,
            })
          : await dialog.showMessageBox({
              type: "error",
              title: "在线升级失败",
              message,
              detail: "可以打开下载地址手动完成本次更新。",
              buttons: ["打开下载", "稍后"],
              defaultId: 0,
              cancelId: 1,
            });
        if (fallback.response === 0) await shell.openExternal(updateUrl);
      }
    } else if (response === 1) {
      await shell.openExternal(updateUrl);
    }
  }

  return result;
}

function localFrontendFile() {
  return path.join(__dirname, "..", "dist", "index.html");
}

async function loadUrlWithTimeout(window, url, timeoutMs) {
  let timeoutId = null;
  const loadPromise = window.loadURL(url);
  loadPromise.catch(() => {});
  try {
    await Promise.race([
      loadPromise,
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => {
          reject(new Error(`远程前端加载超过 ${timeoutMs}ms`));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

async function remoteFrontendRendered(window) {
  if (REMOTE_FRONTEND_RENDER_WAIT_MS > 0) {
    await new Promise((resolve) => setTimeout(resolve, REMOTE_FRONTEND_RENDER_WAIT_MS));
  }
  return window.webContents.executeJavaScript(
    `(() => {
      const root = document.getElementById("root");
      if (!root) return true;
      if (root.children.length > 0) return true;
      return document.body && document.body.innerText.trim().length > 0;
    })()`,
    true,
  );
}

async function loadCustomerFrontend(window) {
  const explicitFrontendUrl = String(process.env.AI_ACQ_FRONTEND_URL || "").trim();
  if (explicitFrontendUrl) {
    await window.loadURL(explicitFrontendUrl);
    return { mode: "explicit", url: explicitFrontendUrl };
  }

  const remoteEnabled = process.env.AI_ACQ_DESKTOP_REMOTE_FRONTEND === "true";
  if (app.isPackaged && remoteEnabled) {
    try {
      await loadUrlWithTimeout(window, REMOTE_FRONTEND_URL, REMOTE_FRONTEND_TIMEOUT_MS);
      const rendered = await remoteFrontendRendered(window);
      if (!rendered) throw new Error("远程前端加载后没有渲染内容");
      return { mode: "remote", url: REMOTE_FRONTEND_URL };
    } catch (error) {
      console.error("[ai-acq] remote frontend load failed, falling back to bundled dist:", error);
      window.webContents.stop();
    }
  }

  const file = localFrontendFile();
  await window.loadFile(file);
  return { mode: "bundled", url: file };
}

function domainsForPlatform(platform) {
  return PLATFORM_SESSION_DOMAINS[platform] ?? [];
}

function hostFromUrl(value) {
  try {
    return new URL(value).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function domainMatches(host, domains) {
  const normalizedHost = String(host || "").toLowerCase().replace(/^\./, "");
  return domains.some((domain) => normalizedHost === domain || normalizedHost.endsWith(`.${domain}`));
}

function looksLikeSessionKey(value) {
  const normalizedValue = String(value || "").toLowerCase();
  return SESSION_MARKERS.some((marker) => normalizedValue.includes(marker));
}

function cookieHasLoginMarker(cookie, domains, currentHost) {
  const cookieHost = String(cookie.domain || currentHost || "").toLowerCase().replace(/^\./, "");
  return domainMatches(cookieHost, domains) && looksLikeSessionKey(cookie.name) && Boolean(cookie.value);
}

async function inspectPageStorage(targetContents) {
  try {
    return await targetContents.executeJavaScript(
      `(() => {
        const markers = ${JSON.stringify(SESSION_MARKERS)};
        const hasMarker = (value) => markers.some((marker) => String(value || "").toLowerCase().includes(marker));
        const readStorage = (storage) => {
          try {
            for (let index = 0; index < storage.length; index += 1) {
              const key = storage.key(index);
              const value = key ? storage.getItem(key) : "";
              if (hasMarker(key) || hasMarker(value)) return true;
            }
          } catch (_) {
            return false;
          }
          return false;
        };
        const text = String(document.body?.innerText || "").toLowerCase().slice(0, 12000);
        const hasLogoutElement = Boolean(
          document.querySelector('[href*="logout"], [href*="signout"], [class*="avatar"], [class*="user"], [class*="profile"]')
        );
        const hasChineseLoginSignal = /(退出|个人中心|我的主页|我的订单|消息|私信|创作者服务|账号设置)/.test(text) && !/(立即登录|登录\\/注册|请登录)/.test(text);
        return {
          url: window.location.href,
          title: document.title,
          hasStorageEvidence: readStorage(window.localStorage) || readStorage(window.sessionStorage),
          hasPageLoginSignal: hasLogoutElement || hasChineseLoginSignal
        };
      })()`,
      true,
    );
  } catch {
    return {
      url: targetContents.getURL(),
      title: targetContents.getTitle(),
      hasStorageEvidence: false,
      hasPageLoginSignal: false,
    };
  }
}

function commentCaptureScript(platform) {
  return `(() => {
    const platform = ${JSON.stringify(platform)};
    const cleanText = (value) => String(value || "")
      .replace(/[\\u200b\\u200c\\u200d\\ufeff]/g, "")
      .replace(/\\s+/g, " ")
      .trim();
    const lineText = (value) => String(value || "")
      .split(/\\n+/)
      .map((line) => cleanText(line))
      .filter(Boolean);
    const markerPattern = /(comment|reply|review|remark|message|comment-item|commentlist|评论|留言|回复|互动)/i;
    const authorPattern = /(author|nickname|nick|name|user|avatar|用户名|昵称|作者)/i;
    const actionPattern = /^(回复|点赞|赞|转发|分享|收藏|展开|收起|更多|举报|删除|置顶|全部回复|查看回复|写评论|发表评论|登录|关注)$/;
    const uiPattern = /(首页|推荐|搜索|发布|消息|私信|登录后|扫码|验证码|隐私政策|用户协议|打开 App|打开微信|客户端下载|创作者服务平台)/;
    const seen = new Set();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const descriptor = (element) => [
      element.tagName,
      element.id,
      typeof element.className === "string" ? element.className : "",
      element.getAttribute("role") || "",
      element.getAttribute("aria-label") || "",
      Object.keys(element.dataset || {}).join(" "),
    ].join(" ");
    const readCount = (text, keywords) => {
      const escaped = keywords.join("|");
      const match = text.match(new RegExp("(" + escaped + ")\\\\s*([0-9][0-9,.万wW]*)"));
      if (!match) return 0;
      const raw = match[2].replace(/,/g, "").toLowerCase();
      const numeric = Number.parseFloat(raw.replace(/[万w]/g, ""));
      if (!Number.isFinite(numeric)) return 0;
      return /[万w]/.test(raw) ? Math.round(numeric * 10000) : Math.round(numeric);
    };
    const authorFrom = (element, lines) => {
      const authorNode = Array.from(element.querySelectorAll("*")).find((child) => {
        const info = descriptor(child);
        const text = cleanText(child.textContent);
        return authorPattern.test(info) && text.length >= 1 && text.length <= 40 && !actionPattern.test(text);
      });
      const authorText = cleanText(authorNode?.textContent);
      if (authorText) return authorText.slice(0, 60);
      const firstShortLine = lines.find((line) => line.length > 0 && line.length <= 24 && !actionPattern.test(line) && !uiPattern.test(line));
      return firstShortLine ? firstShortLine.slice(0, 60) : "";
    };
    const profileUrlFrom = (element) => {
      const anchors = [
        element.closest("a[href]"),
        ...Array.from(element.querySelectorAll("a[href]")),
        ...Array.from(element.parentElement?.querySelectorAll("a[href]") || []),
      ].filter(Boolean);
      const profilePattern = /(user|profile|author|creator|homepage|channel|个人主页|主页|sec_uid|web_rid|wxid|finder)/i;
      const blockedPattern = /(login|passport|comment|reply|share|javascript:|#)$/i;
      const videoPattern = /(\\/video\\/|aweme|modal_id|item|note|play|detail|search)/i;
      const scored = anchors
        .map((anchor) => {
          const href = cleanText(anchor.href || anchor.getAttribute("href"));
          const label = cleanText(anchor.textContent || anchor.getAttribute("aria-label") || anchor.getAttribute("title") || "");
          const info = descriptor(anchor);
          if (!href || blockedPattern.test(href)) return null;
          if (videoPattern.test(href) && !profilePattern.test(href) && !profilePattern.test(info)) return null;
          const score = (profilePattern.test(href) ? 3 : 0)
            + (profilePattern.test(info) ? 2 : 0)
            + (label.length > 0 && label.length <= 40 ? 1 : 0)
            + (/douyin\\.com|channels\\.weixin\\.qq\\.com|weixin\\.qq\\.com|wx\\.qq\\.com/i.test(href) ? 1 : 0);
          return score >= 2 ? { href, score } : null;
        })
        .filter(Boolean)
        .sort((left, right) => right.score - left.score);
      return scored[0]?.href || "";
    };
    const contentFrom = (lines, author) => {
      const meaningful = lines
        .filter((line) => line !== author)
        .filter((line) => line.length >= 2 && line.length <= 280)
        .filter((line) => !actionPattern.test(line))
        .filter((line) => !/^\\d{1,2}[:：]\\d{2}$/.test(line))
        .filter((line) => !/^\\d+\\s*(赞|回复|条回复)$/.test(line));
      const longest = meaningful.sort((left, right) => right.length - left.length)[0];
      return cleanText(longest || meaningful.join(" "));
    };
    const externalIdFrom = (element) => {
      const raw = element.getAttribute("data-id")
        || element.getAttribute("data-comment-id")
        || element.getAttribute("comment-id")
        || element.id
        || "";
      return cleanText(raw).slice(0, 120);
    };
    const elements = Array.from(document.querySelectorAll("article, li, section, div"));
    const comments = [];
    for (const element of elements) {
      if (!isVisible(element)) continue;
      const text = cleanText(element.innerText || element.textContent);
      if (text.length < 4 || text.length > 700) continue;
      if (seen.has(text)) continue;
      const lines = lineText(element.innerText || element.textContent).slice(0, 12);
      if (lines.length === 0 || lines.join("").length < 4) continue;
      const info = descriptor(element);
      const hasMarker = markerPattern.test(info);
      const isLeafLike = element.children.length <= 8 && text.length <= 360;
      const parentText = cleanText(element.parentElement?.innerText || "");
      const isDistinctBlock = !parentText || parentText.length > text.length * 1.35;
      const hasCommentText = lines.some((line) => line.length >= 4 && line.length <= 220 && !actionPattern.test(line) && !uiPattern.test(line));
      const score = (hasMarker ? 3 : 0)
        + (isLeafLike ? 1 : 0)
        + (isDistinctBlock ? 1 : 0)
        + (hasCommentText ? 1 : 0)
        + (/listitem|article/i.test(info) ? 1 : 0);
      if (score < 3) continue;
      const authorName = authorFrom(element, lines) || "平台评论用户";
      const content = contentFrom(lines, authorName);
      if (content.length < 2 || actionPattern.test(content) || uiPattern.test(content)) continue;
      const dedupeKey = cleanText(authorName + "|" + content);
      if (seen.has(dedupeKey)) continue;
      seen.add(text);
      seen.add(dedupeKey);
      comments.push({
        externalCommentId: externalIdFrom(element),
        authorName,
        authorProfileUrl: profileUrlFrom(element),
        content,
        videoUrl: window.location.href,
        likeCount: readCount(text, ["赞", "点赞", "like"]),
        replyCount: readCount(text, ["回复", "reply"]),
        rawPayload: {
          platform,
          tagName: element.tagName.toLowerCase(),
          className: typeof element.className === "string" ? element.className.slice(0, 180) : "",
          score,
          lines: lines.slice(0, 8),
        },
      });
      if (comments.length >= 80) break;
    }
    return {
      url: window.location.href,
      title: document.title,
      platform,
      comments,
    };
  })()`;
}

function clampInteger(value, fallback, min, max) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isHttpUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function platformSearchUrl(platform, keyword) {
  const query = String(keyword || "").trim();
  if (!query) return "";
  if (platform === "抖音") return `https://www.douyin.com/search/${encodeURIComponent(query)}?type=video`;
  return "";
}

function waitForWebContentsIdle(targetContents, timeoutMs = 12000) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      targetContents.removeListener("did-stop-loading", onStop);
      targetContents.removeListener("did-fail-load", onFail);
      resolve();
    };
    const onStop = () => setTimeout(finish, 800);
    const onFail = () => setTimeout(finish, 800);
    const timer = setTimeout(finish, timeoutMs);
    targetContents.once("did-stop-loading", onStop);
    targetContents.once("did-fail-load", onFail);
    if (!targetContents.isLoading()) setTimeout(finish, 800);
  });
}

function searchCurrentPageScript(keyword) {
  return `(() => {
    const keyword = ${JSON.stringify(keyword)};
    const cleanText = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const descriptor = (element) => [
      element.tagName,
      element.id,
      typeof element.className === "string" ? element.className : "",
      element.getAttribute("role") || "",
      element.getAttribute("aria-label") || "",
      element.getAttribute("placeholder") || "",
      element.getAttribute("title") || "",
    ].join(" ");
    const searchPattern = /(搜索|搜一搜|search|keyword|query)/i;
    const setNativeValue = (element, value) => {
      if (element.isContentEditable) {
        element.focus();
        element.textContent = value;
        element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        return;
      }
      const prototype = Object.getPrototypeOf(element);
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(element, value);
      else element.value = value;
      element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const candidates = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], [role="searchbox"], [role="textbox"]'))
      .filter(isVisible)
      .map((element) => {
        const info = descriptor(element);
        const score = (searchPattern.test(info) ? 4 : 0)
          + (element.tagName === "INPUT" ? 1 : 0)
          + (element.getAttribute("type") === "search" ? 3 : 0);
        return { element, score, info: cleanText(info).slice(0, 120) };
      })
      .sort((left, right) => right.score - left.score);
    const target = candidates[0]?.element;
    if (!target) {
      const button = Array.from(document.querySelectorAll("button, a, [role='button']")).find((element) => {
        if (!isVisible(element)) return false;
        return searchPattern.test(descriptor(element)) || searchPattern.test(cleanText(element.textContent));
      });
      if (button) {
        button.scrollIntoView({ block: "center", inline: "center" });
        button.click();
        return { ok: false, clickedSearchButton: true, message: "已打开搜索入口，请确认页面是否出现搜索框。" };
      }
      return { ok: false, message: "当前页未找到可填写的搜索框。" };
    }
    target.scrollIntoView({ block: "center", inline: "center" });
    setNativeValue(target, keyword);
    target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Enter", code: "Enter" }));
    target.dispatchEvent(new KeyboardEvent("keypress", { bubbles: true, cancelable: true, key: "Enter", code: "Enter" }));
    target.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, cancelable: true, key: "Enter", code: "Enter" }));
    const form = target.closest("form");
    if (form) form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    return { ok: true, message: "已填写关键词并触发搜索。", target: candidates[0]?.info || "" };
  })()`;
}

function openFirstVideoResultScript(platform) {
  return `(() => {
    const platform = ${JSON.stringify(platform)};
    const cleanText = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const descriptor = (element) => [
      element.tagName,
      element.id,
      typeof element.className === "string" ? element.className : "",
      element.getAttribute("role") || "",
      element.getAttribute("aria-label") || "",
      element.getAttribute("title") || "",
      Object.keys(element.dataset || {}).join(" "),
    ].join(" ");
    const blockedPattern = /(login|passport|download|协议|隐私|帮助|setting|message|chat|inbox)/i;
    const videoPattern = /(\\/video\\/|modal_id|aweme|item|note|detail|play|feed|video|作品|播放|评论|点赞)/i;
    const elements = Array.from(document.querySelectorAll("a[href], article, li, section, div[role='button'], button, [data-e2e], [data-testid]"));
    const candidates = elements
      .filter(isVisible)
      .map((element) => {
        const anchor = element.matches?.("a[href]") ? element : element.querySelector?.("a[href]");
        const href = cleanText(anchor?.href || element.getAttribute?.("href") || "");
        const text = cleanText(element.innerText || element.textContent).slice(0, 220);
        const info = descriptor(element);
        if (blockedPattern.test(href) || blockedPattern.test(info)) return null;
        const hasMedia = Boolean(element.querySelector?.("video, img, canvas, picture")) || /VIDEO|IMG/.test(element.tagName);
        const score = (videoPattern.test(href) ? 5 : 0)
          + (videoPattern.test(info) ? 3 : 0)
          + (videoPattern.test(text) ? 2 : 0)
          + (hasMedia ? 2 : 0)
          + (href && /douyin\\.com|channels\\.weixin\\.qq\\.com|weixin\\.qq\\.com|wx\\.qq\\.com/i.test(href) ? 1 : 0)
          + (text.length > 8 && text.length < 220 ? 1 : 0);
        return score >= 4 ? { element, anchor, href, text, score } : null;
      })
      .filter(Boolean)
      .sort((left, right) => right.score - left.score);
    const selected = candidates[0];
    if (!selected) return { ok: false, message: "没有找到可打开的视频搜索结果。", platform };
    const clickable = selected.anchor || selected.element;
    clickable.scrollIntoView({ block: "center", inline: "center" });
    const beforeUrl = window.location.href;
    clickable.click();
    return {
      ok: true,
      message: "已打开搜索结果视频。",
      platform,
      beforeUrl,
      href: selected.href || "",
      text: selected.text.slice(0, 120),
      score: selected.score,
    };
  })()`;
}

function scrollCommentsScript(rounds) {
  return `(async () => {
    const rounds = ${rounds};
    const cleanText = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clickExpandButtons = () => {
      const pattern = /(展开|更多评论|查看回复|加载更多|全部回复|more|reply|comments?)/i;
      let clicked = 0;
      for (const element of Array.from(document.querySelectorAll("button, a, [role='button'], span, div"))) {
        if (clicked >= 8) break;
        if (!isVisible(element)) continue;
        const text = cleanText(element.innerText || element.textContent || element.getAttribute("aria-label") || element.getAttribute("title"));
        if (!text || text.length > 24 || !pattern.test(text)) continue;
        element.scrollIntoView({ block: "center", inline: "center" });
        element.click();
        clicked += 1;
      }
      return clicked;
    };
    const scrollTargets = () => {
      const targetPattern = /(comment|reply|review|list|feed|评论|回复|留言|互动)/i;
      return Array.from(document.querySelectorAll("main, section, aside, div, ul"))
        .filter((element) => isVisible(element) && element.scrollHeight > element.clientHeight + 80)
        .map((element) => {
          const info = [
            element.id,
            typeof element.className === "string" ? element.className : "",
            element.getAttribute("role") || "",
            element.getAttribute("aria-label") || "",
            cleanText(element.innerText || "").slice(0, 80),
          ].join(" ");
          const score = (targetPattern.test(info) ? 3 : 0) + Math.min(3, Math.floor((element.scrollHeight - element.clientHeight) / 600));
          return { element, score };
        })
        .filter((item) => item.score > 0)
        .sort((left, right) => right.score - left.score)
        .slice(0, 4)
        .map((item) => item.element);
    };
    let expandClicks = 0;
    for (let index = 0; index < rounds; index += 1) {
      expandClicks += clickExpandButtons();
      const targets = scrollTargets();
      for (const target of targets) target.scrollBy({ top: Math.max(360, target.clientHeight * 0.85), behavior: "instant" });
      window.scrollBy({ top: Math.max(520, window.innerHeight * 0.75), behavior: "instant" });
      await wait(750);
    }
    return {
      ok: true,
      rounds,
      expandClicks,
      url: window.location.href,
      title: document.title,
      scrollY: window.scrollY,
      height: document.documentElement.scrollHeight,
    };
  })()`;
}

function fillDirectMessageScript(message, options = {}) {
  const allowSend = Boolean(options.allowSend);
  const confirmTimeoutMs = clampInteger(options.confirmTimeoutMs, 3500, 500, 15000);
  const selectors =
    options.selectors && typeof options.selectors === "object"
      ? {
          riskCheckSelector: String(options.selectors.riskCheckSelector || "").trim(),
          messageButtonSelector: String(options.selectors.messageButtonSelector || "").trim(),
          inputSelector: String(options.selectors.inputSelector || "").trim(),
          sendButtonSelector: String(options.selectors.sendButtonSelector || "").trim(),
          sentSuccessSelector: String(options.selectors.sentSuccessSelector || "").trim(),
        }
      : {};
  return `(async () => {
    const message = ${JSON.stringify(message)};
    const allowSend = ${allowSend ? "true" : "false"};
    const confirmTimeoutMs = ${confirmTimeoutMs};
    const selectors = ${JSON.stringify(selectors)};
    const cleanText = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const isVisible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const descriptor = (element) => [
      element.tagName,
      element.id,
      typeof element.className === "string" ? element.className : "",
      element.getAttribute("role") || "",
      element.getAttribute("aria-label") || "",
      element.getAttribute("placeholder") || "",
      element.getAttribute("title") || "",
      cleanText(element.textContent || "").slice(0, 40),
    ].join(" ");
    const notDisabled = (element) => !element.disabled && element.getAttribute("aria-disabled") !== "true";
    const queryVisible = (selector) => {
      if (!selector) return [];
      try {
        return Array.from(document.querySelectorAll(selector)).filter((element) => isVisible(element) && notDisabled(element));
      } catch {
        return [];
      }
    };
    const clickSelector = (selector) => {
      const selected = queryVisible(selector)[0];
      if (!selected) return false;
      selected.scrollIntoView({ block: "center", inline: "center" });
      selected.click();
      return true;
    };
    const selectorText = (selector) => {
      const element = queryVisible(selector)[0];
      return element ? cleanText(element.innerText || element.textContent || element.getAttribute("aria-label") || element.getAttribute("title") || "") : "";
    };
    const visibleClickables = () => Array.from(document.querySelectorAll("button, a, [role='button'], div, span"))
        .filter((element) => isVisible(element) && notDisabled(element))
        .map((element) => ({
          element,
          label: cleanText(element.innerText || element.textContent || element.getAttribute("aria-label") || element.getAttribute("title") || ""),
          info: cleanText(descriptor(element)),
        }));
    const clickByPattern = (pattern) => {
      const candidates = visibleClickables()
        .map((item) => ({ ...item, text: cleanText([item.label, item.info].join(" ")) }))
        .filter((item) => pattern.test(item.text))
        .sort((left, right) => left.text.length - right.text.length);
      const selected = candidates[0]?.element;
      if (!selected) return false;
      selected.scrollIntoView({ block: "center", inline: "center" });
      selected.click();
      return true;
    };
    const findSendButton = () => {
      const sendTextPattern = /^(发送|send)$/i;
      const sendInfoPattern = /(send|submit|发送)/i;
      return visibleClickables()
        .map((item) => {
          const label = cleanText(item.label);
          const score = (sendTextPattern.test(label) ? 6 : 0)
            + (/发送/.test(label) && label.length <= 8 ? 4 : 0)
            + (sendInfoPattern.test(item.info) ? 2 : 0)
            - (/(发消息|发送消息|私信|联系|评论|回复)/.test(label) && !sendTextPattern.test(label) ? 4 : 0);
          return { ...item, score };
        })
        .filter((item) => item.score > 0)
        .sort((left, right) => right.score - left.score || left.label.length - right.label.length)[0]?.element || null;
    };
    const setNativeValue = (element, value) => {
      element.focus();
      if (element.isContentEditable) {
        element.textContent = value;
        element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        return;
      }
      const prototype = Object.getPrototypeOf(element);
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(element, value);
      else element.value = value;
      element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const inputValue = (element) => element.isContentEditable ? cleanText(element.textContent) : cleanText(element.value);
    const pageRiskText = () => {
      const text = cleanText(document.body?.innerText || "").slice(0, 20000);
      const match = text.match(/(验证码|安全验证|滑动验证|登录后|请登录|操作频繁|发送失败|发送过快|风险|限制|异常|稍后再试|verify|captcha|too frequent|failed)/i);
      return match?.[0] || "";
    };
    const openedMessageEntry = clickSelector(selectors.messageButtonSelector) || clickByPattern(/(私信|发消息|发送消息|联系|聊天|message|chat|dm)/i);
    if (openedMessageEntry) await wait(1200);
    const configuredInput = queryVisible(selectors.inputSelector)[0] || null;
    const input = configuredInput || Array.from(document.querySelectorAll("textarea, input, [contenteditable='true'], [role='textbox']"))
      .filter((element) => isVisible(element) && notDisabled(element))
      .map((element) => {
        const info = descriptor(element);
        const score = (/(私信|消息|输入|回复|message|chat|send|textarea)/i.test(info) ? 4 : 0)
          + (element.isContentEditable ? 2 : 0)
          + (element.tagName === "TEXTAREA" ? 3 : 0)
          + (element.tagName === "INPUT" ? 1 : 0);
        return { element, score, info };
      })
      .sort((left, right) => right.score - left.score)[0]?.element;
    if (!input) {
      const risk = selectorText(selectors.riskCheckSelector) || pageRiskText();
      return {
        ok: false,
        status: risk ? "send-blocked" : "no-input",
        openedMessageEntry,
        sent: false,
        sendClicked: false,
        sentConfirmed: false,
        receiptStatus: risk ? "blocked" : "missing",
        receiptMessage: risk || "未找到可填写的私信输入框。",
        message: risk
          ? \`平台疑似风控或登录拦截：\${risk}\`
          : openedMessageEntry ? "已打开私信入口，但未找到可填写的输入框。" : "未找到私信入口或输入框。",
        url: window.location.href,
        title: document.title,
      };
    }
    setNativeValue(input, message);
    await wait(500);
    if (!allowSend) {
      return {
        ok: true,
        status: "draft-ready",
        openedMessageEntry,
        filled: true,
        sent: false,
        sendClicked: false,
        sentConfirmed: false,
        receiptStatus: "draft",
        receiptMessage: "已填写草稿，未点击发送。",
        outgoingContent: message,
        message: "已填写私信草稿，按安全策略停在发送前。",
        url: window.location.href,
        title: document.title,
      };
    }
    const sendButton = queryVisible(selectors.sendButtonSelector)[0] || findSendButton();
    if (!sendButton) {
      return {
        ok: false,
        status: "send-button-missing",
        openedMessageEntry,
        filled: true,
        sent: false,
        sendClicked: false,
        sentConfirmed: false,
        receiptStatus: "missing",
        receiptMessage: "未找到可点击的发送按钮。",
        outgoingContent: message,
        message: "已填写草稿，但未找到可点击的发送按钮。",
        url: window.location.href,
        title: document.title,
      };
    }
    sendButton.scrollIntoView({ block: "center", inline: "center" });
    sendButton.click();
    await wait(confirmTimeoutMs);
    const selectorRisk = selectorText(selectors.riskCheckSelector);
    const receiptText = selectorText(selectors.sentSuccessSelector);
    const risk = selectorRisk || pageRiskText();
    const remainingValue = inputValue(input);
    const sentConfirmed = !risk && (Boolean(receiptText) || remainingValue !== message);
    const status = risk ? "send-blocked" : sentConfirmed ? "sent-confirmed" : "send-clicked-unconfirmed";
    return {
      ok: !risk,
      status,
      openedMessageEntry,
      filled: true,
      sent: !risk,
      sendClicked: true,
      sentConfirmed,
      receiptStatus: risk ? "blocked" : sentConfirmed ? "confirmed" : "unconfirmed",
      receiptMessage: risk || receiptText || (sentConfirmed ? "已观察到发送回执或输入框状态变化。" : "未在会话记录中确认发送回执。"),
      outgoingContent: message,
      message: risk
        ? \`平台疑似拦截发送：\${risk}\`
        : sentConfirmed
          ? "已点击发送按钮，并观察到输入框清空/状态变化。"
          : "已点击发送按钮，但未能确认平台是否完成发送。",
      url: window.location.href,
      title: document.title,
    };
  })()`;
}

async function runCommentAutomation(payload) {
  const targetContents = webContents.fromId(Number(payload?.webContentsId));
  const platform = String(payload?.platform || "");
  const keyword = String(payload?.keyword || "").trim();
  const sourceUrl = String(payload?.sourceUrl || "").trim();
  const sourceType = String(payload?.sourceType || "").trim();
  const dmMessage = String(payload?.dmMessage || "").trim();
  const scrollRounds = clampInteger(payload?.scrollRounds, 6, 1, 20);
  const maxAuthors = clampInteger(payload?.maxAuthors, 3, 0, 12);
  const sendIntervalSeconds = clampInteger(payload?.sendIntervalSeconds, 45, 0, 600);
  const allowSend = Boolean(payload?.allowSend);
  const selectors = payload?.selectors && typeof payload.selectors === "object" ? payload.selectors : {};
  const steps = [];
  const dmActions = [];
  const addStep = (name, status, message, extra = {}) => {
    steps.push({ name, status, message, ...extra });
  };

  if (!targetContents) {
    return {
      url: "",
      title: "",
      platform,
      comments: [],
      steps,
      dmActions,
      error: "未找到客户端内置登录页，请先打开平台登录页。",
    };
  }

  try {
    const canLoadSourceUrl = isHttpUrl(sourceUrl);
    if (canLoadSourceUrl) {
      await targetContents.loadURL(sourceUrl);
      await waitForWebContentsIdle(targetContents);
      addStep("open_source", "done", "已打开配置的来源页面。", { url: sourceUrl });
    } else if (keyword) {
      const searchUrl = platformSearchUrl(platform, keyword);
      if (searchUrl) {
        await targetContents.loadURL(searchUrl);
        await waitForWebContentsIdle(targetContents);
        addStep("search_keyword", "done", "已打开平台关键词搜索页。", { keyword, url: searchUrl });
      } else {
        const searchResult = await targetContents.executeJavaScript(searchCurrentPageScript(keyword), true);
        await delay(1800);
        await waitForWebContentsIdle(targetContents, 8000);
        addStep("search_keyword", searchResult?.ok ? "done" : "warning", searchResult?.message || "已尝试在当前页搜索关键词。", {
          keyword,
        });
      }
    } else {
      addStep("search_keyword", "skipped", "未填写关键词或来源 URL，沿用当前内置页。");
    }

    if ((!canLoadSourceUrl && keyword) || (sourceType && sourceType !== "视频链接" && sourceType !== "视频")) {
      const openResult = await targetContents.executeJavaScript(openFirstVideoResultScript(platform), true);
      await delay(1800);
      await waitForWebContentsIdle(targetContents, 10000);
      addStep("open_video", openResult?.ok ? "done" : "warning", openResult?.message || "已尝试打开第一个视频结果。", {
        href: openResult?.href || "",
        text: openResult?.text || "",
      });
    } else {
      addStep("open_video", "skipped", canLoadSourceUrl ? "已直接打开配置的视频/主页 URL。" : "当前页作为采集页。");
    }

    const scrollResult = await targetContents.executeJavaScript(scrollCommentsScript(scrollRounds), true);
    addStep("scroll_comments", "done", `已滚动加载评论 ${scrollRounds} 轮。`, {
      expandClicks: scrollResult?.expandClicks || 0,
      url: scrollResult?.url || targetContents.getURL(),
    });

    const capture = await targetContents.executeJavaScript(commentCaptureScript(platform), true);
    const comments = Array.isArray(capture?.comments) ? capture.comments.slice(0, 120) : [];
    addStep("capture_comments", "done", `已从当前内置页识别 ${comments.length} 条评论。`);

    const profileTargets = [];
    const seenProfiles = new Set();
    for (const comment of comments) {
      const profileUrl = String(comment?.authorProfileUrl || "").trim();
      const authorName = String(comment?.authorName || "评论用户").trim();
      if (!profileUrl || seenProfiles.has(profileUrl) || !isHttpUrl(profileUrl)) continue;
      seenProfiles.add(profileUrl);
      profileTargets.push({ authorName, profileUrl });
      if (profileTargets.length >= maxAuthors) break;
    }

    if (!dmMessage || maxAuthors <= 0) {
      addStep("prepare_dm", "skipped", "未配置私信文案或作者数为 0，跳过主页/私信自动化。");
    } else if (profileTargets.length === 0) {
      addStep("prepare_dm", "warning", "当前评论 DOM 未识别到作者主页链接，无法自动进入主页私信。");
    } else {
      for (const [index, target] of profileTargets.entries()) {
        try {
          if (allowSend && index > 0 && sendIntervalSeconds > 0) {
            await delay(sendIntervalSeconds * 1000);
          }
          await targetContents.loadURL(target.profileUrl);
          await waitForWebContentsIdle(targetContents, 10000);
          await delay(900);
          const dmResult = await targetContents.executeJavaScript(
            fillDirectMessageScript(dmMessage, { allowSend, confirmTimeoutMs: 4000, selectors }),
            true,
          );
          dmActions.push({
            authorName: target.authorName,
            profileUrl: target.profileUrl,
            status: dmResult?.status || "unknown",
            sent: Boolean(dmResult?.sent),
            sendClicked: Boolean(dmResult?.sendClicked),
            sentConfirmed: Boolean(dmResult?.sentConfirmed),
            receiptStatus: dmResult?.receiptStatus || "",
            receiptMessage: dmResult?.receiptMessage || "",
            outgoingContent: dmResult?.outgoingContent || dmMessage,
            message: dmResult?.message || "",
            url: dmResult?.url || targetContents.getURL(),
          });
        } catch (error) {
          dmActions.push({
            authorName: target.authorName,
            profileUrl: target.profileUrl,
            status: "failed",
            sent: false,
            sendClicked: false,
            sentConfirmed: false,
            receiptStatus: "failed",
            receiptMessage: error instanceof Error ? error.message : "进入作者主页或填写私信失败",
            outgoingContent: dmMessage,
            message: error instanceof Error ? error.message : "进入作者主页或填写私信失败",
            url: targetContents.getURL(),
          });
        }
      }
      const sentCount = dmActions.filter((action) => action.sent).length;
      const draftCount = dmActions.filter((action) => action.status === "draft-ready").length;
      addStep(
        "prepare_dm",
        dmActions.some((action) => action.status === "failed") ? "warning" : "done",
        allowSend
          ? `已处理 ${dmActions.length} 个作者主页，点击发送 ${sentCount} 条，发送间隔 ${sendIntervalSeconds} 秒。`
          : `已处理 ${dmActions.length} 个作者主页，填好 ${draftCount} 条草稿并停在发送前。`,
      );
    }

    return {
      url: capture?.url || targetContents.getURL(),
      title: capture?.title || targetContents.getTitle(),
      platform,
      comments,
      steps,
      dmActions,
    };
  } catch (error) {
    return {
      url: targetContents.getURL(),
      title: targetContents.getTitle(),
      platform,
      comments: [],
      steps,
      dmActions,
      error: error instanceof Error ? error.message : "自动化执行失败",
    };
  }
}

ipcMain.handle("dm-login:inspect", async (_event, payload) => {
  const targetContents = webContents.fromId(Number(payload?.webContentsId));
  if (!targetContents) {
    return {
      url: "",
      title: "",
      hasCookieEvidence: false,
      hasStorageEvidence: false,
      hasPageLoginSignal: false,
    };
  }

  const platform = String(payload?.platform || "");
  const domains = domainsForPlatform(platform);
  const pageEvidence = await inspectPageStorage(targetContents);
  const currentUrl = pageEvidence.url || targetContents.getURL();
  const currentHost = hostFromUrl(currentUrl);
  const cookies = domains.length ? await targetContents.session.cookies.get({}) : [];
  const hasCookieEvidence = cookies.some((cookie) => cookieHasLoginMarker(cookie, domains, currentHost));

  return {
    url: currentUrl,
    title: pageEvidence.title || targetContents.getTitle(),
    hasCookieEvidence,
    hasStorageEvidence: Boolean(pageEvidence.hasStorageEvidence),
    hasPageLoginSignal: Boolean(pageEvidence.hasPageLoginSignal),
  };
});

ipcMain.handle("comment-intercept:capture", async (_event, payload) => {
  const targetContents = webContents.fromId(Number(payload?.webContentsId));
  const platform = String(payload?.platform || "");
  if (!targetContents) {
    return {
      url: "",
      title: "",
      platform,
      comments: [],
      error: "未找到客户端内置登录页，请先打开平台登录页。",
    };
  }

  try {
    const capture = await targetContents.executeJavaScript(commentCaptureScript(platform), true);
    return {
      url: capture?.url || targetContents.getURL(),
      title: capture?.title || targetContents.getTitle(),
      platform,
      comments: Array.isArray(capture?.comments) ? capture.comments.slice(0, 80) : [],
    };
  } catch (error) {
    return {
      url: targetContents.getURL(),
      title: targetContents.getTitle(),
      platform,
      comments: [],
      error: error instanceof Error ? error.message : "读取当前内置页失败",
    };
  }
});

ipcMain.handle("comment-intercept:automate", async (_event, payload) => runCommentAutomation(payload));

ipcMain.handle("asterisk-sidecar:status", async () => asteriskSidecar.status());

ipcMain.handle("asterisk-sidecar:start", async () => asteriskSidecar.start());

ipcMain.handle("asterisk-sidecar:stop", async () => asteriskSidecar.stop());

ipcMain.handle("app-info:get", async () => ({
  appName: packageJson.productName || packageJson.name || app.getName(),
  version: app.getVersion(),
  remoteFrontendUrl: REMOTE_FRONTEND_URL,
  manifestUrl: UPDATE_MANIFEST_URL,
  onlineFrontendEnabled: app.isPackaged && process.env.AI_ACQ_DESKTOP_REMOTE_FRONTEND === "true",
}));

ipcMain.handle("app-update:check", async (event, payload = {}) =>
  checkClientUpdate({
    prompt: Boolean(payload?.prompt),
    owner: BrowserWindow.fromWebContents(event.sender),
  }),
);

ipcMain.handle("app-update:install", async (event) =>
  installClientUpdate({
    owner: BrowserWindow.fromWebContents(event.sender),
  }),
);

ipcMain.handle("app-update:open", async (_event, url) => {
  const targetUrl = String(url || "").trim();
  if (!targetUrl) return { ok: false, message: "缺少下载地址" };
  await shell.openExternal(targetUrl);
  return { ok: true };
});

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 980,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: "#f6faff",
    title: "商家AI获客客户端",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webviewTag: true,
    },
  });

  void loadCustomerFrontend(window).catch((error) => {
    console.error("[ai-acq] customer frontend load failed:", error);
    if (!window.isDestroyed()) {
      window.loadURL(
        `data:text/html;charset=utf-8,${encodeURIComponent(
          "<!doctype html><html><body style=\"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6faff;color:#20304a;padding:32px;\"><h2>客户端页面加载失败</h2><p>请检查网络后重新打开客户端，或联系交付人员重新安装最新客户端。</p></body></html>",
        )}`,
      );
    }
  });
}

app.whenReady().then(() => {
  createWindow();

  if (app.isPackaged && process.env.AI_ACQ_DISABLE_UPDATE_PROMPT !== "true") {
    setTimeout(() => {
      const owner = BrowserWindow.getAllWindows()[0] || null;
      void checkClientUpdate({ prompt: true, owner }).catch((error) => {
        console.warn("[ai-acq] update check failed:", error);
      });
    }, 5000);
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  void asteriskSidecar.stop();
});
