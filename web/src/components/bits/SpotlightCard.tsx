// Adapted from React Bits (reactbits.dev) - SpotlightCard
import React, { useRef, useState } from 'react'

interface Props extends React.PropsWithChildren {
  className?: string
  spotlightColor?: string
}

const SpotlightCard: React.FC<Props> = ({ children, className = '', spotlightColor = 'rgba(255, 138, 115, 0.10)' }) => {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [opacity, setOpacity] = useState(0)

  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        const r = ref.current?.getBoundingClientRect()
        if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top })
      }}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={`relative overflow-hidden rounded-2xl border border-line bg-card/80 backdrop-blur-sm ${className}`}
    >
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-500 ease-in-out"
        style={{
          opacity,
          background: `radial-gradient(520px circle at ${pos.x}px ${pos.y}px, ${spotlightColor}, transparent 70%)`,
        }}
      />
      <div className="relative flex h-full min-h-0 flex-col">{children}</div>
    </div>
  )
}

export default SpotlightCard
