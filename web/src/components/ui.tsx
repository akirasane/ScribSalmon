import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, X } from 'lucide-react'
import { on } from '../bridge'
import type { Toast } from '../types'

/* ------------------------------------------------------------------ Button */
type Variant = 'primary' | 'ghost' | 'danger'
interface BtnProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onDrag' | 'onDragStart' | 'onDragEnd' | 'onAnimationStart'> {
  variant?: Variant
  icon?: ReactNode
}

const VARIANT: Record<Variant, string> = {
  primary:
    'text-[#2b100b] font-semibold bg-gradient-to-r from-accent to-accent2 shadow-[0_0_0_0_rgba(255,138,115,0)] hover:shadow-[0_0_22px_2px_rgba(255,138,115,0.28)]',
  ghost: 'text-ink border border-line bg-card hover:bg-card-hi hover:border-accent/60',
  danger: 'text-danger border border-line bg-card hover:bg-danger/10 hover:border-danger/60',
}

export function Button({ variant = 'ghost', icon, children, className = '', ...rest }: BtnProps) {
  return (
    <motion.button
      whileHover={rest.disabled ? undefined : { scale: 1.03 }}
      whileTap={rest.disabled ? undefined : { scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 500, damping: 28 }}
      className={`inline-flex h-9 cursor-pointer items-center justify-center gap-2 rounded-full px-4 text-[13px] font-medium
        transition-[box-shadow,background-color,border-color,opacity] duration-200 disabled:cursor-not-allowed disabled:opacity-40
        ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </motion.button>
  )
}

/* ------------------------------------------------------------------ Toggle */
export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="group flex cursor-pointer items-center gap-2.5 text-[13px]"
    >
      <span
        className={`relative h-5 w-[38px] rounded-full transition-colors duration-300 ${
          checked ? 'bg-gradient-to-r from-accent to-accent2' : 'bg-[#33241e]'
        }`}
      >
        <motion.span
          className="absolute top-[3px] size-[14px] rounded-full bg-white shadow"
          animate={{ left: checked ? 21 : 3 }}
          transition={{ type: 'spring', stiffness: 520, damping: 30 }}
        />
      </span>
      <span className={`transition-colors ${checked ? 'text-ink' : 'text-mute group-hover:text-ink'}`}>{label}</span>
    </button>
  )
}

/* ------------------------------------------------------------------ Select */
export function Select<T extends string>({
  value,
  onChange,
  options,
  className = '',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
  className?: string
}) {
  return (
    <div className={`relative ${className}`}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="h-9 w-full cursor-pointer appearance-none rounded-xl border border-line bg-card-hi pr-8 pl-3 text-[13px] text-ink
          transition-colors outline-none hover:border-accent/60 focus:border-accent"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-card">
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-mute" />
    </div>
  )
}

/* ------------------------------------------------------------------ Modal */
export function Modal({ open, onClose, children, width = 'max-w-2xl' }: { open: boolean; onClose: () => void; children: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-6 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            className={`flex max-h-full w-full ${width} flex-col overflow-hidden rounded-3xl border border-line bg-surface shadow-2xl shadow-black/60`}
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/* ------------------------------------------------------------------ Toasts */
export function Toasts({ items, dismiss }: { items: Toast[]; dismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed right-5 bottom-5 z-[60] flex w-[360px] flex-col gap-2">
      <AnimatePresence initial={false}>
        {items.map((t) => (
          <motion.div
            key={t.id}
            layout
            initial={{ opacity: 0, x: 60, scale: 0.95 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 60, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
            className={`pointer-events-auto flex items-start gap-3 rounded-2xl border bg-card/95 p-3.5 text-[13px] shadow-xl backdrop-blur ${
              t.kind === 'error' ? 'border-danger/50' : 'border-accent/40'
            }`}
          >
            <span className={`mt-1 size-2 shrink-0 rounded-full ${t.kind === 'error' ? 'bg-danger' : 'bg-accent'}`} />
            <span className="selectable flex-1 leading-snug break-words">{t.text}</span>
            <button className="cursor-pointer text-mute hover:text-ink" onClick={() => dismiss(t.id)}>
              <X className="size-4" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

/* ------------------------------------------------------------------ Waveform */
export function Waveform({ active }: { active: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const state = useRef({ level: 0, active, vals: new Array<number>(240).fill(0.04) })
  state.current.active = active

  useEffect(() => on('level', (v: number) => (state.current.level = v)), [])

  useEffect(() => {
    const cv = canvas.current!
    const ctx = cv.getContext('2d')!
    let raf = 0
    let phase = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const resize = () => {
      cv.width = cv.clientWidth * dpr
      cv.height = cv.clientHeight * dpr
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(cv)

    // sample at a steady rate on a timer (rAF is throttled when the window is in the background)
    const sampler = setInterval(() => {
      const s = state.current
      phase += 0.14
      const prev = s.vals[s.vals.length - 1]
      const next = s.active ? prev * 0.4 + Math.min(1, (s.level * 9) ** 0.8) * 0.6 : 0.05 + 0.035 * Math.sin(phase)
      s.vals.push(next)
      s.vals.shift()
      if (!s.active) s.level = 0
    }, 55)

    const draw = () => {
      raf = requestAnimationFrame(draw)
      const s = state.current
      const w = cv.width
      const h = cv.height
      ctx.clearRect(0, 0, w, h)
      const step = 6 * dpr
      const n = Math.floor(w / step)
      const g = ctx.createLinearGradient(0, 0, w, 0)
      g.addColorStop(0, '#ff8a73')
      g.addColorStop(1, '#ffc65c')
      ctx.fillStyle = g
      ctx.globalAlpha = s.active ? 0.95 : 0.35
      const vals = s.vals.slice(-n)
      let x = w - vals.length * step
      for (const v of vals) {
        const bh = Math.max(3 * dpr, v * (h - 4 * dpr))
        ctx.beginPath()
        ctx.roundRect(x, (h - bh) / 2, 3 * dpr, bh, 1.5 * dpr)
        ctx.fill()
        x += step
      }
    }
    raf = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(raf)
      clearInterval(sampler)
      ro.disconnect()
    }
  }, [])

  return <canvas ref={canvas} className="h-11 w-full" />
}
