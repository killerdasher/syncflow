import { motion } from 'framer-motion'
import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface GlowButtonProps {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  icon?: ReactNode
  disabled?: boolean
  className?: string
}

export function GlowButton({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  icon,
  disabled = false,
  className,
}: GlowButtonProps) {
  return (
    <motion.button
      whileHover={{ scale: disabled ? 1 : 1.02 }}
      whileTap={{ scale: disabled ? 1 : 0.98 }}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-300',
        {
          'bg-cyber-teal/20 text-cyber-teal border border-cyber-teal/30 hover:bg-cyber-teal/30 hover:border-cyber-teal/50 hover:shadow-glow':
            variant === 'primary',
          'bg-navy-700 text-frost-100 border border-frost-300/10 hover:bg-navy-600 hover:border-frost-300/20':
            variant === 'secondary',
          'bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 hover:border-red-500/50':
            variant === 'danger',
          'bg-transparent text-frost-300 hover:text-frost-100 hover:bg-navy-700/50':
            variant === 'ghost',
        },
        {
          'px-3 py-1.5 text-xs': size === 'sm',
          'px-5 py-2.5 text-sm': size === 'md',
          'px-7 py-3 text-base': size === 'lg',
        },
        disabled && 'opacity-50 cursor-not-allowed',
        className
      )}
    >
      {icon && <span className="flex-shrink-0">{icon}</span>}
      {children}
    </motion.button>
  )
}
