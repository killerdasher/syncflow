import { memo, useState } from 'react'
import { motion } from 'framer-motion'
import { X, RotateCcw, Check, AlertCircle, FileArchive, FileImage, FileVideo, ShieldCheck, Ban, Clock, FolderOpen, Download, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import type { Transfer } from '../../lib/types'
import { IS_COMPANION } from '../../lib/bridge'
import { uploadFiles } from '../../lib/upload'
import { fetchFileFromDesktop, saveBlobToPhone } from '../../lib/download'
import { formatBytes, formatSpeed, formatDuration } from '../../lib/constants'
import { ProgressRing } from './ProgressRing'
import { useTransferStore } from '../../stores/transferStore'
import { useSettingsStore } from '../../stores/settingsStore'

interface TransferCardProps {
  transfer: Transfer
}

const fileIconMap: Record<string, any> = {
  'application/zip': FileArchive,
  'image/jpeg': FileImage,
  'image/png': FileImage,
  'image/gif': FileImage,
  'video/mp4': FileVideo,
  'video/avi': FileVideo,
}

export const TransferCard = memo(function TransferCard({ transfer }: TransferCardProps) {
  const cancelTransfer = useTransferStore((s) => s.cancelTransfer)
  const addTransfer = useTransferStore((s) => s.addTransfer)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const isActive = transfer.status === 'transferring' || transfer.status === 'pending'
  const isAwaiting = transfer.status === 'awaiting'
  const isCompleted = transfer.status === 'completed'
  const isFailed = transfer.status === 'failed'
  const isCancelled = transfer.status === 'cancelled'

  const elapsed = transfer.endTime
    ? transfer.endTime - transfer.startTime
    : Date.now() - transfer.startTime

  const handleCancel = async () => {
    cancelTransfer(transfer.id)
    if (window.electronAPI) {
      await window.electronAPI.send({ type: 'command:cancel', transferId: transfer.id })
    }
  }

  const handleRetry = async () => {
    if (!transfer.targetIp || !window.electronAPI) return
    addTransfer({
      id: transfer.id,
      status: 'pending',
      progress: 0,
      speed: 0,
      bytesTransferred: 0,
      error: undefined,
      verified: false,
      endTime: undefined,
      startTime: Date.now(),
    })
    if (IS_COMPANION && transfer.files.length > 0 && transfer.files.every((f) => f.blob instanceof Blob)) {
      await uploadFiles(
        transfer.files,
        { ip: transfer.targetIp, deviceId: transfer.targetDeviceId || undefined },
        transfer.id
      )
      return
    }
    await window.electronAPI.send({
      type: 'command:send',
      targetIp: transfer.targetIp,
      targetDeviceId: transfer.targetDeviceId,
      files: transfer.files.map((f) => f.path),
      transferId: transfer.id,
    })
  }

  const handleApprove = async () => {
    if (window.electronAPI) {
      await window.electronAPI.send({ type: 'transfer:approve', transferId: transfer.id })
    }
  }

  const handleDecline = async () => {
    if (window.electronAPI) {
      await window.electronAPI.send({ type: 'transfer:decline', transferId: transfer.id })
    }
  }

  // Companion-only: pull each completed file off the desktop over WS and
  // hand it to the share sheet (native) or a browser download (web).
  const handleSave = async () => {
    if (saving) return
    setSaving(true)
    setSaveError(null)
    try {
      for (let i = 0; i < transfer.files.length; i++) {
        const got = await fetchFileFromDesktop(transfer.id, i)
        await saveBlobToPhone(got.blob, got.name)
      }
    } catch (e: any) {
      setSaveError(String(e?.message || e))
    }
    setSaving(false)
  }

  // Received files: destPath from the backend. Sent files: reveal the local source.
  const revealPath = transfer.destPath || (transfer.fromDevice === (useSettingsStore.getState().settings.deviceName || 'This Device')
    ? transfer.files.find((f) => f.path)?.path
    : undefined)
  const canReveal = isCompleted && !!revealPath && !!window.electronAPI?.shell?.reveal

  const handleReveal = () => {
    if (revealPath) window.electronAPI?.shell?.reveal(revealPath)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.3 }}
      className={clsx(
        'glass-card p-4 transition-all duration-300',
        isActive && 'border-cyber-teal/30 shadow-glow',
        isAwaiting && 'border-amber-400/40 shadow-glow',
        isCompleted && 'border-green-500/20',
        isFailed && 'border-red-500/20',
        isCancelled && 'border-white/10'
      )}
    >
      <div className="flex items-start gap-4">
        <ProgressRing
          progress={transfer.progress}
          status={transfer.status}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between mb-2">
            <div>
              <h4 className="text-sm font-semibold text-frost-100 truncate">
                {transfer.files.map((f) => f.name).join(', ')}
              </h4>
              <p className="text-xs text-frost-300 mt-0.5">
                {transfer.fromDevice} → {transfer.toDevice}
              </p>
            </div>

            <div className="flex items-center gap-1 ml-2">
              {isAwaiting && (
                <>
                  <button
                    onClick={handleApprove}
                    aria-label="Accept transfer"
                    title="Accept transfer"
                    className="w-7 h-7 flex items-center justify-center rounded-lg text-green-400 hover:bg-green-500/10 transition-colors"
                  >
                    <Check size={12} />
                  </button>
                  <button
                    onClick={handleDecline}
                    aria-label="Decline transfer"
                    title="Decline transfer"
                    className="w-7 h-7 flex items-center justify-center rounded-lg text-red-400 hover:bg-red-500/10 transition-colors"
                  >
                    <X size={12} />
                  </button>
                </>
              )}
              {isActive && (
                <button
                  onClick={handleCancel}
                  aria-label="Cancel transfer"
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-frost-300 hover:bg-red-500/10 hover:text-red-400 transition-colors"
                >
                  <X size={12} />
                </button>
              )}
              {(isFailed || isCancelled) && transfer.targetIp && transfer.files.some((f) => f.path) && (
                <button
                  onClick={handleRetry}
                  aria-label="Retry transfer"
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-red-400 hover:bg-red-500/10 transition-colors"
                >
                  <RotateCcw size={12} />
                </button>
              )}
              {canReveal && (
                <button
                  onClick={handleReveal}
                  aria-label="Show in folder"
                  title="Show in folder"
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-frost-300 hover:text-cyber-teal hover:bg-cyber-teal/10 transition-colors"
                >
                  <FolderOpen size={12} />
                </button>
              )}
              {IS_COMPANION && isCompleted && (
                <button
                  onClick={handleSave}
                  disabled={saving}
                  aria-label="Save to device"
                  title="Save to device"
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-frost-300 hover:text-cyber-teal hover:bg-cyber-teal/10 transition-colors disabled:opacity-50"
                >
                  {saving ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                </button>
              )}
            </div>
          </div>

          {isActive && (
            <div className="mb-2">
              <div className="h-1.5 bg-navy-700 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-linear-to-r from-cyber-teal to-cyber-blue rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${transfer.progress * 100}%` }}
                  transition={{ duration: 0.5, ease: 'easeOut' }}
                />
              </div>
            </div>
          )}

          <div className="flex items-center gap-4 text-xs text-frost-300">
            <span>{formatBytes(transfer.bytesTransferred)} / {formatBytes(transfer.totalBytes)}</span>
            {isActive && <span className="text-cyber-teal">{formatSpeed(transfer.speed)}</span>}
            <span>{formatDuration(elapsed)}</span>
          </div>

          {transfer.files.length > 1 && (
            <div className="mt-2 flex items-center gap-1 text-[11px] text-frost-400">
              <span>{transfer.files.length} files</span>
              <span>•</span>
              <span>{formatBytes(transfer.totalBytes)}</span>
            </div>
          )}

          {isFailed && transfer.error && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-red-400">
              <AlertCircle size={12} />
              {transfer.error}
            </div>
          )}

          {isAwaiting && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
              <Clock size={12} />
              Incoming transfer from {transfer.fromDevice} — waiting for your approval
            </div>
          )}

          {isCancelled && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-frost-400">
              <Ban size={12} />
              Transfer cancelled
            </div>
          )}

          {isCompleted && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-green-400">
              <Check size={12} />
              Transfer complete
              {transfer.verified && (
                <span className="flex items-center gap-1 ml-2 px-1.5 py-0.5 rounded bg-green-400/10 border border-green-400/20">
                  <ShieldCheck size={10} />
                  Chain verified
                </span>
              )}
              {IS_COMPANION && saving && (
                <span className="text-frost-400 ml-1">Saving to device…</span>
              )}
            </div>
          )}

          {IS_COMPANION && saveError && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-red-400">
              <AlertCircle size={12} />
              {saveError}
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
})
