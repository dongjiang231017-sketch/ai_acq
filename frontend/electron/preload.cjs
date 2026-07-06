const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiAcqDesktop", {
  isDesktopClient: true,
  inspectDmLogin: (payload) => ipcRenderer.invoke("dm-login:inspect", payload),
  captureCommentIntercept: (payload) => ipcRenderer.invoke("comment-intercept:capture", payload),
  runCommentInterceptAutomation: (payload) => ipcRenderer.invoke("comment-intercept:automate", payload),
  getAsteriskSidecarStatus: () => ipcRenderer.invoke("asterisk-sidecar:status"),
  startAsteriskSidecar: () => ipcRenderer.invoke("asterisk-sidecar:start"),
  stopAsteriskSidecar: () => ipcRenderer.invoke("asterisk-sidecar:stop"),
  getAppInfo: () => ipcRenderer.invoke("app-info:get"),
  checkForClientUpdate: (payload) => ipcRenderer.invoke("app-update:check", payload),
  installClientUpdate: (payload) => ipcRenderer.invoke("app-update:install", payload),
  openClientUpdate: (url) => ipcRenderer.invoke("app-update:open", url),
});
