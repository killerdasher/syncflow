import { useEffect, useRef, useCallback } from 'react'
import { useDeviceStore } from '../stores/deviceStore'
import { useTransferStore } from '../stores/transferStore'
import { useChatStore } from '../stores/chatStore'
import { useAppStore } from '../stores/appStore'
import { useSettingsStore } from '../stores/settingsStore'
import type { ChatMessage, Transfer } from '../lib/types'

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
          })
          break
        case 'transfer:complete':
          ensureTransfer(msg.transferId, {
            status: 'completed',
            progress: 1,
            speed: 0,
            endTime: Date.now(),
            ...(msg.verified != null ? { verified: msg.verified } : {}),
          })
          break
        case 'transfer:error':
          ensureTransfer(msg.transferId, {
            status: 'failed',
            error: msg.error,
            speed: 0,
          })
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
          break
        case 'identity:info':
          if (msg.deviceId) setSelfId(msg.deviceId)
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

    window.electronAPI.send({ type: 'identity:get' })
    window.electronAPI.send({ type: 'devices:list' })

    const s = useSettingsStore.getState().settings
    window.electronAPI.send({
      type: 'settings:apply',
      downloadPath: s.downloadPath,
      autoAccept: s.autoAccept,
    })

    return () => {
      window.electronAPI.removeMessageListener()
      window.electronAPI.removeStatusListener()
      connected.current = false
    }
  }, [addDevice, updateDevice, removeDevice, updateTransfer, addTransfer, addChatMessage, setChatMessages, setSelfId])

  return { send, connected: connected.current }
}
