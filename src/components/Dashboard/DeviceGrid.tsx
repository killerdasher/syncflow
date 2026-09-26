import { motion } from 'framer-motion'
import { Plus } from 'lucide-react'
import { useDeviceStore } from '../../stores/deviceStore'
import { DeviceCard } from './DeviceCard'
import { GlowButton } from '../shared/GlowButton'

interface DeviceGridProps {
  onSendToDevice: (device: any) => void
  onAddDevice: () => void
}

export function DeviceGrid({ onSendToDevice, onAddDevice }: DeviceGridProps) {
  const devices = useDeviceStore((s) => s.devices)
  const selectedDevice = useDeviceStore((s) => s.selectedDevice)
  const selectDevice = useDeviceStore((s) => s.selectDevice)

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Devices</h2>
          <p className="text-sm text-frost-300">
            {devices.filter((d) => d.status === 'connected').length} of {devices.length} connected
          </p>
        </div>
        <GlowButton icon={<Plus size={14} />} onClick={onAddDevice}>
          Add Device
        </GlowButton>
      </div>

      {devices.length === 0 && (
        <div className="glass-card p-10 text-center mb-4">
          <p className="text-sm text-frost-200 mb-1">No devices yet</p>
          <p className="text-xs text-frost-400">
            Devices on your network are discovered automatically — or add one manually with the button above.
          </p>
        </div>
      )}

      <motion.div
        className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4"
        initial="initial"
        animate="animate"
        variants={{
          animate: {
            transition: { staggerChildren: 0.08 },
          },
        }}
      >
        {devices.map((device) => (
          <DeviceCard
            key={device.id}
            device={device}
            onSend={onSendToDevice}
            isSelected={selectedDevice?.id === device.id}
            onSelect={selectDevice}
          />
        ))}
      </motion.div>
    </div>
  )
}
