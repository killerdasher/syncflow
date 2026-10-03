import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Lock, Hash, ShieldCheck, Smartphone, AlertTriangle } from 'lucide-react'
import { clsx } from 'clsx'
import { useChatStore } from '../../stores/chatStore'
import { useSettingsStore } from '../../stores/settingsStore'
import type { ChatMessage } from '../../lib/types'

const REAL_HASH = /^[0-9a-f]{16,}$/i
const EARLY_PAGE = 100

export function ChatPage() {
  const [input, setInput] = useState('')
  const [showEarlier, setShowEarlier] = useState(false)
  const messages = useChatStore((s) => s.messages)
  const settings = useSettingsStore((s) => s.settings)
  const bottomRef = useRef<HTMLDivElement>(null)

  const hiddenCount = !showEarlier && messages.length > EARLY_PAGE ? messages.length - EARLY_PAGE : 0
  const visible = hiddenCount ? messages.slice(hiddenCount) : messages

  useEffect(() => {
    if (window.electronAPI) {
      window.electronAPI.send({ type: 'identity:get' })
      window.electronAPI.send({ type: 'chat:history' })
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    const text = input.trim()
    if (!text) return
    setInput('')

    if (!window.electronAPI) return

    const payload: Record<string, unknown> = { type: 'chat:send', text }
    if (settings.deviceName) payload.fromDevice = settings.deviceName

    const success = await window.electronAPI.send(payload)

    if (!success) {
      const failedMsg: ChatMessage = {
        id: `local-${Date.now()}`,
        fromDevice: settings.deviceName || 'This Device',
        deviceId: 'self',
        text,
        timestamp: Date.now() / 1000,
        hash: 'pending',
        self: true,
      }
      useChatStore.getState().addMessage(failedMsg)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Chat</h2>
          <p className="text-sm text-frost-300">{messages.length} message{messages.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-cyber-teal/10 border border-cyber-teal/20">
          <Lock size={12} className="text-cyber-teal" />
          <span className="text-xs font-medium text-cyber-teal">E2E Encrypted</span>
        </div>
      </div>

      <div className="flex-1 glass-card p-4 mb-4 overflow-y-auto min-h-0" style={{ maxHeight: 'calc(100vh - 280px)' }}>
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center py-10">
            <Lock size={32} className="text-frost-400 mb-3" />
            <p className="text-sm text-frost-300">No messages yet</p>
            <p className="text-xs text-frost-400 mt-1">Messages are relayed to paired devices on your network</p>
          </div>
        )}
        {hiddenCount > 0 && (
          <div className="text-center mb-3">
            <button
              onClick={() => setShowEarlier(true)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium text-frost-300 hover:text-frost-100 bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
            >
              Show {hiddenCount} earlier message{hiddenCount !== 1 ? 's' : ''}
            </button>
          </div>
        )}
        <AnimatePresence initial={false}>
          {visible.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.25 }}
              className={clsx(
                'mb-3 flex',
                msg.self ? 'justify-end' : 'justify-start'
              )}
            >
              <div
                className={clsx(
                  'max-w-[70%] rounded-2xl px-4 py-2.5',
                  msg.self
                    ? 'bg-cyber-teal/15 border border-cyber-teal/25 rounded-br-md'
                    : 'bg-navy-700/70 border border-white/5 rounded-bl-md'
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={clsx(
                      'text-[11px] font-semibold',
                      msg.self ? 'text-cyber-teal' : 'text-cyber-blue'
                    )}
                  >
                    {msg.self ? 'You' : msg.fromDevice}
                  </span>
                  <span className="text-[10px] text-frost-400">
                    {formatTime(msg.timestamp)}
                  </span>
                  {REAL_HASH.test(msg.hash) && (
                    <Hash size={9} className="text-frost-400" />
                  )}
                </div>
                <p className="text-sm text-frost-100 leading-relaxed wrap-break-word">
                  {msg.text}
                </p>
                {msg.hash === 'pending' ? (
                  <div className="flex items-center gap-1 mt-1.5 text-amber-400">
                    <AlertTriangle size={9} />
                    <span className="text-[9px]">Not sent — backend offline</span>
                  </div>
                ) : REAL_HASH.test(msg.hash) ? (
                  <div className="flex items-center gap-1 mt-1.5">
                    <ShieldCheck size={9} className="text-green-400" />
                    <span className="text-[9px] font-mono text-frost-400 truncate">
                      {msg.hash.slice(0, 16)}…
                    </span>
                  </div>
                ) : null}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      <div className="glass-card p-3">
        <div className="flex items-end gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message..."
            rows={1}
            aria-label="Message"
            className="flex-1 bg-navy-700/50 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 resize-none transition-all"
            style={{ minHeight: '42px', maxHeight: '120px' }}
          />
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={handleSend}
            disabled={!input.trim()}
            aria-label="Send message"
            className={clsx(
              'w-10 h-10 flex items-center justify-center rounded-xl transition-all duration-200',
              input.trim()
                ? 'bg-cyber-teal/20 text-cyber-teal border border-cyber-teal/30 hover:bg-cyber-teal/30'
                : 'bg-navy-700/50 text-frost-400 border border-white/5'
            )}
          >
            <Send size={16} />
          </motion.button>
        </div>
        <div className="flex items-center justify-between mt-2 px-1">
          <span className="text-[10px] text-frost-400 flex items-center gap-1">
            <Smartphone size={9} />
            Messages relay to all paired devices
          </span>
          <span className="text-[10px] text-frost-400">Enter to send</span>
        </div>
      </div>
    </div>
  )
}
