import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Settings } from '../lib/types'

interface SettingsState {
  settings: Settings
  updateSettings: (updates: Partial<Settings>) => void
}

const defaultSettings: Settings = {
  deviceName: '',
  autoAccept: false,
  downloadPath: '~/Downloads/SyncFlow',
  syncFolders: [],
  relayServer: '',
  relayToken: '',
  encryptionEnabled: true,
  maxConcurrentTransfers: 4,
  port: 18973,
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      settings: defaultSettings,
      updateSettings: (updates) =>
        set((state) => ({
          settings: { ...state.settings, ...updates },
        })),
    }),
    {
      name: 'syncflow-settings',
    }
  )
)
