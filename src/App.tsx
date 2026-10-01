import { useState, useCallback, useMemo, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send } from 'lucide-react'
import { TitleBar } from './components/shared/TitleBar'
import { AnimatedBackground } from './components/shared/AnimatedBackground'
import { GlowButton } from './components/shared/GlowButton'
import { Sidebar } from './components/Sidebar/Sidebar'
import { DeviceGrid } from './components/Dashboard/DeviceGrid'
import { AddDeviceModal } from './components/Dashboard/AddDeviceModal'
import { DevicePickerModal } from './components/Dashboard/DevicePickerModal'
import { TransferList } from './components/Transfer/TransferList'
import { FileDropZone } from './components/Transfer/FileDropZone'
import { SyncPage } from './components/Sync/SyncPage'
import { StoragePage } from './components/Storage/StoragePage'
import { SettingsPage } from './components/Settings/SettingsPage'
import { ChatPage } from './components/Chat/ChatPage'
import { useWebSocket } from './hooks/useWebSocket'
import { useSyncEngine } from './hooks/useSyncEngine'
import { useTransferStore } from './stores/transferStore'
import { useDeviceStore } from './stores/deviceStore'
import { useSettingsStore } from './stores/settingsStore'
import { useAppStore } from './stores/appStore'
import type { Device, Transfer, FileItem } from './lib/types'

