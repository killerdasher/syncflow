import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, MonitorSmartphone, Plus } from 'lucide-react'
import { clsx } from 'clsx'
import { useDeviceStore } from '../../stores/deviceStore'
import type { Device } from '../../lib/types'

interface AddDeviceModalProps {
  isOpen: boolean
  onClose: () => void
}

const IP_RE = /^(\d{1,3}\.){3}\d{1,3}$|^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$|^[a-zA-Z0-9-]+$/

export function AddDeviceModal({ isOpen, onClose }: AddDeviceModalProps) {
  const addDevice = useDeviceStore((s) => s.addDevice)
  const devices = useDeviceStore((s) => s.devices)
  const [name, setName] = useState('')
  const [ip, setIp] = useState('')
  const [error, setError] = useState('')

  const reset = () => {
    setName('')
    setIp('')
    setError('')
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleSubmit = () => {
    const trimmedIp = ip.trim()
    const trimmedName = name.trim()

    if (!trimmedIp) {
      setError('IP address or hostname is required')
      return
    }
    if (!IP_RE.test(trimmedIp)) {
      setError('Enter a valid IPv4 address or hostname (e.g. 192.168.1.20)')
      return
    }
    if (devices.some((d) => d.ip === trimmedIp)) {
      setError('A device with this address already exists')
      return
    }

    const device: Device = {
      id: `manual-${trimmedIp}-${Date.now()}`,
      name: trimmedName || trimmedIp,
      mac: 'unknown',
      ip: trimmedIp,
      os: 'unknown',
      status: 'connected',
      connectionType: 'lan',
      lastSeen: Date.now(),
      icon: 'pc',
      manual: true,
    }

    addDevice(device)
    reset()
    onClose()
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={handleClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2 }}
            className="glass-card p-6 w-full max-w-md border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyber-teal/15 flex items-center justify-center">
                  <MonitorSmartphone size={20} className="text-cyber-teal" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-frost-100">Add Device</h3>
                  <p className="text-xs text-frost-300">Manually add a device by its address</p>
                </div>
              </div>
              <button
                onClick={handleClose}
                aria-label="Close"
                className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-400 hover:bg-white/5 hover:text-frost-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-frost-200 mb-1.5">Device Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Office PC"
                  className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-frost-200 mb-1.5">IP Address / Hostname</label>
                <input
                  type="text"
                  value={ip}
                  onChange={(e) => setIp(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
                  placeholder="e.g. 192.168.1.20"
                  className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                />
                <p className="text-xs text-frost-400 mt-1.5">
                  The device must be running SyncFlow on your network.
                </p>
              </div>

              {error && (
                <p className="text-xs text-red-400 flex items-center gap-1.5">
                  {error}
                </p>
              )}

              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleClose}
                  className="flex-1 py-2.5 rounded-xl bg-navy-700 text-frost-100 border border-white/10 text-sm font-medium hover:bg-navy-600 transition-all"
                >
                  Cancel
                </button>
                <motion.button
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={handleSubmit}
                  className={clsx(
                    'flex-1 py-2.5 rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-all',
                    'bg-cyber-teal/20 text-cyber-teal border border-cyber-teal/30 hover:bg-cyber-teal/30'
                  )}
                >
                  <Plus size={14} />
                  Add Device
                </motion.button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
