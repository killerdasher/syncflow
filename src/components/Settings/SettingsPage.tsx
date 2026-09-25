import { useState } from 'react'
import { motion } from 'framer-motion'
import { User, FolderOpen, Shield, Network, Bell, Save, Check } from 'lucide-react'
import { clsx } from 'clsx'
import { useSettingsStore } from '../../stores/settingsStore'
import { GlowButton } from '../shared/GlowButton'

type SettingsTab = 'general' | 'network' | 'security' | 'folders'

const tabs = [
  { id: 'general' as SettingsTab, label: 'General', icon: User },
  { id: 'network' as SettingsTab, label: 'Network', icon: Network },
  { id: 'security' as SettingsTab, label: 'Security', icon: Shield },
  { id: 'folders' as SettingsTab, label: 'Folders', icon: FolderOpen },
]

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [saved, setSaved] = useState(false)
  const { settings, updateSettings } = useSettingsStore()

  const handleSave = () => {
    if (window.electronAPI) {
      window.electronAPI.send({
        type: 'settings:apply',
        downloadPath: settings.downloadPath,
        autoAccept: settings.autoAccept,
      })
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleAddFolder = async () => {
    if (!window.electronAPI?.openDirectory) return
    const dir = await window.electronAPI.openDirectory()
    if (!dir) return
    if (settings.syncFolders.some((f) => f.localPath === dir)) return
    updateSettings({
      syncFolders: [
        ...settings.syncFolders,
        { localPath: dir, remoteDevice: '', remotePath: '', enabled: true, lastSync: 0 },
      ],
    })
  }

  const handleRemoveFolder = (localPath: string) => {
    updateSettings({ syncFolders: settings.syncFolders.filter((f) => f.localPath !== localPath) })
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Settings</h2>
          <p className="text-sm text-frost-300">Configure your SyncFlow application</p>
        </div>
        <GlowButton
          onClick={handleSave}
          icon={saved ? <Check size={14} /> : <Save size={14} />}
          variant={saved ? 'primary' : 'secondary'}
        >
          {saved ? 'Saved!' : 'Save Changes'}
        </GlowButton>
      </div>

      <div className="flex gap-4">
        <div className="w-48 flex-shrink-0">
          <nav className="flex flex-col gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={clsx(
                  'flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200',
                  activeTab === tab.id
                    ? 'bg-cyber-teal/10 text-cyber-teal'
                    : 'text-frost-300 hover:text-frost-100 hover:bg-white/5'
                )}
              >
                <tab.icon size={16} />
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex-1">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
            className="glass-card p-6"
          >
            {activeTab === 'general' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">General Settings</h3>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Device Name</label>
                  <input
                    type="text"
                    value={settings.deviceName}
                    onChange={(e) => updateSettings({ deviceName: e.target.value })}
                    placeholder="Defaults to system hostname"
                    className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Download Path</label>
                  <input
                    type="text"
                    value={settings.downloadPath}
                    onChange={(e) => updateSettings({ downloadPath: e.target.value })}
                    className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                  />
                </div>

                <div className="flex items-center justify-between py-3 border-b border-white/5">
                  <div>
                    <p className="text-sm font-medium text-frost-200">Auto-accept transfers</p>
                    <p className="text-xs text-frost-400 mt-0.5">Automatically accept incoming file transfers</p>
                  </div>
                  <button
                    onClick={() => updateSettings({ autoAccept: !settings.autoAccept })}
                    className={clsx(
                      'relative w-11 h-6 rounded-full transition-colors duration-200',
                      settings.autoAccept ? 'bg-cyber-teal' : 'bg-navy-600'
                    )}
                  >
                    <motion.div
                      className="absolute top-1 w-4 h-4 rounded-full bg-white"
                      animate={{ left: settings.autoAccept ? 24 : 4 }}
                      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                    />
                  </button>
                </div>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Max Concurrent Transfers</label>
                  <input
                    type="range"
                    min={1}
                    max={8}
                    value={settings.maxConcurrentTransfers}
                    onChange={(e) => updateSettings({ maxConcurrentTransfers: parseInt(e.target.value) })}
                    className="w-full accent-cyber-teal"
                  />
                  <span className="text-xs text-frost-400">{settings.maxConcurrentTransfers} transfers</span>
                </div>
              </div>
            )}

            {activeTab === 'network' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Network Settings</h3>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Relay Server URL</label>
                  <input
                    type="text"
                    value={settings.relayServer}
                    onChange={(e) => updateSettings({ relayServer: e.target.value })}
                    placeholder="wss://relay.example.com"
                    className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 placeholder:text-frost-400/50 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                  />
                  <p className="text-xs text-frost-400 mt-1.5">Leave empty for LAN-only mode</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Port</label>
                  <input
                    type="number"
                    value={settings.port}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10)
                      if (!Number.isNaN(v) && v > 0 && v <= 65535) updateSettings({ port: v })
                    }}
                    className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                  />
                </div>

                <div className="glass-card p-4 bg-navy-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-2 h-2 rounded-full bg-green-400" />
                    <span className="text-sm font-medium text-frost-200">mDNS Discovery</span>
                  </div>
                  <p className="text-xs text-frost-400">
                    Automatically discovers devices on your local network using Bonjour/mDNS.
                    No configuration required.
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'security' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Security Settings</h3>

                <div className="flex items-center justify-between py-3 border-b border-white/5">
                  <div>
                    <p className="text-sm font-medium text-frost-200">Enable Encryption</p>
                    <p className="text-xs text-frost-400 mt-0.5">Encrypt all file transfers with AES-256</p>
                  </div>
                  <button
                    onClick={() => updateSettings({ encryptionEnabled: !settings.encryptionEnabled })}
                    className={clsx(
                      'relative w-11 h-6 rounded-full transition-colors duration-200',
                      settings.encryptionEnabled ? 'bg-cyber-teal' : 'bg-navy-600'
                    )}
                  >
                    <motion.div
                      className="absolute top-1 w-4 h-4 rounded-full bg-white"
                      animate={{ left: settings.encryptionEnabled ? 24 : 4 }}
                      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                    />
                  </button>
                </div>

                <div className="glass-card p-4 bg-navy-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Shield size={16} className="text-cyber-teal" />
                    <span className="text-sm font-medium text-frost-200">Security Info</span>
                  </div>
                  <ul className="text-xs text-frost-400 space-y-1.5">
                    <li>• TLS 1.3 for all connections</li>
                    <li>• AES-256-GCM file encryption</li>
                    <li>• X25519 key exchange</li>
                    <li>• Per-device pairing with QR codes</li>
                  </ul>
                </div>
              </div>
            )}

            {activeTab === 'folders' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Sync Folders</h3>
                <p className="text-sm text-frost-300 mb-4">
                  Configure folders for automatic synchronization between devices.
                </p>

                {settings.syncFolders.length === 0 ? (
                  <div className="text-center py-8">
                    <FolderOpen size={40} className="mx-auto text-frost-400 mb-3" />
                    <p className="text-sm text-frost-300">No sync folders configured</p>
                    <GlowButton variant="secondary" size="sm" className="mt-3" onClick={handleAddFolder}>
                      Add Folder
                    </GlowButton>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {settings.syncFolders.map((folder, i) => (
                      <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-navy-700/50 border border-white/5">
                        <div>
                          <p className="text-sm text-frost-200">{folder.localPath}</p>
                          <p className="text-xs text-frost-400">
                            {folder.remoteDevice ? `↔ ${folder.remoteDevice}:${folder.remotePath}` : 'Local folder — not paired'}
                          </p>
                        </div>
                        <button
                          onClick={() => handleRemoveFolder(folder.localPath)}
                          className="text-xs text-frost-400 hover:text-red-400 transition-colors"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                    <GlowButton variant="secondary" size="sm" onClick={handleAddFolder}>
                      Add Folder
                    </GlowButton>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </div>
  )
}