// Real peer ids are sha256-derived 32-char hex; locally added devices use
// synthetic ids (e.g. "manual-1.2.3.4-…") that must not be sent as
// targetDeviceId — the backend validates the format and the peer identity.
const REAL_DEVICE_ID_RE = /^[0-9a-f]{32}$/
const deviceIdOf = (d: Device): string | undefined => (REAL_DEVICE_ID_RE.test(d.id) ? d.id : undefined)

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [addDeviceOpen, setAddDeviceOpen] = useState(false)
  const [pickerFiles, setPickerFiles] = useState<FileItem[] | null>(null)
  const addTransfer = useTransferStore((s) => s.addTransfer)
  const devices = useDeviceStore((s) => s.devices)
  const deviceName = useSettingsStore((s) => s.settings.deviceName)
  const navTarget = useAppStore((s) => s.navTarget)
  const clearNavigate = useAppStore((s) => s.clearNavigate)

  // Notification click (or any other code) may request a page switch
  useEffect(() => {
    if (!navTarget) return
    setActiveTab(navTarget)
    clearNavigate()
  }, [navTarget, clearNavigate])

  useEffect(() => {
    if (window.electronAPI && typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {})
    }
  }, [])

  useSyncEngine()

  const connectedTargets = useMemo(
    () => devices.filter((d) => d.id !== 'self' && d.status === 'connected'),
    [devices]
  )

  const { send } = useWebSocket()

  const sendFiles = useCallback(async (files: FileItem[], targetDevice: Device) => {
    const targetDeviceId = deviceIdOf(targetDevice)
    const newTransfer: Transfer = {
      id: `tr-${Date.now()}`,
      fromDevice: deviceName || 'This Device',
      toDevice: targetDevice.name,
      files,
      status: 'pending',
      progress: 0,
      speed: 0,
      bytesTransferred: 0,
      totalBytes: files.reduce((sum, f) => sum + f.size, 0),
      startTime: Date.now(),
      targetIp: targetDevice.ip,
      targetDeviceId,
    }
    addTransfer(newTransfer)

    const success = await send({
      type: 'command:send',
      targetIp: targetDevice.ip,
      ...(targetDeviceId ? { targetDeviceId } : {}),
      files: files.map((f) => f.path),
      transferId: newTransfer.id,
    })

    if (!success) {
      useTransferStore.getState().updateTransfer(newTransfer.id, {
        status: 'failed',
        error: 'Backend not connected',
      })
    }

    setActiveTab('transfers')
  }, [addTransfer, send, deviceName])

  const pickFiles = useCallback((): Promise<FileItem[]> => {
    if (window.electronAPI?.openFiles) {
      return window.electronAPI
        .openFiles()
        .then((items) => items || [])
        .catch(() => [])
    }
    // Fallback for running the renderer in a plain browser (no preload)
    return new Promise((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      input.multiple = true
      input.addEventListener('cancel', () => resolve([]))
      input.addEventListener('change', () => {
        const arr = Array.from(input.files || [])
        resolve(
          arr.map((f) => ({
            name: f.name,
            path: window.electronAPI?.getFilePath?.(f) || f.name,
            size: f.size,
            type: f.type || 'application/octet-stream',
          }))
        )
      })
      input.click()
    })
  }, [])

  const routeFiles = useCallback(
    async (files: FileItem[]) => {
      if (files.length === 0) return
      const state = useDeviceStore.getState()
      const sel = state.selectedDevice
      if (sel && sel.id !== 'self' && sel.status === 'connected') {
        await sendFiles(files, sel)
        return
      }
      const connected = state.devices.filter((d) => d.id !== 'self' && d.status === 'connected')
      if (connected.length === 1) {
        await sendFiles(files, connected[0])
        return
      }
      // Zero or several targets — let the user choose (or add a device)
      setPickerFiles(files)
    },
    [sendFiles]
  )

  const handleQuickSend = useCallback(async () => {
    const files = await pickFiles()
    await routeFiles(files)
  }, [pickFiles, routeFiles])

  const handleSendToDevice = useCallback(async (device: Device) => {
    if (!window.electronAPI?.openFiles) {
      const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')
      fileInput?.click()
      return
    }

    const files = await window.electronAPI.openFiles()
    if (files && files.length > 0) {
      await sendFiles(files, device)
    }
  }, [sendFiles])

  const handleFilesSelected = useCallback(
    async (files: File[]) => {
      const fileItems: FileItem[] = files.map((f) => ({
        name: f.name,
        path: window.electronAPI?.getFilePath?.(f) || f.webkitRelativePath || f.name,
        size: f.size,
        type: f.type || 'application/octet-stream',
      }))
      await routeFiles(fileItems)
    },
    [routeFiles]
  )

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-6"
          >
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-frost-100">Send Files</h2>
                  <p className="text-sm text-frost-300">
                    Pick files to send — drag &amp; drop below or click the button
                  </p>
                </div>
                <GlowButton icon={<Send size={14} />} onClick={handleQuickSend}>
                  Send Files
                </GlowButton>
              </div>
              <FileDropZone onFilesSelected={handleFilesSelected} />
            </div>
            <DeviceGrid onSendToDevice={handleSendToDevice} onAddDevice={() => setAddDeviceOpen(true)} />
          </motion.div>
        )
      case 'transfers':
        return (
          <motion.div
            key="transfers"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="h-full"
          >
            <TransferList onSendFiles={handleQuickSend} />
          </motion.div>
        )
      case 'chat':
        return (
          <motion.div
            key="chat"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="h-full flex flex-col"
          >
            <ChatPage />
          </motion.div>
        )
      case 'sync':
        return (
          <motion.div
            key="sync"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <SyncPage />
          </motion.div>
        )
      case 'storage':
        return (
          <motion.div
            key="storage"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <StoragePage />
          </motion.div>
        )
      case 'settings':
        return (
          <motion.div
            key="settings"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <SettingsPage />
          </motion.div>
        )
      default:
        return null
    }
  }

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden gradient-bg">
      <AnimatedBackground />
      <TitleBar />
      <div className="flex flex-1 overflow-hidden relative z-10">
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
        <main className="flex-1 overflow-y-auto p-6">
          <AnimatePresence mode="wait">
            {renderContent()}
          </AnimatePresence>
        </main>
      </div>
      <AddDeviceModal isOpen={addDeviceOpen} onClose={() => setAddDeviceOpen(false)} />
      <DevicePickerModal
        files={pickerFiles}
        devices={connectedTargets}
        onClose={() => setPickerFiles(null)}
        onSend={(device) => {
          const files = pickerFiles
          setPickerFiles(null)
          if (files) sendFiles(files, device)
        }}
        onAddDevice={() => setAddDeviceOpen(true)}
      />
    </div>
  )
}

export default App
