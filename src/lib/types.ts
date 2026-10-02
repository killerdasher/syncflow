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
  targetDeviceId?: string
  verified?: boolean
  destPath?: string
  destFolder?: string
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
  maxConcurrent: number
}

export interface SyncFolder {
  localPath: string
  remoteDevice: string
  remotePath: string
  enabled: boolean
  lastSync: number
  /** Auto-sync interval in minutes: 0 = manual only, 1/5/15 */
  interval: number
}

export interface PinnedPeer {
  key: string
  name: string
  deviceId: string
  firstSeen: number
  lastSeen: number
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
      requestStatus: () => void
      window: {
        minimize: () => void
        maximize: () => void
        close: () => void
        focus: () => void
      }
      openFiles: () => Promise<FileItem[]>
      openDirectory: () => Promise<string | null>
      onTraySendFiles?: (callback: () => void) => void
      removeTraySendFilesListener?: () => void
      getFilePath: (file: File) => string
      getPath: (name: string) => Promise<string>
      shell: {
        open: (path: string) => Promise<string>
        reveal: (path: string) => Promise<boolean>
      }
      sync: {
        scan: (folderPath: string, lastSync: number) => Promise<
          { files: { path: string; name: string; size: number }[]; error?: string } | undefined
        >
      }
    }
  }
}
