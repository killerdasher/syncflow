import type { FileItem } from './types'
import { bridgeBuffered, sendBridgeBinary, waitForBridgeMessage } from './bridge'

/**
 * Phase 3 phone→desktop upload: streams picked files over the authenticated
 * WebSocket (see backend/upload.py for the protocol) and hands the staged
 * bytes to the desktop's transfer engine for delivery to the target peer.
 *
 * The desktop's `command:send` path cannot be used here — it validates real
 * desktop paths, which a companion never has. Replies are routed through the
 * shared message listeners, so backend `error` frames already fail the
 * matching transfer card in useWebSocket; `false` is reserved for local
 * failures (send failed / no reply) where the caller marks the card itself.
 */

const CHUNK = 256 * 1024 // matches CHUNK_SIZE in backend/upload.py
const DRAIN_LIMIT = 4 * 1024 * 1024 // pause while the socket buffer is heavy
const DRAIN_POLL_MS = 10
const REPLY_TIMEOUT_MS = 20000

export interface UploadTarget {
  ip: string
  port?: number
  deviceId?: string
  destFolder?: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function ask(msg: any, accepted: string[], transferId: string): Promise<any | null> {
  const waiter = waitForBridgeMessage((m) => {
    if (!m || typeof m !== 'object') return false
    if (m.type === 'error') return m.transferId === transferId
    if (m.type === 'transfer:new') return m.transfer?.id === transferId
    return m.transferId === transferId && accepted.includes(m.type)
  }, REPLY_TIMEOUT_MS)
  let sent = false
  try {
    sent = await Promise.resolve(window.electronAPI?.send?.(msg))
  } catch {
    sent = false
  }
  if (!sent) return null
  return waiter
}

export async function uploadFiles(
  files: FileItem[],
  target: UploadTarget,
  transferId: string
): Promise<boolean> {
  const blobs = files.filter((f) => f.blob instanceof Blob)
  if (blobs.length !== files.length || files.length === 0) return false
  const batchTotalBytes = files.reduce((sum, f) => sum + f.size, 0)

  for (let seq = 0; seq < files.length; seq++) {
    const file = files[seq]
    const ready = await ask(
      {
        type: 'transfer:upload',
        transferId,
        seq,
        name: file.name,
        size: file.size,
        batchTotalBytes,
        targetIp: target.ip,
        ...(target.port ? { targetPort: target.port } : {}),
        ...(target.deviceId ? { targetDeviceId: target.deviceId } : {}),
        ...(target.destFolder ? { destFolder: target.destFolder } : {}),
      },
      ['transfer:upload:ready'],
      transferId
    )
    if (!ready || ready.type !== 'transfer:upload:ready') return Boolean(ready)

    const blob = file.blob as Blob
    let offset = 0
    while (offset < blob.size) {
      while (bridgeBuffered() > DRAIN_LIMIT) await sleep(DRAIN_POLL_MS)
      const piece = blob.slice(offset, Math.min(offset + CHUNK, blob.size))
      const buf = await piece.arrayBuffer()
      if (!sendBridgeBinary(buf)) return false
      offset += piece.size
    }

    const done = await ask(
      { type: 'transfer:upload:end', transferId, seq },
      ['transfer:upload:file-done'],
      transferId
    )
    if (!done || done.type !== 'transfer:upload:file-done') return Boolean(done)
  }

  const fin = await ask({ type: 'transfer:upload:finish', transferId }, [], transferId)
  if (!fin) return false
  return fin.type === 'transfer:new'
}
