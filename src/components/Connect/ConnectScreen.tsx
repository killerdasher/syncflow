import { useEffect, useState, type FormEvent } from 'react'
import { Wifi, KeyRound, QrCode } from 'lucide-react'
import { Capacitor } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'
import {
  connectCompanion,
  forgetCompanion,
  hasSavedToken,
  savedHost,
} from '../../lib/bridge'
import type { PairTarget } from '../../lib/qr'
import { takePendingPair, onPendingPair } from '../../lib/deepLink'
import { scanPairQr } from '../../lib/scan'
import { GlowButton } from '../shared/GlowButton'

/** Best-effort permission ask — must run inside a user gesture (submit/scan). */
function askNotifyPermission(): void {
  try {
    if (Capacitor.isNativePlatform()) {
      void LocalNotifications.requestPermissions().catch(() => undefined)
    } else if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      void Notification.requestPermission().catch(() => undefined)
    }
  } catch {
    /* notifications are best-effort */
  }
}

function mapError(result: string): string {
  switch (result) {
    case 'auth_fail':
      return 'Saved device token was rejected — enter a fresh pairing code.'
    case 'pair_fail:locked':
      return 'Too many wrong codes: pairing is locked for 5 minutes.'
    case 'pair_fail:expired':
      return 'That code expired — generate a new one on the desktop.'
    case 'pair_fail:no_code':
      return 'No active code on the desktop — generate one first.'
    case 'pair_fail:bad_code':
      return 'Wrong code — check the desktop screen and try again.'
    case 'connect_failed':
      return 'Could not reach that address. Is the desktop awake, in LAN mode, and reachable?'
    case 'timeout':
      return 'Timed out waiting for the desktop.'
    case 'need_host':
      return 'Enter the desktop address first.'
    case 'need_code':
      return 'Enter the pairing code shown on the desktop.'
    case 'superseded':
      return 'A newer connection attempt replaced this one.'
    default:
      return result || 'Connection failed.'
  }
}

export function ConnectScreen() {
  const [host, setHost] = useState(savedHost())
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hadToken] = useState(hasSavedToken())

  const runConnect = async (targetHost: string, targetCode?: string) => {
    setBusy(true)
    setError(null)
    const result = await connectCompanion(targetHost, targetCode || undefined)
    if (result !== 'authed' && result !== 'paired') {
      setError(mapError(result))
    } else {
      setCode('')
    }
    setBusy(false)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    askNotifyPermission()
    await runConnect(host, code || undefined)
  }

  // QR deep link path: a system camera opened syncflow://pair?... and the
  // app received it via the scheme intent (or the launch URL).
  useEffect(() => {
    const handlePair = (t: PairTarget) => {
      setHost(t.host)
      setCode('')
      void runConnect(t.host, t.code)
    }
    const initial = takePendingPair()
    if (initial) handlePair(initial)
    return onPendingPair(handlePair)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const scan = async () => {
    if (busy) return
    askNotifyPermission()
    setBusy(true)
    setError(null)
    try {
      const target = await scanPairQr()
      if (!target) {
        setError('That QR code is not a SyncFlow pairing code.')
        setBusy(false)
        return
      }
      setHost(target.host)
      setCode('')
      const result = await connectCompanion(target.host, target.code)
      if (result !== 'authed' && result !== 'paired') {
        setError(mapError(result))
      }
    } catch (e: any) {
      setError(String(e?.message || 'Scanner failed — enter the code manually.'))
    }
    setBusy(false)
  }

  const forget = () => {
    forgetCompanion()
    setCode('')
    setError(null)
  }

  return (
    <div className="h-screen w-screen flex items-center justify-center gradient-bg">
      <div className="glass-card w-[min(28rem,92vw)] p-7 bg-navy-800/80">
        <div className="flex items-center gap-2 mb-1">
          <Wifi size={18} className="text-cyber-teal" />
          <h1 className="text-lg font-semibold text-frost-100">Connect to SyncFlow</h1>
        </div>
        <p className="text-xs text-frost-400 mb-5">
          The companion joins your desktop over the local network. On the desktop open{' '}
          <span className="text-frost-200">Settings → Network → Pair a mobile device</span>,
          generate a code, and enter it below. The desktop must run in LAN mode
          (<span className="font-mono text-frost-300">SYNCFLOW_WS_HOST=0.0.0.0</span>).
        </p>

        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="block text-xs text-frost-300 mb-1">Desktop address</label>
            <input
              type="text"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="ws://192.168.1.20:18973"
              spellCheck={false}
              className="w-full rounded-xl bg-navy-900/70 border border-white/10 px-3 py-2 text-sm font-mono text-frost-100 placeholder:text-frost-500 focus:outline-none focus:border-cyber-teal/50"
            />
          </div>
          <div>
            <label className="block text-xs text-frost-300 mb-1">
              Pairing code {hadToken && '(saved device token will be used if left empty)'}
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="XXXXXXXX"
              maxLength={8}
              spellCheck={false}
              className="w-full rounded-xl bg-navy-900/70 border border-white/10 px-3 py-2 text-sm font-mono tracking-[0.3em] text-frost-100 placeholder:text-frost-500 focus:outline-none focus:border-cyber-teal/50"
            />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex items-center gap-3 pt-1">
            <GlowButton disabled={busy} icon={<KeyRound size={14} />}>
              {busy ? 'Connecting…' : 'Connect'}
            </GlowButton>
            {Capacitor.isNativePlatform() && (
              <button
                type="button"
                onClick={scan}
                disabled={busy}
                className="inline-flex items-center gap-1.5 text-xs text-frost-300 hover:text-cyber-teal transition-colors disabled:opacity-50"
              >
                <QrCode size={14} />
                Scan QR
              </button>
            )}
            {hadToken && (
              <button
                type="button"
                onClick={forget}
                className="text-xs text-frost-400 hover:text-frost-200 transition-colors"
              >
                Forget saved session
              </button>
            )}
          </div>
        </form>

        <p className="text-[11px] text-frost-500 mt-5">
          Codes are single-use and last 5 minutes. No account, no internet — traffic
          never leaves your LAN. On Android you can also scan the desktop's QR with
          your system camera — it opens this app automatically.
        </p>
      </div>
    </div>
  )
}
