import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { LayoutDashboard, ArrowUpDown, FolderSync, Settings, HardDrive, MessageSquare } from 'lucide-react'
import { clsx } from 'clsx'
import { useDeviceStore } from '../../stores/deviceStore'
import { useAppStore } from '../../stores/appStore'

interface SidebarProps {
  activeTab: string
  onTabChange: (tab: string) => void
}

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'transfers', label: 'Transfers', icon: ArrowUpDown },
  { id: 'chat', label: 'Chat', icon: MessageSquare },
  { id: 'sync', label: 'Sync Folders', icon: FolderSync },
  { id: 'storage', label: 'Storage', icon: HardDrive },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  const peerCount = useDeviceStore((s) => s.devices.filter((d) => d.status === 'connected').length)
  const backendConnected = useAppStore((s) => s.backendConnected)

  return (
    <div className="flex flex-col w-56 h-full bg-navy-800/50 border-r border-white/5">
      <div className="flex-1 py-4 px-3">
        <nav className="flex flex-col gap-1">
          {navItems.map((item) => {
            const isActive = activeTab === item.id
            return (
              <motion.button
                key={item.id}
                whileHover={{ x: 4 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => onTabChange(item.id)}
                className={clsx(
                  'relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors duration-200',
                  isActive
                    ? 'text-cyber-teal bg-cyber-teal/10'
                    : 'text-frost-300 hover:text-frost-100 hover:bg-white/5'
                )}
              >
                {isActive && (
                  <motion.div
                    layoutId="sidebar-indicator"
                    className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-cyber-teal rounded-r-full"
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                )}
                <item.icon size={18} />
                {item.label}
              </motion.button>
            )
          })}
        </nav>
      </div>

      <div className="p-3 border-t border-white/5">
        <div className="glass-card p-3">
          <div className="flex items-center gap-2 mb-2">
            <div className={clsx('w-2 h-2 rounded-full', backendConnected ? 'bg-cyber-teal' : 'bg-red-400')} />
            <span className="text-xs font-medium text-frost-200">
              {backendConnected ? 'Backend Connected' : 'Backend Offline'}
            </span>
          </div>
          <p className="text-[11px] text-frost-400">
            {peerCount > 0
              ? `${peerCount} device${peerCount !== 1 ? 's' : ''} discovered`
              : 'No devices discovered yet'}
          </p>
        </div>
      </div>
    </div>
  )
}
