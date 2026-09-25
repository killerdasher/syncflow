import { create } from 'zustand'
import type { Transfer } from '../lib/types'

type TransferInput = Partial<Transfer> & { id: string }

interface TransferState {
  transfers: Transfer[]
  addTransfer: (transfer: TransferInput) => void
  updateTransfer: (id: string, updates: Partial<Transfer>) => void
  removeTransfer: (id: string) => void
  cancelTransfer: (id: string) => void
}

const defaultTransfer: Omit<Transfer, 'id'> = {
  fromDevice: 'This Device',
  toDevice: 'Unknown device',
  files: [],
  status: 'pending',
  progress: 0,
  speed: 0,
  bytesTransferred: 0,
  totalBytes: 0,
  startTime: Date.now(),
}

export const useTransferStore = create<TransferState>((set) => ({
  transfers: [],
  addTransfer: (input) =>
    set((state) => {
      const idx = state.transfers.findIndex((t) => t.id === input.id)
      if (idx >= 0) {
        return {
          transfers: state.transfers.map((t, i) => (i === idx ? { ...t, ...input } : t)),
        }
      }
      return { transfers: [{ ...defaultTransfer, ...input } as Transfer, ...state.transfers] }
    }),
  updateTransfer: (id, updates) =>
    set((state) => ({
      transfers: state.transfers.map((t) =>
        t.id === id ? { ...t, ...updates } : t
      ),
    })),
  removeTransfer: (id) =>
    set((state) => ({
      transfers: state.transfers.filter((t) => t.id !== id),
    })),
  cancelTransfer: (id) =>
    set((state) => ({
      transfers: state.transfers.map((t) =>
        t.id === id ? { ...t, status: 'cancelled' as const } : t
      ),
    })),
}))
