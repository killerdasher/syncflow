import { useState } from 'react'
import { motion } from 'framer-motion'
import { FolderSync, Plus, FolderOpen, Trash2, Send, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { GlowButton } from '../shared/GlowButton'
import { useSettingsStore, applySettings } from '../../stores/settingsStore'
import { useDeviceStore } from '../../stores/deviceStore'
import { syncFolderNow, type SyncResult } from '../../hooks/useSyncEngine'
import type { SyncFolder } from '../../lib/types'

const RESULT_TEXT: Record<SyncResult, string> = {
  sent: 'Sent — waiting for transfer to finish',
  'no-device': 'No target device selected',
  'not-connected': 'Target device is not connected',
  'no-files': 'Nothing new to send',
  'no-electron': 'File access unavailable',
  error: 'Send failed — see Transfers',
}

const INTERVALS = [
  { value: 0, label: 'Manual only' },
  { value: 1, label: 'Every minute' },
  { value: 5, label: 'Every 5 minutes' },
  { value: 15, label: 'Every 15 minutes' },
]

function fmtLastSync(ts?: number): string {
  if (!ts) return 'never'
  const d = Date.now() - ts
  if (d < 60_000) return 'just now'
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`
  return new Date(ts).toLocaleString()
}

export function SyncPage() {
  const settings = useSettingsStore((s) => s.settings)
  const updateSettings = useSettingsStore((s) => s.updateSettings)
  const devices = useDeviceStore((s) => s.devices)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<{ folder: string; text: string } | null>(null)

  const syncFolders = settings.syncFolders
  const syncable = devices.filter((d) => d.id !== 'self')

  const updateFolder = (localPath: string, updates: Partial<SyncFolder>) => {
    updateSettings({
      syncFolders: syncFolders.map((f) => (f.localPath === localPath ? { ...f, ...updates } : f)),
    })
  }

  const handleAdd = async () => {
    if (!window.electronAPI?.openDirectory) return
    const dir = await window.electronAPI.openDirectory()
    if (!dir) return
    if (syncFolders.some((f) => f.localPath === dir)) return
    updateSettings({
      syncFolders: [
        ...syncFolders,
        {
          localPath: dir,
          remoteDevice: '',
          remotePath: '',
          enabled: true,
          lastSync: 0,
          interval: 0,
        },
      ],
    })
    applySettings()
  }

  const handleRemove = (localPath: string) => {
    updateSettings({ syncFolders: syncFolders.filter((f) => f.localPath !== localPath) })
    applySettings()
  }

  const handleSyncNow = async (folder: SyncFolder) => {
    if (busy) return
    setBusy(folder.localPath)
    try {
      const result = await syncFolderNow(folder)
      setToast({ folder: folder.localPath, text: RESULT_TEXT[result] })
      setTimeout(() => setToast(null), 4000)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Sync Folders</h2>
          <p className="text-sm text-frost-300">
            {syncFolders.length} folder{syncFolders.length !== 1 ? 's' : ''} added — new and
            changed files are pushed to the paired device
          </p>
        </div>
        <GlowButton icon={<Plus size={14} />} onClick={handleAdd}>Add Sync Folder</GlowButton>
      </div>

      {syncFolders.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <FolderOpen size={40} className="mx-auto text-frost-400 mb-3" />
          <p className="text-sm text-frost-200 mb-1">No sync folders yet</p>
          <p className="text-xs text-frost-400">
            Add a local folder, pair it with a device, then push updates manually or on an
            interval.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {syncFolders.map((folder, index) => {
            const pairedDevice = syncable.find((d) => d.id === folder.remoteDevice)
            const nameInput = folder.remotePath ||
              folder.localPath.split('/').filter(Boolean).pop() || ''
            const syncing = busy === folder.localPath
            const toastHere = toast?.folder === folder.localPath ? toast.text : null

            return (
              <motion.div
                key={folder.localPath}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: index * 0.1 }}
                className="glass-card p-5"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-aqua-900/60 flex items-center justify-center">
                      <FolderSync size={20} className="text-cyber-teal" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-frost-100">
                        {folder.localPath.split('/').filter(Boolean).pop() || folder.localPath}
                      </h3>
                      <p className="text-xs text-frost-300">{folder.localPath}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-navy-700/70 border border-white/10">
                      <span className={clsx(
                        'w-1.5 h-1.5 rounded-full',
                        pairedDevice ? 'bg-green-400' : 'bg-frost-400'
                      )} />
                      <span className="text-xs font-medium text-frost-300">
                        {pairedDevice ? pairedDevice.name : 'Not paired'}
                      </span>
                    </div>
                    <button
                      onClick={() => handleRemove(folder.localPath)}
                      aria-label="Remove folder"
                      className="w-7 h-7 flex items-center justify-center rounded-lg text-frost-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-frost-300 mb-1.5">
                      Send to device
                    </label>
                    <select
                      value={folder.remoteDevice}
                      onChange={(e) => updateFolder(folder.localPath, { remoteDevice: e.target.value, lastSync: 0 })}
                      className="w-full px-3 py-2 bg-navy-700 border border-white/10 rounded-xl text-xs text-frost-100 focus:outline-none focus:border-cyber-teal/50"
                    >
                      <option value="">Choose a device…</option>
                      {syncable.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name} ({d.status})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-frost-300 mb-1.5">
                      Destination folder on peer
                    </label>
                    <input
                      type="text"
                      value={folder.remotePath}
                      placeholder={nameInput}
                      onChange={(e) => updateFolder(folder.localPath, { remotePath: e.target.value })}
                      className="w-full px-3 py-2 bg-navy-700 border border-white/10 rounded-xl text-xs text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50"
                    />
                    <p className="text-[10px] text-frost-400 mt-1">
                      Peer only accepts a folder it configured itself (default: same name)
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-frost-300 mb-1.5">
                      Auto-sync interval
                    </label>
                    <select
                      value={folder.interval}
                      onChange={(e) => updateFolder(folder.localPath, { interval: parseInt(e.target.value) })}
                      className="w-full px-3 py-2 bg-navy-700 border border-white/10 rounded-xl text-xs text-frost-100 focus:outline-none focus:border-cyber-teal/50"
                    >
                      {INTERVALS.map((iv) => (
                        <option key={iv.value} value={iv.value}>{iv.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/5">
                  <div className="flex items-center gap-3 text-xs text-frost-400">
                    <span>Last sync: {fmtLastSync(folder.lastSync)}</span>
                    {toastHere && <span className="text-cyber-teal">{toastHere}</span>}
                  </div>
                  <GlowButton
                    variant="secondary"
                    size="sm"
                    onClick={() => handleSyncNow(folder)}
                    disabled={!pairedDevice || syncing}
                    icon={syncing ? <RefreshCw size={13} className="animate-spin" /> : <Send size={13} />}
                  >
                    {syncing ? 'Sending…' : 'Sync Now'}
                  </GlowButton>
                </div>
              </motion.div>
            )
          })}
        </div>
      )}
    </div>
  )
}
