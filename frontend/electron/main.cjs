const { app, BrowserWindow, ipcMain, webContents } = require("electron");
const path = require("path");

const PLATFORM_SESSION_DOMAINS = {
  "美团": ["meituan.com"],
  "饿了么": ["ele.me", "eleme.cn", "eleme.io"],
  "抖音": ["douyin.com", "bytedance.com", "snssdk.com"],
};

const SESSION_MARKERS = ["auth", "login", "passport", "session", "sid", "sso", "ticket", "token", "uid", "user"];

const userDataDir = path.join(__dirname, "..", ".electron-user-data");
app.setPath("userData", userDataDir);

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

  const frontendUrl = process.env.AI_ACQ_FRONTEND_URL;
  if (frontendUrl) {
    window.loadURL(frontendUrl);
  } else {
    window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
