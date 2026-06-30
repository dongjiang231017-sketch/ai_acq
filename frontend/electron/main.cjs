const { app, BrowserWindow, ipcMain, webContents } = require("electron");
const path = require("path");

const PLATFORM_SESSION_DOMAINS = {
  "美团": ["meituan.com"],
  "饿了么": ["ele.me", "eleme.cn", "eleme.io"],
  "抖音": ["douyin.com", "bytedance.com", "snssdk.com"],
  "视频号": ["channels.weixin.qq.com", "weixin.qq.com", "wx.qq.com"],
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
        authorProfileUrl: "",
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
