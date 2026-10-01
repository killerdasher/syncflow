import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Settings } from '../lib/types'

interface PendingSync {
  folderPath: string
  scanTime: number
}

interface SettingsState {
  settings: Settings
  /** Transfers waiting on a sync-folder send (id -> context) */
  pendingSyncs: Record<string, PendingSync>
  updateSettings: (updates: Partial<Settings>) => void
  addPendingSync: (transferId: string, folderPath: string) => void
  resolvePendingSync: (transferId: string, success: boolean) => void
}

const defaultSettings: Settings = {
  deviceName: '',
  autoAccept: false,
  downloadPath: '~/Downloads/SyncFlow',
  syncFolders: [],
  maxConcurrent: 4,
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      settings: defaultSettings,
      pendingSyncs: {},
      updateSettings: (updates) =>
        set((state) => ({
          settings: { ...state.settings, ...updates },
        })),
      addPendingSync: (transferId, folderPath) =>
        set((state) => ({
          pendingSyncs: {
            ...state.pendingSyncs,
            [transferId]: { folderPath, scanTime: Date.now() },
          },
        })),
      resolvePendingSync: (transferId, success) =>
        set((state) => {
          const pending = state.pendingSyncs[transferId]
          if (!pending) return state
          const { [transferId]: _drop, ...rest } = state.pendingSyncs
          if (!success) return { pendingSyncs: rest }
          return {
            pendingSyncs: rest,
            settings: {
              ...state.settings,
              syncFolders: state.settings.syncFolders.map((f) =>
                f.localPath === pending.folderPath
                  ? { ...f, lastSync: pending.scanTime }
                  : f
              ),
            },
          }
        }),
    }),
    {
      name: 'syncflow-settings',
      version: 1,
      partialize: (state) => ({ settings: state.settings }) as any,
      migrate: (persisted: any, _version: number) => {
        // v0 stored non-functional placeholders (relay/port/encryption toggles)
        const old = persisted?.settings ?? {}
        const {
          relayServer: _r1,
          relayToken: _r2,
          port: _p,
          encryptionEnabled: _e,
          maxConcurrentTransfers,
          ...rest
        } = old
        return {
          settings: {
            ...defaultSettings,
            ...rest,
            maxConcurrent: Number(old.maxConcurrent) || Number(maxConcurrentTransfers) || 4,
          },
          pendingSyncs: {},
        }
      },
    }
  )
)

/** Push the local settings to the Python backend (idempotent). */
export function applySettings(): void {
  if (!window.electronAPI) return
  const s = useSettingsStore.getState().settings
  window.electronAPI.send({
    type: 'settings:apply',
    downloadPath: s.downloadPath,
    autoAccept: s.autoAccept,
    maxConcurrent: s.maxConcurrent,
    ...(s.deviceName ? { deviceName: s.deviceName } : {}),
    syncFolders: (s.syncFolders || []).map((f) => ({ localPath: f.localPath })),
  })
}
