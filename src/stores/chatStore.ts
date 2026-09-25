import { create } from 'zustand'
import type { ChatMessage } from '../lib/types'

interface ChatState {
  messages: ChatMessage[]
  selfId: string | null
  addMessage: (msg: ChatMessage) => void
  setMessages: (msgs: ChatMessage[]) => void
  setSelfId: (id: string) => void
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
  clear: () => set({ messages: [] }),
}))
