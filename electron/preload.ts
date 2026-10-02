import { contextBridge, ipcRenderer, webUtils } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  send: (msg: any) => ipcRenderer.invoke('ws:send', msg),
  onMessage: (callback: (msg: any) => void) => {
    ipcRenderer.on('ws:message', (_event, msg) => callback(msg))
  },
  removeMessageListener: () => {
    ipcRenderer.removeAllListeners('ws:message')
  },
  onStatus: (callback: (status: { connected: boolean }) => void) => {
    ipcRenderer.on('backend:status', (_event, status) => callback(status))
  },
  removeStatusListener: () => {
    ipcRenderer.removeAllListeners('backend:status')
  },
  requestStatus: () => ipcRenderer.send('backend:status:request'),
  window: {
    minimize: () => ipcRenderer.send('window:minimize'),
    maximize: () => ipcRenderer.send('window:maximize'),
    close: () => ipcRenderer.send('window:close'),
    focus: () => ipcRenderer.send('window:focus'),
  },
  openFiles: () => ipcRenderer.invoke('dialog:openFiles'),
  openDirectory: () => ipcRenderer.invoke('dialog:openDirectory'),
  getFilePath: (file: File) => webUtils.getPathForFile(file),
  getPath: (name: string) => ipcRenderer.invoke('app:getPath', name),
  shell: {
    open: (path: string) => ipcRenderer.invoke('shell:open', path),
    reveal: (path: string) => ipcRenderer.invoke('shell:reveal', path),
  },
  sync: {
    scan: (folderPath: string, lastSync: number) =>
      ipcRenderer.invoke('sync:scan', folderPath, lastSync),
  },
})
