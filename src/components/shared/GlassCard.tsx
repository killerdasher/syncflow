import { motion } from 'framer-motion'
import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface GlassCardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  onClick?: () => void
  animate?: boolean
}

export function GlassCard({ children, className, hover = false, onClick, animate = true }: GlassCardProps) {
  const Component = animate ? motion.div : 'div'
  const animateProps = animate
    ? {
        initial: { opacity: 0, y: 15 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.4 },
      }
    : {}

  return (
    <Component
      className={clsx(
        'glass-card p-5 transition-all duration-300',
        hover && 'glass-card-hover cursor-pointer',
        onClick && 'cursor-pointer',
        className
      )}
      onClick={onClick}
      {...animateProps}
    >
      {children}
    </Component>
  )
}
