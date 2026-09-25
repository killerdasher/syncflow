export const APP_NAME = 'SyncFlow'
export const APP_VERSION = '1.0.0'

export const DEFAULT_PORT = 18973
export const WS_RECONNECT_DELAY = 3000
export const DEVICE_TIMEOUT = 30000

export const CHUNK_SIZE = 65536
export const MAX_CONCURRENT_TRANSFERS = 4

export const MDNS_SERVICE = '_syncflow._tcp.local.'

export const OS_ICONS: Record<string, 'pc' | 'laptop' | 'phone' | 'tablet' | 'unknown'> = {
  windows: 'pc',
  linux: 'laptop',
  macos: 'laptop',
  darwin: 'laptop',
  android: 'phone',
  ios: 'phone',
  unknown: 'unknown',
}

export const OS_LABELS: Record<string, string> = {
  windows: 'Windows',
  linux: 'Linux',
  macos: 'macOS',
  darwin: 'macOS',
  android: 'Android',
  ios: 'iOS',
  unknown: 'Unknown',
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export function formatSpeed(bytesPerSec: number): string {
  return formatBytes(bytesPerSec) + '/s'
}

export function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  if (hours > 0) return `${hours}h ${minutes % 60}m`
  if (minutes > 0) return `${minutes}m ${seconds % 60}s`
  return `${seconds}s`
}
