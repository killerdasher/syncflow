import { motion } from 'framer-motion'
import { clsx } from 'clsx'

interface ProgressRingProps {
  progress: number
  size?: number
  strokeWidth?: number
  status?: 'transferring' | 'completed' | 'failed' | 'pending' | 'cancelled' | 'awaiting'
}

export function ProgressRing({
  progress,
  size = 48,
  strokeWidth = 3,
  status = 'transferring',
}: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (progress * circumference)

  const colorMap: Record<string, string> = {
    transferring: 'stroke-cyber-teal',
    completed: 'stroke-green-400',
    failed: 'stroke-red-400',
    pending: 'stroke-frost-400',
    cancelled: 'stroke-frost-400',
    awaiting: 'stroke-amber-400',
  }

  const bgColorMap: Record<string, string> = {
    transferring: 'stroke-cyber-teal/10',
    completed: 'stroke-green-400/10',
    failed: 'stroke-red-400/10',
    pending: 'stroke-frost-400/10',
    cancelled: 'stroke-frost-400/10',
    awaiting: 'stroke-amber-400/10',
  }

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className={bgColorMap[status]}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          className={colorMap[status]}
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-[10px] font-semibold text-frost-100">
          {Math.round(progress * 100)}%
        </span>
      </div>
    </div>
  )
}
