import { useEffect, useState } from 'react'
import { QrCode, RefreshCw, Smartphone, TriangleAlert } from 'lucide-react'
import { useAppStore } from '../../stores/appStore'
import { GlowButton } from '../shared/GlowButton'

function fmt(total: number): string {
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function PairingCard() {
  const pairing = useAppStore((s) => s.pairing)
  const error = useAppStore((s) => s.pairingError)
  const setPairingError = useAppStore((s) => s.setPairingError)
  const [, setTick] = useState(0)

  const remaining = pairing
    ? Math.max(0, Math.ceil((pairing.expiresAt - Date.now()) / 1000))
    : 0

  useEffect(() => {
    if (!pairing) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [pairing])

  const generate = () => {
    setPairingError(null)
    window.electronAPI.send({ type: 'pairing:generate' })
  }

  const active = pairing != null && remaining > 0

  return (
    <div className="glass-card p-4 bg-navy-700/50">
      <div className="flex items-center gap-2 mb-2">
        <Smartphone size={16} className="text-cyber-teal" />
        <span className="text-sm font-medium text-frost-200">Pair a mobile device</span>
      </div>
      <p className="text-xs text-frost-400 mb-3">
        Generate a one-time code the companion app on your phone uses to join over the LAN.
        Codes last 5 minutes, work once, and five wrong guesses lock pairing for 5 minutes.
        Everything stays on your network — no accounts, no internet.
      </p>

      {error && <p className="text-xs text-red-400 mb-3">{error}</p>}

      {!active && pairing && (
        <p className="text-xs text-frost-400 mb-3">Code expired — generate a fresh one.</p>
      )}

      {active && pairing ? (
        <div className="flex flex-wrap items-center gap-5">
          <div>
            <p className="font-mono text-2xl tracking-[0.35em] text-frost-100 select-all">
              {pairing.code}
            </p>
            <p className="text-xs text-cyber-teal mt-1">expires in {fmt(remaining)}</p>
            <p className="text-xs text-frost-400 font-mono mt-2">
              ws://{pairing.host}:{pairing.port}
            </p>
            {!pairing.lanMode && (
              <p className="text-xs text-amber-400 mt-2 flex items-center gap-1">
                <TriangleAlert size={12} />
                LAN mode is off — restart the backend with SYNCFLOW_WS_HOST=0.0.0.0
                so phones can reach it.
              </p>
            )}
          </div>
          {pairing.qr && (
            <img
              src={pairing.qr}
              alt="Pairing QR code"
              className="w-32 h-32 rounded-lg bg-white p-2 flex-shrink-0"
            />
          )}
        </div>
      ) : (
        <GlowButton onClick={generate} icon={<QrCode size={14} />} variant="secondary">
          Generate pairing code
        </GlowButton>
      )}

      {active && (
        <div className="mt-3">
          <GlowButton onClick={generate} icon={<RefreshCw size={12} />} variant="ghost" size="sm">
            New code (invalidates this one)
          </GlowButton>
        </div>
      )}
    </div>
  )
}
