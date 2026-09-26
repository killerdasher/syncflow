import { motion, AnimatePresence } from 'framer-motion'
import { X, Send, MonitorSmartphone, Plus } from 'lucide-react'
import { clsx } from 'clsx'
import type { Device, FileItem } from '../../lib/types'
import { formatBytes } from '../../lib/constants'

interface DevicePickerModalProps {
  files: FileItem[] | null
  devices: Device[]
  onSend: (device: Device) => void
  onAddDevice: () => void
  onClose: () => void
}

export function DevicePickerModal({ files, devices, onSend, onAddDevice, onClose }: DevicePickerModalProps) {
  const totalBytes = files ? files.reduce((sum, f) => sum + f.size, 0) : 0

  return (
    <AnimatePresence>
      {files !== null && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2 }}
            className="glass-card p-6 w-full max-w-md border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyber-teal/15 flex items-center justify-center">
                  <Send size={20} className="text-cyber-teal" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-frost-100">Send to device</h3>
                  <p className="text-xs text-frost-300">
                    {files.length} file{files.length !== 1 ? 's' : ''} · {formatBytes(totalBytes)}
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-400 hover:bg-white/5 hover:text-frost-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {devices.length === 0 ? (
              <div className="text-center py-6">
                <MonitorSmartphone size={36} className="mx-auto text-frost-400 mb-3" />
                <p className="text-sm text-frost-200 mb-1">No devices online</p>
                <p className="text-xs text-frost-400 mb-4">
                  Start SyncFlow on the other device so it appears here, or add it manually by address.
                </p>
                <div className="flex gap-3">
                  <button
                    onClick={onClose}
                    className="flex-1 py-2.5 rounded-xl bg-navy-700 text-frost-100 border border-white/10 text-sm font-medium hover:bg-navy-600 transition-all"
                  >
                    Cancel
                  </button>
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => {
                      onClose()
                      onAddDevice()
                    }}
                    className="flex-1 py-2.5 rounded-xl text-sm font-medium flex items-center justify-center gap-2 bg-cyber-teal/20 text-cyber-teal border border-cyber-teal/30 hover:bg-cyber-teal/30 transition-all"
                  >
                    <Plus size={14} />
                    Add Device
                  </motion.button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                {devices.map((device) => (
                  <motion.button
                    key={device.id}
                    whileHover={{ x: 4 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => onSend(device)}
                    className={clsx(
                      'w-full flex items-center justify-between px-4 py-3 rounded-xl text-left transition-colors',
                      'bg-navy-700/60 border border-white/5 hover:border-cyber-teal/40 hover:bg-cyber-teal/10'
                    )}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-frost-100 truncate">{device.name}</p>
                      <p className="text-xs text-frost-400 font-mono">{device.ip}</p>
                    </div>
                    <Send size={14} className="text-cyber-teal flex-shrink-0" />
                  </motion.button>
                ))}
                <button
                  onClick={onClose}
                  className="w-full py-2.5 mt-2 rounded-xl bg-navy-700 text-frost-200 border border-white/10 text-sm font-medium hover:bg-navy-600 transition-all"
                >
                  Cancel
                </button>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
