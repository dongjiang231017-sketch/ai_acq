const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aiAcqDesktop", {
  isDesktopClient: true,
  inspectDmLogin: (payload) => ipcRenderer.invoke("dm-login:inspect", payload),
});
