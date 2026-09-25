import { HardDrive, Database, ArrowUpDown, CheckCircle, XCircle } from 'lucide-react'
import { GlassCard } from '../shared/GlassCard'
import { useTransferStore } from '../../stores/transferStore'
import { useSettingsStore } from '../../stores/settingsStore'
import { formatBytes } from '../../lib/constants'

export function StoragePage() {
  const transfers = useTransferStore((s) => s.transfers)
  const deviceName = useSettingsStore((s) => s.settings.deviceName)
  const downloadPath = useSettingsStore((s) => s.settings.downloadPath)

  const selfLabel = deviceName || 'This Device'
  const completed = transfers.filter((t) => t.status === 'completed')
  const failed = transfers.filter((t) => t.status === 'failed' || t.status === 'cancelled')
  const active = transfers.filter((t) => t.status === 'transferring' || t.status === 'pending' || t.status === 'awaiting')

  const sentBytes = completed
    .filter((t) => t.fromDevice === selfLabel)
    .reduce((sum, t) => sum + t.totalBytes, 0)
  const receivedBytes = completed
    .filter((t) => t.toDevice === selfLabel)
    .reduce((sum, t) => sum + t.totalBytes, 0)

  const hasData = transfers.length > 0

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Storage</h2>
          <p className="text-sm text-frost-300">Local storage and transfer history</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <GlassCard>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-cyber-teal/15 flex items-center justify-center">
              <HardDrive size={20} className="text-cyber-teal" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-frost-100">Received Files</h3>
              <p className="text-xs text-frost-300">Saved to download folder</p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex justify-between text-xs">
              <span className="text-frost-300">Download folder</span>
              <span className="text-frost-100 font-mono truncate ml-3">{downloadPath}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-frost-300">Received this session</span>
              <span className="text-frost-100">{formatBytes(receivedBytes)}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-frost-300">Sent this session</span>
              <span className="text-frost-100">{formatBytes(sentBytes)}</span>
            </div>
          </div>

          {!hasData && (
            <p className="text-xs text-frost-400 mt-4 pt-3 border-t border-white/5">
              No transfer activity yet in this session.
            </p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-cyber-blue/15 flex items-center justify-center">
              <Database size={20} className="text-cyber-blue" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-frost-100">Transfer History</h3>
              <p className="text-xs text-frost-300">This session</p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex justify-between text-xs items-center">
              <span className="text-frost-300 flex items-center gap-1.5">
                <ArrowUpDown size={11} className="text-cyber-teal" />
                Active
              </span>
              <span className="text-frost-100">{active.length}</span>
            </div>
            <div className="flex justify-between text-xs items-center">
              <span className="text-frost-300 flex items-center gap-1.5">
                <CheckCircle size={11} className="text-green-400" />
                Completed
              </span>
              <span className="text-frost-100">{completed.length}</span>
            </div>
            <div className="flex justify-between text-xs items-center">
              <span className="text-frost-300 flex items-center gap-1.5">
                <XCircle size={11} className="text-red-400" />
                Failed / cancelled
              </span>
              <span className="text-red-400">{failed.length}</span>
            </div>
          </div>

          {!hasData && (
            <p className="text-xs text-frost-400 mt-4 pt-3 border-t border-white/5">
              Completed transfers will be listed here.
            </p>
          )}
        </GlassCard>
      </div>
    </div>
  )
}
