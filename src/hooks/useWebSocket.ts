import { useEffect, useRef, useCallback } from 'react'
import { useDeviceStore } from '../stores/deviceStore'
import { useTransferStore } from '../stores/transferStore'
import { useChatStore } from '../stores/chatStore'
import { useAppStore } from '../stores/appStore'
import { usePeerStore } from '../stores/peerStore'
import { useSettingsStore, applySettings } from '../stores/settingsStore'
import type { ChatMessage, Transfer } from '../lib/types'

function notify(title: string, body: string, onClick: () => void) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
  try {
    const n = new Notification(title, { body, silent: false })
    n.onclick = () => {
      onClick()
      n.close()
    }
  } catch {
    /* notifications are best-effort */
  }
}

export function useWebSocket() {
  const connected = useRef(false)
  const addDevice = useDeviceStore((s) => s.addDevice)
  const updateDevice = useDeviceStore((s) => s.updateDevice)
  const removeDevice = useDeviceStore((s) => s.removeDevice)
  const updateTransfer = useTransferStore((s) => s.updateTransfer)
  const addTransfer = useTransferStore((s) => s.addTransfer)
  const addChatMessage = useChatStore((s) => s.addMessage)
  const setChatMessages = useChatStore((s) => s.setMessages)
  const setSelfId = useChatStore((s) => s.setSelfId)

  const send = useCallback((msg: any) => {
    if (window.electronAPI) {
      return window.electronAPI.send(msg)
    }
    return Promise.resolve(false)
  }, [])

  useEffect(() => {
    if (!window.electronAPI) return

    const notified = new Set<string>()

    const focusApp = (page: string) => {
      window.electronAPI.window.focus()
      useAppStore.getState().navigate(page)
    }

    const ensureTransfer = (id: string, updates: Partial<Transfer>) => {
      const exists = useTransferStore.getState().transfers.some((t) => t.id === id)
      if (!exists) {
        addTransfer({
          id,
          fromDevice: 'Unknown device',
          toDevice: 'This Device',
          startTime: Date.now(),
          ...updates,
        })
      } else {
        updateTransfer(id, updates)
      }
    }

    const handleMessage = (msg: any) => {
      switch (msg.type) {
        case 'devices:update':
          if (Array.isArray(msg.devices)) {
            msg.devices.forEach((d: any) => addDevice(d))
          }
          break
        case 'device:connected':
          addDevice(msg.device)
          break
        case 'device:disconnected':
          updateDevice(msg.deviceId, { status: 'disconnected' })
          break
        case 'device:removed':
          removeDevice(msg.deviceId)
          break
        case 'transfer:progress':
          ensureTransfer(msg.transferId, {
            progress: msg.progress,
            speed: msg.speed,
            bytesTransferred: msg.bytesTransferred,
            ...(msg.totalBytes != null ? { totalBytes: msg.totalBytes } : {}),
            ...(msg.status ? { status: msg.status } : {}),
            ...(msg.verified != null ? { verified: msg.verified } : {}),
            ...(msg.fromDevice ? { fromDevice: msg.fromDevice } : {}),
            ...(msg.toDevice ? { toDevice: msg.toDevice } : {}),
            ...(msg.files ? { files: msg.files } : {}),
            ...(msg.destPath ? { destPath: msg.destPath } : {}),
            ...(msg.destFolder ? { destFolder: msg.destFolder } : {}),
          })
          if (msg.status === 'awaiting' && !notified.has(msg.transferId)) {
            notified.add(msg.transferId)
            const from = msg.fromDevice || 'a device'
            const name = Array.isArray(msg.files) && msg.files[0]?.name
              ? `: ${msg.files[0].name}${msg.files.length > 1 ? ` +${msg.files.length - 1}` : ''}`
              : ''
            notify('Incoming transfer', `${from} wants to send you a file${name}`, () => focusApp('transfers'))
          }
          break
        case 'transfer:complete':
          ensureTransfer(msg.transferId, {
            status: 'completed',
            progress: 1,
            speed: 0,
            endTime: Date.now(),
            ...(msg.verified != null ? { verified: msg.verified } : {}),
            ...(msg.destPath ? { destPath: msg.destPath } : {}),
          })
          useSettingsStore.getState().resolvePendingSync(msg.transferId, true)
          break
        case 'transfer:error':
          ensureTransfer(msg.transferId, {
            status: 'failed',
            error: msg.error,
            speed: 0,
          })
          useSettingsStore.getState().resolvePendingSync(msg.transferId, false)
          break
        case 'transfer:cancelled':
          if (msg.success) {
            updateTransfer(msg.transferId, { status: 'cancelled', speed: 0 })
          }
          break
        case 'transfer:new':
          addTransfer({ ...(msg.transfer || {}), id: msg.transfer?.id || `tr-${Date.now()}` })
          break
        case 'error':
          // Backend validation/refusal replies — fail the matching transfer so
          // it can't sit in "pending" forever (e.g. invalid target device id)
          if (msg.transferId && useTransferStore.getState().transfers.some((t) => t.id === msg.transferId)) {
            updateTransfer(msg.transferId, {
              status: 'failed',
              error: msg.error || 'Backend rejected the request',
              speed: 0,
            })
          }
          if (typeof msg.error === 'string' && msg.error.includes('pairing')) {
            useAppStore.getState().setPairing(null)
            useAppStore.getState().setPairingError(msg.error)
          }
          break
        case 'peers:list':
        case 'peers:updated':
          if (Array.isArray(msg.peers)) {
            usePeerStore.getState().setPeers(msg.peers)
          }
          break
        case 'identity:info':
          if (msg.deviceId) setSelfId(msg.deviceId)
          if (msg.deviceName && !useSettingsStore.getState().settings.deviceName) {
            useSettingsStore.getState().updateSettings({ deviceName: msg.deviceName })
          }
          break
        case 'pairing:code':
          if (msg.code) {
            useAppStore.getState().setPairingError(null)
            useAppStore.getState().setPairing({
              code: String(msg.code),
              qr: typeof msg.qr === 'string' ? msg.qr : '',
              host: typeof msg.host === 'string' ? msg.host : '',
              port: Number(msg.port) || 18973,
              lanMode: Boolean(msg.lanMode),
              expiresAt: Date.now() + (Number(msg.expiresIn) || 300) * 1000,
            })
          }
          break
        case 'chat:message': {
          const chatMsg: ChatMessage = {
            id: msg.id,
            fromDevice: msg.fromDevice,
            deviceId: msg.deviceId,
            text: msg.text,
            timestamp: msg.timestamp,
            hash: msg.hash,
            self: msg.deviceId === useChatStore.getState().selfId,
          }
          addChatMessage(chatMsg)
          if (!chatMsg.self && !notified.has(`chat-${msg.id}`)) {
            notified.add(`chat-${msg.id}`)
            notify(chatMsg.fromDevice || 'New message', chatMsg.text, () => focusApp('chat'))
          }
          break
        }
        case 'chat:history':
          if (Array.isArray(msg.messages)) {
            const selfId = useChatStore.getState().selfId
            setChatMessages(msg.messages.map((m: any) => ({
              id: m.id,
              fromDevice: m.fromDevice,
              deviceId: m.deviceId,
              text: m.text,
              timestamp: m.timestamp,
              hash: m.hash,
              self: m.deviceId === selfId,
            })))
          }
          break
      }
    }

    window.electronAPI.onMessage(handleMessage)
    connected.current = true

    const handleStatus = (status: { connected: boolean }) => {
      useAppStore.getState().setBackendConnected(status.connected)
    }
    window.electronAPI.onStatus(handleStatus)
    // Re-request: did-finish-load may have pushed status before this listener attached
    window.electronAPI.requestStatus()

    window.electronAPI.send({ type: 'identity:get' })
    window.electronAPI.send({ type: 'devices:list' })
    window.electronAPI.send({ type: 'peers:list' })
    applySettings()

    return () => {
      window.electronAPI.removeMessageListener()
      window.electronAPI.removeStatusListener()
      connected.current = false
    }
  }, [addDevice, updateDevice, removeDevice, updateTransfer, addTransfer, addChatMessage, setChatMessages, setSelfId])

  return { send, connected: connected.current }
}
