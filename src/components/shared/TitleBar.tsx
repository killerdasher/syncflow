import { Minus, Square, X, Wifi, Shield } from 'lucide-react'
import { useDeviceStore } from '../../stores/deviceStore'

export function TitleBar() {
  const devices = useDeviceStore((s) => s.devices)
  const connectedCount = devices.filter((d) => d.status === 'connected').length

  return (
    <div className="drag-region flex items-center justify-between h-10 px-4 bg-navy-900/80 border-b border-white/5 select-none">
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-cyber-teal animate-pulse-slow" />
          <span className="text-sm font-semibold tracking-wide gradient-text">SyncFlow</span>
        </div>
        <div className="no-drag flex items-center gap-2 text-xs text-frost-300">
          <span className="flex items-center gap-1">
            <Wifi size={12} className="text-cyber-teal" />
            {connectedCount} device{connectedCount !== 1 ? 's' : ''}
          </span>
          <span className="flex items-center gap-1">
            <Shield size={12} className="text-cyber-teal" />
            End-to-end encrypted
          </span>
        </div>
      </div>

      <div className="no-drag flex items-center gap-0.5">
        <button
          onClick={() => window.electronAPI?.window?.minimize?.()}
          aria-label="Minimize"
          className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-300 hover:bg-white/5 hover:text-frost-100 transition-colors"
        >
          <Minus size={14} />
        </button>
        <button
          onClick={() => window.electronAPI?.window?.maximize?.()}
          aria-label="Maximize"
          className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-300 hover:bg-white/5 hover:text-frost-100 transition-colors"
        >
          <Square size={12} />
        </button>
        <button
          onClick={() => window.electronAPI?.window?.close?.()}
          aria-label="Close"
          className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-300 hover:bg-red-500/20 hover:text-red-400 transition-colors"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}
