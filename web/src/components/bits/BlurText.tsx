// Adapted from React Bits (reactbits.dev) - BlurText (words variant)
import { motion } from 'motion/react'

interface Props {
  text: string
  delay?: number
  className?: string
}

export default function BlurText({ text, delay = 110, className = '' }: Props) {
  const words = text.split(' ')
  return (
    <p className={`flex flex-wrap justify-center ${className}`}>
      {words.map((w, i) => (
        <motion.span
          key={i}
          initial={{ filter: 'blur(10px)', opacity: 0, y: -24 }}
          animate={{ filter: ['blur(10px)', 'blur(4px)', 'blur(0px)'], opacity: [0, 0.5, 1], y: [-24, 4, 0] }}
          transition={{ duration: 0.7, times: [0, 0.5, 1], delay: (i * delay) / 1000, ease: 'easeOut' }}
          style={{ display: 'inline-block', willChange: 'transform, filter, opacity' }}
        >
          {w}
          {i < words.length - 1 && ' '}
        </motion.span>
      ))}
    </p>
  )
}
