export interface Device {
  id: string
  name: string
  mac: string
  ip: string
  os: 'windows' | 'linux' | 'macos' | 'android' | 'ios' | 'unknown'
  status: 'connected' | 'disconnected' | 'connecting'
  connectionType: 'lan' | 'wan'
  lastSeen: number
  icon: 'pc' | 'laptop' | 'phone' | 'tablet' | 'unknown'
  manual?: boolean
}

export interface Transfer {
  id: string
  fromDevice: string
  toDevice: string
  files: FileItem[]
  status: 'pending' | 'awaiting' | 'transferring' | 'completed' | 'failed' | 'cancelled'
  progress: number
  speed: number
  bytesTransferred: number
  totalBytes: number
  startTime: number
  endTime?: number
  error?: string
  targetIp?: string
  verified?: boolean
}

export interface FileItem {
  name: string
  path: string
  size: number
  type: string
  hash?: string
}

export interface Settings {
  deviceName: string
  autoAccept: boolean
  downloadPath: string
  syncFolders: SyncFolder[]
  relayServer: string
  relayToken: string
  encryptionEnabled: boolean
  maxConcurrentTransfers: number
  port: number
}

export interface SyncFolder {
  localPath: string
  remoteDevice: string
  remotePath: string
  enabled: boolean
  lastSync: number
}

export interface WsMessage {
  type: string
  [key: string]: any
}

export interface ChatMessage {
  id: string
  fromDevice: string
  deviceId: string
  text: string
  timestamp: number
  hash: string
  self: boolean
}

declare global {
  interface Window {
    electronAPI: {
      send: (msg: any) => Promise<boolean>
      onMessage: (callback: (msg: any) => void) => void
      removeMessageListener: () => void
      onStatus: (callback: (status: { connected: boolean }) => void) => void
      removeStatusListener: () => void
      window: {
        minimize: () => void
        maximize: () => void
        close: () => void
      }
      openFiles: () => Promise<FileItem[]>
      openDirectory: () => Promise<string | null>
      getFilePath: (file: File) => string
      getPath: (name: string) => Promise<string>
    }
  }
}
