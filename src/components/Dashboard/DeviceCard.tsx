import { memo } from 'react'
import { motion } from 'framer-motion'
import { Monitor, Laptop, Smartphone, Tablet, HelpCircle, Send, Wifi, WifiOff, X } from 'lucide-react'
import { clsx } from 'clsx'
import type { Device } from '../../lib/types'
import { OS_LABELS } from '../../lib/constants'
import { useDeviceStore } from '../../stores/deviceStore'

interface DeviceCardProps {
  device: Device
  onSend: (device: Device) => void
  isSelected: boolean
  onSelect: (device: Device) => void
}

const iconMap = {
  pc: Monitor,
  laptop: Laptop,
  phone: Smartphone,
  tablet: Tablet,
  unknown: HelpCircle,
}

export const DeviceCard = memo(function DeviceCard({ device, onSend, isSelected, onSelect }: DeviceCardProps) {
  const Icon = iconMap[device.icon] ?? HelpCircle
  const isConnected = device.status === 'connected'
  const removeDevice = useDeviceStore((s) => s.removeDevice)

  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
      onClick={() => onSelect(device)}
      className={clsx(
        'glass-card p-5 cursor-pointer transition-all duration-300 group',
        isSelected
          ? 'border-cyber-teal/50 shadow-glow'
          : 'hover:border-cyber-teal/20 hover:shadow-glow'
      )}
    >
      <div className="flex items-start justify-between mb-4">
        <div className={clsx(
          'w-12 h-12 rounded-2xl flex items-center justify-center transition-colors duration-300',
          isConnected
            ? 'bg-cyber-teal/15 text-cyber-teal'
            : 'bg-frost-400/10 text-frost-400'
        )}>
          <Icon size={24} />
        </div>

        <div className="flex items-center gap-2">
          {device.manual && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                removeDevice(device.id)
              }}
              aria-label="Remove device"
              title="Remove device"
              className="w-6 h-6 flex items-center justify-center rounded-md text-frost-400 hover:bg-red-500/10 hover:text-red-400 transition-colors"
            >
              <X size={12} />
            </button>
          )}
          <div className={clsx(
            'w-2 h-2 rounded-full',
            isConnected ? 'bg-cyber-teal animate-pulse-slow' : 'bg-frost-400/40'
          )} />
          <span className={clsx(
            'text-xs font-medium',
            isConnected ? 'text-cyber-teal' : 'text-frost-400'
          )}>
            {isConnected ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>

      <div className="mb-3">
        <h3 className="text-base font-semibold text-frost-100 mb-1">{device.name}</h3>
        <p className="text-xs text-frost-300">{OS_LABELS[device.os] || device.os}</p>
      </div>

      <div className="space-y-2 mb-4">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-frost-400 uppercase tracking-wider">MAC</span>
          <span className="text-xs font-mono text-frost-200">{device.mac}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-frost-400 uppercase tracking-wider">IP</span>
          <span className="text-xs font-mono text-frost-200">{device.ip}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-frost-400 uppercase tracking-wider">Link</span>
          <span className={clsx(
            'flex items-center gap-1 text-xs font-medium',
            device.connectionType === 'lan' ? 'text-cyber-teal' : 'text-cyber-blue'
          )}>
            {device.connectionType === 'lan' ? <Wifi size={10} /> : <WifiOff size={10} />}
            {device.connectionType.toUpperCase()}
          </span>
        </div>
      </div>

      {device.id !== 'self' && (
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={(e) => {
            e.stopPropagation()
            if (isConnected) onSend(device)
          }}
          disabled={!isConnected}
          className={clsx(
            'w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all duration-300',
            isConnected
              ? 'bg-cyber-teal/15 text-cyber-teal border border-cyber-teal/30 hover:bg-cyber-teal/25'
              : 'bg-navy-700/50 text-frost-400 border border-white/5 cursor-not-allowed'
          )}
        >
          <Send size={14} />
          Send Files
        </motion.button>
      )}
    </motion.div>
  )
})
