// Adapted from React Bits (reactbits.dev) - ShinyText
import React, { useRef } from 'react'
import { motion, useMotionValue, useAnimationFrame, useTransform } from 'motion/react'

interface ShinyTextProps {
  text: string
  disabled?: boolean
  speed?: number
  className?: string
  color?: string
  shineColor?: string
  spread?: number
}

const ShinyText: React.FC<ShinyTextProps> = ({
  text,
  disabled = false,
  speed = 2,
  className = '',
  color = '#7b869b',
  shineColor = '#ffffff',
  spread = 120,
}) => {
  const progress = useMotionValue(0)
  const elapsed = useRef(0)
  const last = useRef<number | null>(null)
  const duration = speed * 1000

  useAnimationFrame((time) => {
    if (disabled) {
      last.current = null
      return
    }
    if (last.current === null) {
      last.current = time
      return
    }
    elapsed.current += time - last.current
    last.current = time
    progress.set(((elapsed.current % duration) / duration) * 100)
  })

  const backgroundPosition = useTransform(progress, (p) => `${150 - p * 2}% center`)

  return (
    <motion.span
      className={`inline-block ${className}`}
      style={{
        backgroundImage: `linear-gradient(${spread}deg, ${color} 0%, ${color} 35%, ${shineColor} 50%, ${color} 65%, ${color} 100%)`,
        backgroundSize: '200% auto',
        WebkitBackgroundClip: 'text',
        backgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundPosition,
      }}
    >
      {text}
    </motion.span>
  )
}

export default ShinyText
