/**
 * Phase 1 transport shim — lets the SAME renderer run as a mobile companion
 * in a plain browser (and later a Capacitor webview) with no Electron.
 *
 * When preload never installed `window.electronAPI`, `installBridge()` builds
 * a compatible object over one raw WebSocket to a LAN-mode desktop backend:
 *
 *  - connection target + bearer token persist in localStorage
 *  - on open we authenticate with the saved token (`auth`) — if there is none
 *    (or it is rejected) the connect screen collects a pairing code minted on
 *    the desktop (Settings > Network) and exchanges it for a token (`pairing`)
 *  - app messages are queued until authenticated, then flushed; everything the
 *    server sends is forwarded to `onMessage` listeners (the app's switch
 *    simply ignores types it does not know)
 *  - Electron-only APIs (openFiles/openDirectory/shell/sync/tray) are left
 *    undefined on purpose: every call site already guards with `?.`, and the
 *    UI hides those entry points while `IS_COMPANION`
 *
 * The backend enforces all of this server-side too — an unauthenticated
 * socket can only send `pairing`/`auth` (see docs/networking.md).
 */
import { useAppStore } from '../stores/appStore'

export const IS_COMPANION =
  typeof window !== 'undefined' && !('electronAPI' in window)

const HOST_KEY = 'syncflow.host'
const TOKEN_KEY = 'syncflow.token'
const RETRY_MS = 3000
const HANDSHAKE_TIMEOUT_MS = 15000
const QUEUE_CAP = 500

type Listener = (msg: any) => void
type StatusListener = (s: { connected: boolean }) => void
type BinaryListener = (data: ArrayBuffer) => void

const messageListeners = new Set<Listener>()
const statusListeners = new Set<StatusListener>()
const binaryListeners = new Set<BinaryListener>()
const queue: any[] = []

let ws: WebSocket | null = null
let retryTimer: number | null = null
let handshake: { resolve: (r: string) => void; timer: number } | null = null
let authed = false

export function savedHost(): string {
  return localStorage.getItem(HOST_KEY) || ''
}

export function hasSavedToken(): boolean {
  return Boolean(localStorage.getItem(TOKEN_KEY))
}

export function forgetCompanion(): void {
  localStorage.removeItem(TOKEN_KEY)
  setAuthed(false)
}

function emitStatus(connected: boolean): void {
  statusListeners.forEach((cb) => cb({ connected }))
}

function setAuthed(v: boolean): void {
  authed = v
  useAppStore.getState().setCompanionAuthed(v)
  emitStatus(v)
}

function resolveHandshake(result: string): void {
  if (!handshake) return
  window.clearTimeout(handshake.timer)
  handshake.resolve(result)
  handshake = null
}

function rawSend(msg: any): boolean {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
    return true
  }
  return false
}

function initialFetch(): void {
  rawSend({ type: 'identity:get' })
  rawSend({ type: 'devices:list' })
  rawSend({ type: 'peers:list' })
}

function flushQueue(): void {
  while (authed && queue.length > 0) rawSend(queue.shift())
}

function onServerMessage(msg: any): void {
  switch (msg?.type) {
    case 'auth_ok':
      setAuthed(true)
      resolveHandshake('authed')
      initialFetch()
      flushQueue()
      break
    case 'auth_fail':
      localStorage.removeItem(TOKEN_KEY)
      setAuthed(false)
      resolveHandshake('auth_fail')
      break
    case 'pair_ok':
      if (msg.token) localStorage.setItem(TOKEN_KEY, String(msg.token))
      setAuthed(true)
      resolveHandshake('paired')
      initialFetch()
      flushQueue()
      break
    case 'pair_fail':
      resolveHandshake(`pair_fail:${msg.error || 'rejected'}`)
      break
    default:
      break
  }
  messageListeners.forEach((cb) => cb(msg))
}

function scheduleRetry(): void {
  if (retryTimer !== null || handshake) return // never stomp an active handshake
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    connect()
  }, RETRY_MS)
}

function connect(pendingCode?: string): void {
  const host = savedHost()
  if (!host) {
    emitStatus(false)
    return
  }
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
  if (ws) {
    try {
      ws.close()
    } catch {
      /* already gone */
    }
    ws = null
  }
  let socket: WebSocket
  try {
    socket = new WebSocket(host)
  } catch {
    resolveHandshake('connect_failed')
    scheduleRetry()
    return
  }
  ws = socket
  // Phase 3 receive: binary frames are desktop->phone file payload —
  // deliver them as ArrayBuffer to onBridgeBinary listeners instead of
  // stringifying them into the JSON path below.
  socket.binaryType = 'arraybuffer'
  socket.onopen = () => {
    if (ws !== socket) return // replaced by a newer connect() — ignore
    // The handshake payload is sent straight from the open event (no
    // polling interval: a stale interval from an earlier call could
    // otherwise hijack a newer handshake's promise).
    if (pendingCode) {
      rawSend({ type: 'pairing', code: pendingCode })
      return
    }
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      rawSend({ type: 'auth', token })
      return
    }
    setAuthed(false) // connect screen collects a pairing code
    if (handshake) resolveHandshake('need_code')
  }
  socket.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      binaryListeners.forEach((cb) => {
        try {
          cb(e.data)
        } catch {
          /* one bad listener must not break the stream */
        }
      })
      return
    }
    try {
      onServerMessage(JSON.parse(String(e.data)))
    } catch {
      /* ignore malformed frames */
    }
  }
  socket.onerror = () => {
    if (ws === socket) resolveHandshake('connect_failed')
  }
  socket.onclose = () => {
    const current = ws === socket
    if (current) ws = null
    emitStatus(false)
    // Only the socket the handshake is waiting on can fail it — a replaced
    // (closing) socket from a newer connect() must not touch the promise.
    if (current && handshake) {
      resolveHandshake('connect_failed')
      scheduleRetry()
      return
    }
    // Optimistic: a saved token re-authenticates silently on retry; a
    // rejected one (auth_fail above) drops us back to the connect screen.
    if (!localStorage.getItem(TOKEN_KEY)) setAuthed(false)
    scheduleRetry()
  }
}

