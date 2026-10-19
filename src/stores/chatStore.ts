import { create } from 'zustand'
import type { ChatMessage } from '../lib/types'

interface ChatState {
  messages: ChatMessage[]
  selfId: string | null
  addMessage: (msg: ChatMessage) => void
  setMessages: (msgs: ChatMessage[]) => void
  setSelfId: (id: string) => void
  setMessageStatus: (id: string, status: ChatMessage['status'], failReason?: string) => void
  clear: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  selfId: null,
  addMessage: (msg) =>
    set((state) => {
      if (state.messages.some((m) => m.id === msg.id)) return state
      return { messages: [...state.messages, msg] }
    }),
  setMessages: (msgs) => set({ messages: msgs }),
  setSelfId: (id) =>
    set((state) => ({
      selfId: id,
      messages: state.messages.map((m) => ({ ...m, self: m.deviceId === id })),
    })),
  setMessageStatus: (id, status, failReason) =>
    set((state) => ({
      messages: state.messages.map((m) => {
        if (m.id !== id) return m
        // Delivered is final: a late per-target failure must not downgrade it
        // (the message reached at least one peer).
        if (m.status === 'delivered' && status !== 'delivered') return m
        return {
          ...m,
          status,
          ...(status === 'failed' && failReason ? { failReason } : {}),
          ...(status !== 'failed' ? { failReason: undefined } : {}),
        }
      }),
    })),
  clear: () => set({ messages: [] }),
}))
