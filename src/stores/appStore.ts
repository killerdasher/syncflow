import { create } from 'zustand'

export interface PairingSession {
  code: string
  qr: string
  host: string
  port: number
  lanMode: boolean
  expiresAt: number
}

/** Result of the out-of-band SAS verification for one pinned peer. */
export interface SasResult {
  peerDeviceId: string
  codes: number[]
  hash: string
}

export interface SecurityToast {
  id: number
  key: string
  reason: string
  createdAt: number
}

interface AppState {
  backendConnected: boolean
  setBackendConnected: (connected: boolean) => void
  /** One-shot navigation request (e.g. notification click -> page) */
  navTarget: string | null
  navigate: (page: string) => void
  clearNavigate: () => void
  /** Active pairing code for the mobile companion (Phase 0), null = none */
  pairing: PairingSession | null
  setPairing: (p: PairingSession | null) => void
  pairingError: string | null
  setPairingError: (e: string | null) => void
  /** Companion (Phase 1) auth state — connect screen shows until true */
  companionAuthed: boolean
  setCompanionAuthed: (v: boolean) => void
  /** Latest SAS derivation reply (identity:sas), null = none yet */
  sas: SasResult | null
  setSas: (s: SasResult | null) => void
  /** Security toasts (identity change, etc.) */
  securityToasts: SecurityToast[]
  addSecurityToast: (key: string, reason: string) => void
  dismissSecurityToast: (id: number) => void
}

export const useAppStore = create<AppState>((set) => ({
  backendConnected: false,
  setBackendConnected: (connected) => set({ backendConnected: connected }),
  navTarget: null,
  navigate: (page) => set({ navTarget: page }),
  clearNavigate: () => set({ navTarget: null }),
  pairing: null,
  setPairing: (p) => set({ pairing: p }),
  pairingError: null,
  setPairingError: (e) => set({ pairingError: e }),
  companionAuthed: false,
  setCompanionAuthed: (v) => set({ companionAuthed: v }),
  sas: null,
  setSas: (s) => set({ sas: s }),
  securityToasts: [],
  addSecurityToast: (key, reason) =>
    set((state) => ({
      securityToasts: [
        ...state.securityToasts,
        { id: Date.now(), key, reason, createdAt: Date.now() },
      ],
    })),
  dismissSecurityToast: (id) =>
    set((state) => ({
      securityToasts: state.securityToasts.filter((t) => t.id !== id),
    })),
}))
