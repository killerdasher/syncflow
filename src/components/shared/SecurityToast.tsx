import { useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, AlertTriangle } from 'lucide-react'
import { useAppStore } from '../../stores/appStore'

const TOAST_DURATION = 8000

export function SecurityToastContainer() {
  const { securityToasts, dismissSecurityToast } = useAppStore()

  useEffect(() => {
    const timers = securityToasts.map((t) =>
      setTimeout(() => dismissSecurityToast(t.id), TOAST_DURATION - (Date.now() - t.createdAt))
    )
    return () => timers.forEach(clearTimeout)
  }, [securityToasts, dismissSecurityToast])

  if (securityToasts.length === 0) return null

  return (
    <AnimatePresence>
      {securityToasts.map((toast) => (
        <motion.div
          key={toast.id}
          initial={{ opacity: 0, y: -20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.95 }}
          transition={{ duration: 0.25, ease: 'easeOut' }}
          className="fixed top-4 right-4 z-50 w-96 pointer-events-auto"
        >
          <div className="bg-navy-900/95 border border-red-500/50 rounded-xl p-4 shadow-2xl backdrop-blur-sm flex items-start gap-3">
            <div className="flex-shrink-0 mt-0.5 text-red-400">
              <AlertTriangle size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-frost-100">Peer identity changed</p>
              <p className="text-xs text-frost-300 mt-1 font-mono break-all">{toast.key}</p>
              <p className="text-xs text-frost-400 mt-1 line-clamp-2">{toast.reason}</p>
              <p className="text-xs text-frost-500 mt-2">
                Settings → Security → Pinned Devices to inspect
              </p>
            </div>
            <button
              onClick={() => useAppStore.getState().dismissSecurityToast(toast.id)}
              className="flex-shrink-0 text-frost-400 hover:text-frost-100 transition-colors p-1"
              aria-label="Dismiss"
            >
              <X size={16} />
            </button>
          </div>
        </motion.div>
      ))}
    </AnimatePresence>
  )
}
