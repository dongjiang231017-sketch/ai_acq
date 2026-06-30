const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiAcqDesktop", {
  isDesktopClient: true,
  inspectDmLogin: (payload) => ipcRenderer.invoke("dm-login:inspect", payload),
  captureCommentIntercept: (payload) => ipcRenderer.invoke("comment-intercept:capture", payload),
  runCommentInterceptAutomation: (payload) => ipcRenderer.invoke("comment-intercept:automate", payload),
  getAsteriskSidecarStatus: () => ipcRenderer.invoke("asterisk-sidecar:status"),
  startAsteriskSidecar: () => ipcRenderer.invoke("asterisk-sidecar:start"),
  stopAsteriskSidecar: () => ipcRenderer.invoke("asterisk-sidecar:stop"),
});
