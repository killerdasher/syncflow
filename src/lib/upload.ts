import type { FileItem } from './types'
import {
  bridgeBuffered,
  createBridgeWaiter,
  isBridgeConnected,
  onBridgeStatus,
  sendBridgeBinary,
} from './bridge'

/**
 * Phase 3 phone→desktop upload: streams picked files over the authenticated
 * WebSocket (see backend/upload.py for the protocol) and hands the staged
 * bytes to the desktop's transfer engine for delivery to the target peer.
 *
 * The desktop's `command:send` path cannot be used here — it validates real
 * desktop paths, which a companion never has.
 *
 * Interrupted transfers resume: each attempt first asks the backend for the
 * upload's resume state (`transfer:upload:resume` → nextSeq/partial), skips
 * completed files, seeks to `resumeFrom` on the partial one, and on a dropped
 * socket waits for the bridge to reconnect and retries (bounded). Replies are
 * routed through the shared message listeners, so backend `error` frames
 * already fail the matching transfer card in useWebSocket; `false` is
 * reserved for local failures (send failed / no reply) where the caller
 * marks the card itself.
 */

const CHUNK = 256 * 1024 // matches CHUNK_SIZE in backend/upload.py
const DRAIN_LIMIT = 4 * 1024 * 1024 // pause while the socket buffer is heavy
const DRAIN_POLL_MS = 10
const REPLY_TIMEOUT_MS = 20000
const RECONNECT_WAIT_MS = 20000 // backend retry is 3s + connect + auth
const MAX_ATTEMPTS = 3 // resume attempts per uploadFiles() call

export interface UploadTarget {
  ip: string
  port?: number
  deviceId?: string
  destFolder?: string
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface ResumeState {
  nextSeq: number
  partial: { seq: number; name: string; size: number; bytes: number } | null
  resumable: boolean
}

/** 'ok' | 'reply' | 'error' (card already failed in useWebSocket) | 'lost' (retry) */
type Step = 'ok' | 'reply' | 'error' | 'lost'

async function askFrame(
  msg: any,
  pred: (m: any) => boolean,
  transferId: string
): Promise<{ step: Step; frame: any }> {
  const waiter = createBridgeWaiter(pred, REPLY_TIMEOUT_MS)
  // Fail fast on a dropped socket instead of waiting out REPLY_TIMEOUT_MS.
  let disconnected = false
  const off = onBridgeStatus((s) => {
    if (!s.connected && !disconnected) {
      disconnected = true
      waiter.cancel()
    }
  })
  try {
    if (!isBridgeConnected()) return { step: 'lost', frame: null }
    let sent = false
    try {
      sent = await Promise.resolve(window.electronAPI?.send?.(msg))
    } catch {
      sent = false
    }
    if (!sent) return { step: 'lost', frame: null }
    const frame = await waiter.promise
    if (frame) {
      if (frame.type === 'error') return { step: 'error', frame }
      return { step: 'reply', frame }
    }
    return { step: 'lost', frame: null } // disconnect or reply timeout
  } finally {
    off()
  }
}

function uploadPred(transferId: string, accepted: string[]) {
  return (m: any): boolean => {
    if (!m || typeof m !== 'object') return false
    if (m.type === 'error') return m.transferId === transferId
    if (m.type === 'transfer:new') return m.transfer?.id === transferId
    return m.transferId === transferId && accepted.includes(m.type)
  }
}

/** Resolve once the bridge socket is open and authenticated again. */
function waitConnected(timeoutMs: number): Promise<boolean> {
  if (isBridgeConnected()) return Promise.resolve(true)
  return new Promise((resolve) => {
    let done = false
    let off: (() => void) | null = null
    const finish = (ok: boolean) => {
      if (done) return
      done = true
      if (off) off()
      resolve(ok)
    }
    off = onBridgeStatus((s) => {
      if (s.connected) finish(true)
    })
    setTimeout(() => finish(isBridgeConnected()), timeoutMs)
  })
}

/** 'ok' | 'error' (caller returns true; card handled backend-side) | 'lost' */
async function runAttempt(
  files: FileItem[],
  target: UploadTarget,
  transferId: string,
  batchTotalBytes: number
): Promise<Step> {
  const resume = await askFrame(
    { type: 'transfer:upload:resume', transferId },
    uploadPred(transferId, ['transfer:upload:resume:ready']),
    transferId
  )
  if (resume.step !== 'reply') return resume.step
  const state = resume.frame as ResumeState
  const startSeq = state.nextSeq
  if (
    !Number.isInteger(startSeq) ||
    startSeq < 0 ||
    startSeq > files.length ||
    (state.partial && state.partial.seq !== startSeq)
  ) {
    return 'error' // server/client batch disagreement — fail the card
  }

  for (let seq = startSeq; seq < files.length; seq++) {
    const file = files[seq]
    const ready = await askFrame(
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
      uploadPred(transferId, ['transfer:upload:ready']),
      transferId
    )
    if (ready.step !== 'reply') return ready.step

    const blob = file.blob as Blob
    let offset = typeof ready.frame.resumeFrom === 'number' ? ready.frame.resumeFrom : 0
    while (offset < blob.size) {
      while (bridgeBuffered() > DRAIN_LIMIT) await sleep(DRAIN_POLL_MS)
      const piece = blob.slice(offset, Math.min(offset + CHUNK, blob.size))
      const buf = await piece.arrayBuffer()
      if (!sendBridgeBinary(buf)) return 'lost'
      offset += piece.size
    }

    const done = await askFrame(
      { type: 'transfer:upload:end', transferId, seq },
      uploadPred(transferId, ['transfer:upload:file-done']),
      transferId
    )
    if (done.step !== 'reply') return done.step
  }

  const fin = await askFrame(
    { type: 'transfer:upload:finish', transferId },
    uploadPred(transferId, []),
    transferId
  )
  if (fin.step !== 'reply') return fin.step
  return fin.frame.type === 'transfer:new' ? 'ok' : 'error'
}

export async function uploadFiles(
  files: FileItem[],
  target: UploadTarget,
  transferId: string
): Promise<boolean> {
  const blobs = files.filter((f) => f.blob instanceof Blob)
  if (blobs.length !== files.length || files.length === 0) return false
  const batchTotalBytes = files.reduce((sum, f) => sum + f.size, 0)

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    if (attempt > 0 && !(await waitConnected(RECONNECT_WAIT_MS))) return false
    const step = await runAttempt(files, target, transferId, batchTotalBytes)
    if (step === 'error') return true // error frame already failed the card
    if (step === 'ok') return true
    // 'lost': socket dropped or reply timed out — reconnect and resume.
  }
  return false
}
