import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, ShieldCheck, Copy, Check } from 'lucide-react'
import type { PinnedPeer } from '../../lib/types'
import { useAppStore } from '../../stores/appStore'
import { sasIconSet, sasHex } from '../../lib/sas'

interface VerifyPeerModalProps {
  peer: PinnedPeer | null
  onClose: () => void
}

/**
 * Out-of-band verification ritual: both devices open this dialog for the
 * same peer and compare the 16 icons face-to-face (call, in person, …).
 * A man-in-the-middle that substituted its key at pairing time would have
 * to reproduce this sequence on both links — it cannot, because each side
 * binds its own device ID into the derivation.
 */
export function VerifyPeerModal({ peer, onClose }: VerifyPeerModalProps) {
  const [showHex, setShowHex] = useState(false)
  const [copied, setCopied] = useState(false)
  const sas = useAppStore((s) => s.sas)
  const setSas = useAppStore((s) => s.setSas)

  useEffect(() => {
    if (!peer) return
    setShowHex(false)
    setCopied(false)
    setSas(null)
    if (peer.deviceId) {
      window.electronAPI?.send({ type: 'identity:sas', peerDeviceId: peer.deviceId })
    }
  }, [peer, setSas])

  const match = peer && sas && sas.peerDeviceId === peer.deviceId ? sas : null

  const copyHash = () => {
    if (!match) return
    navigator.clipboard?.writeText(match.hash).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {}
    )
  }

  return (
    <AnimatePresence>
      {peer !== null && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.2 }}
            className="glass-card p-6 w-full max-w-lg border border-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-cyber-teal/15 flex items-center justify-center">
                  <ShieldCheck size={20} className="text-cyber-teal" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-frost-100">Verify this device</h3>
                  <p className="text-xs text-frost-300">
                    {peer.name || 'Unnamed device'} · {peer.deviceId || 'unknown id'}
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="w-8 h-8 flex items-center justify-center rounded-lg text-frost-400 hover:bg-white/5 hover:text-frost-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {match ? (
              <>
                <div className="grid grid-cols-8 gap-2 mb-4">
                  {sasIconSet(match.codes).map((icon, i) => (
                    <div
                      key={i}
                      className="aspect-square rounded-xl bg-navy-700/60 border border-white/10 flex items-center justify-center text-2xl select-none"
                    >
                      {icon}
                    </div>
                  ))}
                </div>

                <p className="text-xs text-frost-300 mb-4 leading-relaxed">
                  Ask the other device to open{' '}
                  <span className="text-frost-100">Settings → Pinned Devices → Verify</span> for
                  this computer. All 16 icons must match, <b>in the same order</b>. A mismatch
                  means someone is between you — forget the device and pair again.
                </p>

                <div className="rounded-xl bg-navy-700/40 border border-white/5 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-frost-400">
                      {showHex ? 'Full fingerprint (SHA-256)' : 'Short code (96 bits) + full hash'}
                    </span>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setShowHex((v) => !v)}
                        className="text-xs text-cyber-teal hover:underline"
                      >
                        {showHex ? 'Show icons' : 'Show hex'}
                      </button>
                      <button
                        onClick={copyHash}
                        className="flex items-center gap-1 text-xs text-frost-400 hover:text-frost-100 transition-colors"
                      >
                        {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                        {copied ? 'Copied' : 'Copy'}
                      </button>
                    </div>
                  </div>
                  <p className="font-mono text-xs text-frost-200 break-all">
                    {showHex
                      ? sasHex(match.hash)
                      : match.codes.map((c) => c.toString(16).padStart(2, '0')).join(' ')}
                  </p>
                </div>
              </>
            ) : (
              <div className="py-8 text-center">
                {peer.deviceId ? (
                  <>
                    <div className="w-8 h-8 mx-auto mb-3 border-2 border-cyber-teal border-t-transparent rounded-full animate-spin" />
                    <p className="text-sm text-frost-300">Computing verification icons…</p>
                  </>
                ) : (
                  <p className="text-sm text-frost-400">
                    This device has no known ID — exchange a transfer first to pin it.
                  </p>
                )}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
