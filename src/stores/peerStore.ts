import { create } from 'zustand'
import type { PinnedPeer } from '../lib/types'

interface PeerState {
  peers: PinnedPeer[]
  setPeers: (peers: PinnedPeer[]) => void
}

export const usePeerStore = create<PeerState>((set) => ({
  peers: [],
  setPeers: (peers) => set({ peers }),
}))
