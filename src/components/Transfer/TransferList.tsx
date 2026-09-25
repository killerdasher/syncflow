import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowUpDown, CheckCircle, XCircle, Clock, Loader } from 'lucide-react'
import { clsx } from 'clsx'
import { useTransferStore } from '../../stores/transferStore'
import { TransferCard } from './TransferCard'

type FilterType = 'all' | 'active' | 'completed' | 'failed'

const filters: { id: FilterType; label: string; icon: any }[] = [
  { id: 'all', label: 'All', icon: ArrowUpDown },
  { id: 'active', label: 'Active', icon: Loader },
  { id: 'completed', label: 'Done', icon: CheckCircle },
  { id: 'failed', label: 'Failed', icon: XCircle },
]

const PAGE_SIZE = 60

export function TransferList() {
  const [filter, setFilter] = useState<FilterType>('all')
  const [showOlder, setShowOlder] = useState(false)
  const transfers = useTransferStore((s) => s.transfers)

  const filtered = transfers.filter((t) => {
    if (filter === 'all') return true
    if (filter === 'active') return t.status === 'transferring' || t.status === 'pending' || t.status === 'awaiting'
    if (filter === 'completed') return t.status === 'completed'
    if (filter === 'failed') return t.status === 'failed' || t.status === 'cancelled'
    return true
  })

  let activeCount = 0
  let completedCount = 0
  let failedCount = 0
  for (const t of transfers) {
    if (t.status === 'transferring' || t.status === 'awaiting') activeCount++
    else if (t.status === 'completed') completedCount++
    else if (t.status === 'failed') failedCount++
  }

  const hiddenCount = !showOlder && filtered.length > PAGE_SIZE ? filtered.length - PAGE_SIZE : 0
  const visible = hiddenCount ? filtered.slice(0, PAGE_SIZE) : filtered

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-frost-100">Transfers</h2>
          <p className="text-sm text-frost-300">
            {activeCount} active • {completedCount} completed • {failedCount} failed
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 mb-5">
        {filters.map((f) => (
          <button
            key={f.id}
            onClick={() => {
              setFilter(f.id)
              setShowOlder(false)
            }}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200',
              filter === f.id
                ? 'bg-cyber-teal/15 text-cyber-teal border border-cyber-teal/30'
                : 'text-frost-300 hover:text-frost-100 hover:bg-white/5 border border-transparent'
            )}
          >
            <f.icon size={12} />
            {f.label}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        <AnimatePresence mode="popLayout">
          {visible.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="glass-card p-12 text-center"
            >
              <ArrowUpDown size={40} className="mx-auto text-frost-400 mb-3" />
              <p className="text-frost-300">No transfers to show</p>
            </motion.div>
          ) : (
            visible.map((transfer) => (
              <TransferCard key={transfer.id} transfer={transfer} />
            ))
          )}
        </AnimatePresence>
        {hiddenCount > 0 && (
          <button
            onClick={() => setShowOlder(true)}
            className="w-full py-2.5 rounded-xl text-xs font-medium text-frost-300 hover:text-frost-100 bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
          >
            Show {hiddenCount} older transfer{hiddenCount !== 1 ? 's' : ''}
          </button>
        )}
      </div>
    </div>
  )
}