/**
 * Connect (or reconnect) to `host`; with `code`, exchange a fresh pairing
 * code for a token instead of using the saved one. Resolves with
 * 'authed' | 'paired' | 'auth_fail' | 'pair_fail:<why>' |
 * 'connect_failed' | 'timeout' | 'need_host'.
 */
export function connectCompanion(host: string, code?: string): Promise<string> {
  const trimmed = host.trim()
  if (!trimmed) return Promise.resolve('need_host')
  localStorage.setItem(HOST_KEY, trimmed)
  if (code) localStorage.removeItem(TOKEN_KEY) // a fresh code wins over a stale token
  if (handshake) {
    window.clearTimeout(handshake.timer)
    handshake.resolve('superseded')
    handshake = null
  }
  return new Promise<string>((resolve) => {
    handshake = {
      resolve,
      timer: window.setTimeout(() => {
        handshake = null
        resolve('timeout')
      }, HANDSHAKE_TIMEOUT_MS),
    }
    connect(code ? code.trim().toUpperCase() : undefined)
  })
}

/**
 * Phase 3 upload plumbing: raw binary frames for file payload plus a
 * one-shot request/response waiter for the JSON control frames. These are
 * module-level (not on the electronAPI shim) because only the companion
 * streams uploads — Electron sends real desktop paths instead.
 */
export function sendBridgeBinary(data: ArrayBuffer): boolean {
  if (!authed || !ws || ws.readyState !== WebSocket.OPEN) return false
  try {
    ws.send(data)
    return true
  } catch {
    return false
  }
}

/** Bytes still queued in the socket's outbound buffer (backpressure). */
export function bridgeBuffered(): number {
  return ws && ws.readyState === WebSocket.OPEN ? ws.bufferedAmount : 0
}

/**
 * Subscribe to binary frames (Phase 3 desktop->phone download payload).
 * Returns an unsubscribe function; listeners are attach-before-send safe.
 */
export function onBridgeBinary(cb: BinaryListener): () => void {
  binaryListeners.add(cb)
  return () => {
    binaryListeners.delete(cb)
  }
}

/**
 * Subscribe to connection status. Returns an unsubscribe function.
 * Companion uploads use this to fail fast (instead of waiting out a 20s
 * reply timeout) when the socket drops mid-transfer.
 */
export function onBridgeStatus(cb: StatusListener): () => void {
  statusListeners.add(cb)
  return () => {
    statusListeners.delete(cb)
  }
}

/** True while the companion socket is open and authenticated. */
export function isBridgeConnected(): boolean {
  return authed && ws !== null && ws.readyState === WebSocket.OPEN
}

interface BridgeWaiter {
  promise: Promise<any | null>
  cancel: () => void
}

/**
 * Like waitForBridgeMessage but with an explicit cancel — callers that
 * abandon one of two pre-attached waiters (download handshake) must call
 * `cancel()` so the listener and timer do not leak until timeout.
 */
export function createBridgeWaiter(
  pred: (msg: any) => boolean,
  timeoutMs = 20000
): BridgeWaiter {
  let listener: Listener | null = null
  let timer: number | null = null
  let settled = false
  let resolveFn: (v: any | null) => void = () => {}
  const promise = new Promise<any | null>((resolve) => {
    resolveFn = resolve
    listener = (msg) => {
      if (!pred(msg)) return
      cleanup()
      resolve(msg)
    }
    timer = window.setTimeout(() => {
      cleanup()
      resolve(null)
    }, timeoutMs)
    messageListeners.add(listener)
  })
  const cleanup = () => {
    if (settled) return
    settled = true
    if (listener) messageListeners.delete(listener)
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }
  return {
    promise,
    cancel: () => {
      cleanup()
      resolveFn(null)
    },
  }
}

/** Resolve with the first frame matching `pred`, or null on timeout. */
export function waitForBridgeMessage(
  pred: (msg: any) => boolean,
  timeoutMs = 20000
): Promise<any | null> {
  return createBridgeWaiter(pred, timeoutMs).promise
}

/** Assign the shim onto `window.electronAPI` (companion mode only). */
export function installBridge(): void {
  const shim = {
    send: (msg: any): Promise<boolean> => {
      if (authed && rawSend(msg)) return Promise.resolve(true)
      if (queue.length >= QUEUE_CAP) queue.shift()
      queue.push(msg)
      return Promise.resolve(false)
    },
    onMessage: (cb: Listener): void => {
      messageListeners.add(cb)
    },
    removeMessageListener: (): void => {
      messageListeners.clear() // matches preload: drops every ws:message listener
    },
    onStatus: (cb: StatusListener): void => {
      statusListeners.add(cb)
    },
    removeStatusListener: (): void => {
      statusListeners.clear()
    },
    requestStatus: (): void => {
      emitStatus(authed && ws?.readyState === WebSocket.OPEN)
    },
    window: {
      minimize: () => {},
      maximize: () => {},
      close: () => {},
      focus: () => {
        window.focus()
      },
    },
  }
  ;(window as any).electronAPI = shim
  if (savedHost()) connect() // auto-reconnect with the saved token if any
}
