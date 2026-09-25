import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { TitleBar } from './components/shared/TitleBar'
import { AnimatedBackground } from './components/shared/AnimatedBackground'
import { Sidebar } from './components/Sidebar/Sidebar'
import { DeviceGrid } from './components/Dashboard/DeviceGrid'
import { TransferList } from './components/Transfer/TransferList'
import { FileDropZone } from './components/Transfer/FileDropZone'
import { SyncPage } from './components/Sync/SyncPage'
import { StoragePage } from './components/Storage/StoragePage'
import { SettingsPage } from './components/Settings/SettingsPage'
import { ChatPage } from './components/Chat/ChatPage'
import { useWebSocket } from './hooks/useWebSocket'
import { useTransferStore } from './stores/transferStore'
import { useDeviceStore } from './stores/deviceStore'
import { useSettingsStore } from './stores/settingsStore'
import type { Device, Transfer, FileItem } from './lib/types'

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const addTransfer = useTransferStore((s) => s.addTransfer)
  const selectedDevice = useDeviceStore((s) => s.selectedDevice)
  const deviceName = useSettingsStore((s) => s.settings.deviceName)

  const { send } = useWebSocket()

  const sendFiles = useCallback(async (files: FileItem[], targetDevice: Device) => {
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
      targetDeviceId: targetDevice.id,
    }
    addTransfer(newTransfer)

    const success = await send({
      type: 'command:send',
      targetIp: targetDevice.ip,
      targetDeviceId: targetDevice.id,
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

  const handleFilesSelected = useCallback(async (files: File[]) => {
    const fileItems: FileItem[] = files.map((f) => ({
      name: f.name,
      path: (window.electronAPI?.getFilePath?.(f)) || f.webkitRelativePath || f.name,
      size: f.size,
      type: f.type || 'application/octet-stream',
    }))

    const target = selectedDevice || useDeviceStore.getState().devices.find((d) => d.id !== 'self' && d.status === 'connected')

    if (target) {
      await sendFiles(fileItems, target)
    } else {
      const newTransfer: Transfer = {
        id: `tr-${Date.now()}`,
        fromDevice: deviceName || 'This Device',
        toDevice: 'No device selected',
        files: fileItems,
        status: 'failed',
        progress: 0,
        speed: 0,
        bytesTransferred: 0,
        totalBytes: fileItems.reduce((sum, f) => sum + f.size, 0),
        startTime: Date.now(),
        error: 'No connected target device selected',
      }
      addTransfer(newTransfer)
      setActiveTab('transfers')
    }
  }, [selectedDevice, sendFiles, addTransfer, deviceName])

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
            <FileDropZone onFilesSelected={handleFilesSelected} />
            <DeviceGrid onSendToDevice={handleSendToDevice} />
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
            <TransferList />
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
    </div>
  )
}

export default App
