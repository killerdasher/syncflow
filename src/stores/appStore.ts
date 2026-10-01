import { create } from 'zustand'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (connected: boolean) => void
  /** One-shot navigation request (e.g. notification click -> page) */
  navTarget: string | null
  navigate: (page: string) => void
  clearNavigate: () => void
}

export const useAppStore = create<AppState>((set) => ({
  backendConnected: false,
  setBackendConnected: (connected) => set({ backendConnected: connected }),
  navTarget: null,
  navigate: (page) => set({ navTarget: page }),
  clearNavigate: () => set({ navTarget: null }),
}))
