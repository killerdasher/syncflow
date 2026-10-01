import { useEffect, useRef, useCallback } from 'react'
import { useSettingsStore } from '../stores/settingsStore'
import { useDeviceStore } from '../stores/deviceStore'
import { useTransferStore } from '../stores/transferStore'
import type { Device, SyncFolder } from '../lib/types'

const MAX_FILES_PER_SEND = 1000
const TICK_MS = 30_000

const REAL_DEVICE_ID_RE = /^[0-9a-f]{32}$/

export type SyncResult =
  | 'sent'
  | 'no-device'
  | 'not-connected'
  | 'no-files'
  | 'no-electron'
  | 'error'

/**
 * Push files changed since folder.lastSync to the folder's paired device.
 * The destination folder name on the receiver defaults to the local folder's
 * basename; the receiver only maps it if it configured a matching folder.
 */
export async function syncFolderNow(folder: SyncFolder): Promise<SyncResult> {
  if (!window.electronAPI?.sync?.scan || !window.electronAPI?.send) return 'no-electron'

  const device: Device | undefined = useDeviceStore
    .getState()
    .devices.find((d) => d.id === folder.remoteDevice)

  if (!device) return 'no-device'
  if (device.status !== 'connected') return 'not-connected'
  const targetDeviceId = REAL_DEVICE_ID_RE.test(device.id) ? device.id : undefined

  const scan = await window.electronAPI.sync.scan(folder.localPath, folder.lastSync || 0)
  if (!scan || scan.error) return scan?.error ? 'error' : 'no-electron'
  const files = (scan.files || []).slice(0, MAX_FILES_PER_SEND)
  if (files.length === 0) return 'no-files'

  const destFolder = (folder.remotePath || '').trim() ||
    folder.localPath.split('/').filter(Boolean).pop() || ''
  const transferId = `sync-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

  useSettingsStore.getState().addPendingSync(transferId, folder.localPath)
  useTransferStore.getState().addTransfer({
    id: transferId,
    fromDevice: useSettingsStore.getState().settings.deviceName || 'This Device',
    toDevice: device.name,
    files: files.map((f) => ({ name: f.name, path: f.path, size: f.size, type: 'application/octet-stream' })),
    status: 'pending',
    progress: 0,
    speed: 0,
    bytesTransferred: 0,
    totalBytes: files.reduce((sum, f) => sum + f.size, 0),
    startTime: Date.now(),
    targetIp: device.ip,
    targetDeviceId,
    destFolder,
  })

  const ok = await window.electronAPI.send({
    type: 'command:send',
    targetIp: device.ip,
    ...(targetDeviceId ? { targetDeviceId } : {}),
    destFolder,
    transferId,
    files: files.map((f) => f.path),
  })

  if (!ok) {
    useTransferStore.getState().updateTransfer(transferId, {
      status: 'failed',
      error: 'Backend not connected',
    })
    useSettingsStore.getState().resolvePendingSync(transferId, false)
    return 'error'
  }
  return 'sent'
}

/** Auto-sync tick: pushes every enabled folder whose interval elapsed. */
export function useSyncEngine() {
  const runningRef = useRef(false)

  const tick = useCallback(async () => {
    if (runningRef.current) return
    runningRef.current = true
    try {
      const { settings, pendingSyncs } = useSettingsStore.getState()
      const now = Date.now()
      for (const folder of settings.syncFolders) {
        if (!folder.enabled || !folder.remoteDevice) continue
        if (!folder.interval || folder.interval <= 0) continue // manual-only
        if (now - (folder.lastSync || 0) < folder.interval * 60_000) continue
        // Never double-send a folder whose previous sync is still in flight
        if (Object.values(pendingSyncs).some((p) => p.folderPath === folder.localPath)) continue
        await syncFolderNow(folder)
        Object.assign(pendingSyncs, useSettingsStore.getState().pendingSyncs)
      }
    } finally {
      runningRef.current = false
    }
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => {
      tick()
    }, TICK_MS)
    return () => window.clearInterval(id)
  }, [tick])
}
