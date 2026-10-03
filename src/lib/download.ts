import { createBridgeWaiter, onBridgeBinary } from './bridge'

/**
 * Phase 3 desktop->phone receive: pulls a completed transfer's file off
 * the desktop over the authenticated WebSocket (backend/download.py) and
 * saves it on the companion.
 *
 * Protocol: request -> ready (name/size) -> ordered binary frames ->
 * file-done (byte count + sha256). Both waiters attach BEFORE the request
 * is sent so a fast small-file reply can never race listener setup; the
 * caller verifies counts (and may verify the sha256) against `ready.size`.
 *
 * Saving is platform-split: native (Capacitor) writes to the app cache
 * and opens the system share sheet — the reliable path on Android, which
 * does not let apps drop files straight into public Downloads anymore.
 * Browsers fall back to an anchor download.
 */

const READY_TIMEOUT_MS = 20000
// Generous worst-case: assume a slow 10 MB/s LAN; the waiter only guards
// against a dead stream, actual progress frames keep flowing meanwhile.
const doneTimeout = (size: number): number =>
  60000 + Math.floor((size / (10 * 1024 * 1024)) * 1000)

export interface FetchedFile {
  blob: Blob
  name: string
  /** Server-computed sha256 of the streamed bytes (verify after reassembly). */
  sha256: string
}

export async function fetchFileFromDesktop(
  transferId: string,
  fileIndex: number
): Promise<FetchedFile> {
  const chunks: ArrayBuffer[] = []
  let received = 0
  const offBinary = onBridgeBinary((data) => {
    chunks.push(data)
    received += data.byteLength
  })
  // Errors carry transferId but not fileIndex (backend validation replies);
  // downloads are one-per-connection, so transferId is enough to disambiguate.
  const readyPred = (m: any) =>
    m?.transferId === transferId &&
    (m.type === 'transfer:download:ready' || m.type === 'error')
  const donePred = (m: any) =>
    m?.transferId === transferId &&
    (m.type === 'transfer:download:file-done' || m.type === 'error')
  const readyW = createBridgeWaiter(readyPred, READY_TIMEOUT_MS)
  const doneW = createBridgeWaiter(donePred, 900000)
  try {
    let sent = false
    try {
      sent = await Promise.resolve(
        window.electronAPI?.send?.({ type: 'transfer:download', transferId, fileIndex })
      )
    } catch {
      sent = false
    }
    if (!sent) {
      throw new Error('Not connected to the desktop')
    }
    const ready = await readyW.promise
    if (!ready || ready.type !== 'transfer:download:ready') {
      throw new Error(ready?.error || 'The desktop did not start the download')
    }
    const size = Number(ready.size) || 0
    // Re-arm the done waiter with a size-aware timeout now that we know it.
    // (Both waiters were attached pre-send; this one replaces the fixed
    // 15-minute guard only if size is large enough to need more time.)
    doneW.cancel() // sync gap only: no await until doneW2 exists
    const doneW2 = createBridgeWaiter(donePred, doneTimeout(size))
    const done = await doneW2.promise
    if (!done || done.type !== 'transfer:download:file-done') {
      throw new Error(done?.error || 'Download interrupted')
    }
    if (received !== size || Number(done.received) !== size) {
      throw new Error(`Download size mismatch (got ${received} of ${size})`)
    }
    return {
      blob: new Blob(chunks, { type: 'application/octet-stream' }),
      name: String(ready.name || `file-${fileIndex}`),
      sha256: String(done.sha256 || ''),
    }
  } finally {
    offBinary()
    readyW.cancel()
    doneW.cancel()
  }
}

/**
 * Persist a fetched file on the device. Native: cache file + share sheet
 * (user picks Downloads/Drive/anything). Web: anchor download.
 */
export async function saveBlobToPhone(blob: Blob, name: string): Promise<boolean> {
  try {
    const { Capacitor } = await import('@capacitor/core')
    if (Capacitor.isNativePlatform()) {
      const { Filesystem, Directory } = await import('@capacitor/filesystem')
      const { Share } = await import('@capacitor/share')
      const written = await Filesystem.writeFile({
        path: name,
        data: blob,
        directory: Directory.Cache,
      })
      try {
        await Share.share({ files: [written.uri], dialogTitle: `Save ${name}` })
      } catch {
        /* sheet dismissed — the file is still in the cache either way */
      }
      return true
    }
  } catch {
    /* fall through to the browser path */
  }
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
  return true
}
