import { create } from 'zustand'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (connected: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  backendConnected: false,
  setBackendConnected: (connected) => set({ backendConnected: connected }),
}))
