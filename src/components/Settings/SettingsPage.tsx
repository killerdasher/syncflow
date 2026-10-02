import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { User, FolderOpen, Shield, Network, Save, Check, KeyRound, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useSettingsStore, applySettings } from '../../stores/settingsStore'
import { usePeerStore } from '../../stores/peerStore'
import { GlowButton } from '../shared/GlowButton'

type SettingsTab = 'general' | 'network' | 'security' | 'folders'

const tabs = [
  { id: 'general' as SettingsTab, label: 'General', icon: User },
  { id: 'network' as SettingsTab, label: 'Network', icon: Network },
  { id: 'security' as SettingsTab, label: 'Security', icon: Shield },
  { id: 'folders' as SettingsTab, label: 'Folders', icon: FolderOpen },
]

function timeAgo(ts?: number): string {
  if (!ts) return '—'
  // Backend stores epoch seconds (time.time()); tolerate ms as well
  const t = ts < 1e12 ? ts * 1000 : ts
  const d = Date.now() - t
  if (d < 60_000) return 'just now'
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`
  return new Date(t).toLocaleDateString()
}

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [saved, setSaved] = useState(false)
  const { settings, updateSettings } = useSettingsStore()
  const peers = usePeerStore((s) => s.peers)

  // Keep the local pinned-peer view fresh while this page is open
  useEffect(() => {
    window.electronAPI?.send({ type: 'peers:list' })
  }, [activeTab])

  const handleSave = () => {
    applySettings()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleForget = (key: string) => {
    window.electronAPI?.send({ type: 'peers:forget', key })
  }

  const handleAddFolder = async () => {
    if (!window.electronAPI?.openDirectory) return
    const dir = await window.electronAPI.openDirectory()
    if (!dir) return
    if (settings.syncFolders.some((f) => f.localPath === dir)) return
    updateSettings({
      syncFolders: [
        ...settings.syncFolders,
        { localPath: dir, remoteDevice: '', remotePath: '', enabled: true, lastSync: 0, interval: 0 },
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
                  <p className="text-xs text-frost-400 mt-1.5">
                    Shown to other devices and used for mDNS discovery.
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">Download Path</label>
                  <input
                    type="text"
                    value={settings.downloadPath}
                    onChange={(e) => updateSettings({ downloadPath: e.target.value })}
                    className="w-full px-4 py-2.5 bg-navy-700 border border-white/10 rounded-xl text-sm text-frost-100 focus:outline-none focus:border-cyber-teal/50 focus:ring-1 focus:ring-cyber-teal/20 transition-all"
                  />
                  <p className="text-xs text-frost-400 mt-1.5">
                    Where incoming files are saved. Must be inside your home directory.
                  </p>
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
                  <label className="block text-sm font-medium text-frost-200 mb-1.5">
                    Max Concurrent Outgoing Transfers: {settings.maxConcurrent}
                  </label>
                  <input
                    type="range"
                    min={1}
                    max={8}
                    value={settings.maxConcurrent}
                    onChange={(e) => updateSettings({ maxConcurrent: parseInt(e.target.value) })}
                    className="w-full accent-cyber-teal"
                  />
                  <p className="text-xs text-frost-400">
                    Additional sends queue until a slot frees up (1–8).
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'network' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Network</h3>

                <div className="glass-card p-4 bg-navy-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-2 h-2 rounded-full bg-green-400" />
                    <span className="text-sm font-medium text-frost-200">mDNS Discovery (Bonjour)</span>
                  </div>
                  <p className="text-xs text-frost-400">
                    Devices on your local network are discovered automatically — no configuration
                    required. Transfers are direct peer-to-peer connections between devices on the
                    same LAN. There are no servers, relays, or accounts.
                  </p>
                </div>

                <div className="glass-card p-4 bg-navy-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Network size={16} className="text-cyber-teal" />
                    <span className="text-sm font-medium text-frost-200">Adding devices manually</span>
                  </div>
                  <p className="text-xs text-frost-400">
                    If mDNS is blocked on your network, use “Add Device” on the dashboard to
                    enter a peer’s IP address directly. Both devices must be reachable on the
                    same network (or routed).
                  </p>
                </div>
              </div>
            )}

            {activeTab === 'security' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Security</h3>

                <div className="glass-card p-4 bg-navy-700/50">
                  <div className="flex items-center gap-2 mb-2">
                    <Shield size={16} className="text-cyber-teal" />
                    <span className="text-sm font-medium text-frost-200">How your transfers are protected</span>
                  </div>
                  <ul className="text-xs text-frost-400 space-y-1.5">
                    <li>• End-to-end encryption: AES-256-GCM (files and messages are unreadable to anyone in between)</li>
                    <li>• X25519 key exchange + Ed25519 signatures (forward-secret session keys)</li>
                    <li>• Trust-on-first-use pinning: each device’s identity is pinned on first contact</li>
                    <li>• Per-chunk SHA-256 verification with blockchain-style chaining</li>
                    <li>• Transport is a direct LAN connection — there is no TLS layer; security comes from the end-to-end encryption above</li>
                  </ul>
                </div>

                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <KeyRound size={14} className="text-cyber-teal" />
                    <span className="text-sm font-medium text-frost-200">Pinned Devices</span>
                    <span className="text-xs text-frost-400">({peers.length})</span>
                  </div>
                  {peers.length === 0 ? (
                    <p className="text-xs text-frost-400">
                      No devices pinned yet. A device is pinned the first time you exchange a
                      transfer or chat with it.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {peers.map((peer) => (
                        <div
                          key={peer.key}
                          className="flex items-center justify-between p-3 rounded-xl bg-navy-700/50 border border-white/5"
                        >
                          <div className="min-w-0">
                            <p className="text-sm text-frost-200 truncate">
                              {peer.name || 'Unnamed device'}
                            </p>
                            <p className="text-xs text-frost-400 font-mono truncate">
                              {peer.key} · pinned {timeAgo(peer.firstSeen)} · seen {timeAgo(peer.lastSeen)}
                            </p>
                          </div>
                          <button
                            onClick={() => handleForget(peer.key)}
                            className="flex items-center gap-1 text-xs text-frost-400 hover:text-red-400 transition-colors flex-shrink-0 ml-3"
                          >
                            <Trash2 size={12} />
                            Forget
                          </button>
                        </div>
                      ))}
                      <p className="text-xs text-frost-400">
                        Forget a device to clear its pinned identity — useful if a peer was
                        reinstalled. The next contact re-pins it.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'folders' && (
              <div className="space-y-5">
                <h3 className="text-base font-semibold text-frost-100 mb-4">Sync Folders</h3>
                <p className="text-sm text-frost-300 mb-4">
                  Configure folders for synchronization between devices. Pairing and intervals are
                  managed on the Sync page.
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
                            {folder.remoteDevice ? `↔ ${folder.remotePath || 'same name'}` : 'Local folder — not paired'}
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
