const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiAcqDesktop", {
  isDesktopClient: true,
  inspectDmLogin: (payload) => ipcRenderer.invoke("dm-login:inspect", payload),
  captureCommentIntercept: (payload) => ipcRenderer.invoke("comment-intercept:capture", payload),
});
