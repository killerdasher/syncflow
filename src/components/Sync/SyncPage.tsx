import { motion } from 'framer-motion'
import { FolderSync, Plus, FolderOpen, Trash2 } from 'lucide-react'
import { GlowButton } from '../shared/GlowButton'
import { useSettingsStore } from '../../stores/settingsStore'

export function SyncPage() {
  const syncFolders = useSettingsStore((s) => s.settings.syncFolders)
  const updateSettings = useSettingsStore((s) => s.updateSettings)

  const handleAdd = async () => {
    if (!window.electronAPI?.openDirectory) return
    const dir = await window.electronAPI.openDirectory()
    if (!dir) return
    if (syncFolders.some((f) => f.localPath === dir)) return
    updateSettings({
      syncFolders: [
        ...syncFolders,
        { localPath: dir, remoteDevice: '', remotePath: '', enabled: true, lastSync: 0 },
      ],
    })
  }

  const handleRemove = (localPath: string) => {
    updateSettings({ syncFolders: syncFolders.filter((f) => f.localPath !== localPath) })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Sync Folders</h2>
          <p className="text-sm text-frost-300">
            {syncFolders.length} folder{syncFolders.length !== 1 ? 's' : ''} added
          </p>
        </div>
        <GlowButton icon={<Plus size={14} />} onClick={handleAdd}>Add Sync Folder</GlowButton>
      </div>

      {syncFolders.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <FolderOpen size={40} className="mx-auto text-frost-400 mb-3" />
          <p className="text-sm text-frost-200 mb-1">No sync folders yet</p>
          <p className="text-xs text-frost-400">
            Add a local folder to prepare it for syncing with a paired device.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {syncFolders.map((folder, index) => (
            <motion.div
              key={folder.localPath}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: index * 0.1 }}
              className="glass-card p-5"
            >
              <div className="flex items-start justify-between mb-3">
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
                    <span className="text-xs font-medium text-frost-300">Local folder</span>
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

              <p className="text-xs text-frost-400">
                Not paired with a remote device — remote sync becomes available once a device pairing flow is configured.
              </p>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  )
}
