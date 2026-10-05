import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Check, ChevronLeft, ChevronRight, PencilLine, Undo2 } from 'lucide-react'
import type { ReviewItem } from '../types'
import { Button, Modal } from './ui'

interface Props {
  open: boolean
  items: ReviewItem[]
  onClose: () => void
  /** pairs [original, replacement] chosen by the user */
  onApply: (fixes: [string, string][]) => void
}

/** Human-in-the-loop: one garbled phrase at a time, pick 1-3 candidates, keep the original, or type your own. */
export default function ReviewModal({ open, items, onClose, onApply }: Props) {
  const [i, setI] = useState(0)
  const [choice, setChoice] = useState<Record<number, string | null>>({}) // null/undefined = keep original
  const [custom, setCustom] = useState<Record<number, string>>({})
  const [dir, setDir] = useState(1)

  useEffect(() => {
    if (open) {
      setI(0)
      setChoice({})
      setCustom({})
    }
  }, [open, items])

  const item = items[i]
  const fixes = useMemo(
    () =>
      items
        .map((it, k) => [it.original, (custom[k]?.trim() ? custom[k].trim() : choice[k]) ?? null] as const)
        .filter((f): f is readonly [string, string] => !!f[1] && f[1] !== f[0])
        .map((f) => [f[0], f[1]] as [string, string]),
    [items, choice, custom],
  )

  const go = (n: number) => {
    setDir(n > i ? 1 : -1)
    setI(Math.max(0, Math.min(items.length - 1, n)))
  }
  const pick = (opt: string | null) => {
    setChoice((c) => ({ ...c, [i]: opt }))
    setCustom((c) => ({ ...c, [i]: '' }))
  }

  useEffect(() => {
    if (!open || !item) return
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return
      const n = Number(e.key)
      if (n >= 1 && n <= item.options.length) {
        pick(item.options[n - 1])
        if (i < items.length - 1) setTimeout(() => go(i + 1), 220)
      } else if (e.key === '0') pick(null)
      else if (e.key === 'ArrowRight') go(i + 1)
      else if (e.key === 'ArrowLeft') go(i - 1)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, item, i, items.length])

  if (!item) return <Modal open={false} onClose={onClose}>{null}</Modal>
  const selected = custom[i]?.trim() ? '__custom__' : (choice[i] ?? null)

  return (
    <Modal open={open} onClose={onClose} width="max-w-2xl">
      <div className="flex min-h-0 flex-col gap-5 overflow-y-auto p-7">
        <div>
          <div className="flex items-baseline justify-between">
            <h2 className="text-[20px] font-semibold tracking-tight">Check unclear words</h2>
            <span className="font-mono text-[12px] text-mute">
              {i + 1} / {items.length}
            </span>
          </div>
          <p className="mt-1 text-[13px] text-mute">
            The speech recognizer may have mis-heard this phrase. Which one is correct?
          </p>
          <div className="mt-3 h-1 overflow-hidden rounded-full bg-card-hi">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-accent to-accent2"
              animate={{ width: `${((i + 1) / items.length) * 100}%` }}
              transition={{ type: 'spring', stiffness: 220, damping: 28 }}
            />
          </div>
        </div>

        <AnimatePresence mode="wait" initial={false} custom={dir}>
          <motion.div
            key={i}
            custom={dir}
            initial={{ opacity: 0, x: 30 * dir }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -30 * dir }}
            transition={{ duration: 0.18 }}
            className="space-y-4"
          >
            {/* context */}
            <div className="selectable rounded-2xl border border-line bg-card p-4 text-[15px] leading-relaxed">
              <span className="text-mute">…{item.before}</span>
              <mark className="rounded-md bg-danger/20 px-1 py-0.5 text-ink underline decoration-danger decoration-wavy underline-offset-4">
                {item.original}
              </mark>
              <span className="text-mute">{item.after}…</span>
              {item.reason && <div className="mt-2 text-[12px] text-mute">Why: {item.reason}</div>}
            </div>

            {/* options */}
            <div className="space-y-2">
              {item.options.map((o, k) => (
                <Option key={o} n={k + 1} active={selected === o} onClick={() => pick(o)}>
                  {o}
                </Option>
              ))}
              <Option n={0} active={selected === null} onClick={() => pick(null)} icon={<Undo2 className="size-4" />} muted>
                Keep original
              </Option>
              <div
                className={`flex items-center gap-3 rounded-xl border px-3 py-2 transition-colors ${
                  selected === '__custom__' ? 'border-accent bg-accent/10' : 'border-line bg-card'
                }`}
              >
                <PencilLine className="size-4 shrink-0 text-mute" />
                <input
                  value={custom[i] ?? ''}
                  onChange={(e) => setCustom((c) => ({ ...c, [i]: e.target.value }))}
                  placeholder="Type my own correction…"
                  className="h-8 w-full bg-transparent text-[14px] outline-none placeholder:text-mute"
                />
              </div>
            </div>
          </motion.div>
        </AnimatePresence>

        <div className="flex items-center gap-2 pt-1">
          <Button onClick={() => go(i - 1)} disabled={i === 0} icon={<ChevronLeft className="size-4" />}>
            Back
          </Button>
          <Button onClick={() => go(i + 1)} disabled={i === items.length - 1} icon={<ChevronRight className="size-4" />}>
            Skip
          </Button>
          <div className="flex-1" />
          <span className="text-[12px] text-mute">{fixes.length} fix{fixes.length === 1 ? '' : 'es'} selected</span>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={fixes.length === 0} icon={<Check className="size-4" strokeWidth={2.6} />} onClick={() => onApply(fixes)}>
            Apply
          </Button>
        </div>
        <p className="-mt-2 text-[11.5px] text-mute">Keyboard: 1-3 choose and continue · 0 keep original · ← → navigate</p>
      </div>
    </Modal>
  )
}

function Option({
  n,
  active,
  onClick,
  children,
  icon,
  muted,
}: {
  n: number
  active: boolean
  onClick: () => void
  children: React.ReactNode
  icon?: React.ReactNode
  muted?: boolean
}) {
  return (
    <motion.button
      whileHover={{ x: 3 }}
      whileTap={{ scale: 0.985 }}
      onClick={onClick}
      className={`selectable flex w-full cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-[14.5px] transition-colors ${
        active ? 'border-accent bg-accent/10' : 'border-line bg-card hover:border-accent/50'
      } ${muted && !active ? 'text-mute' : ''}`}
    >
      <span
        className={`grid size-6 shrink-0 place-items-center rounded-lg font-mono text-[11.5px] ${
          active ? 'bg-accent text-[#2b100b]' : 'bg-card-hi text-mute'
        }`}
      >
        {icon ?? n}
      </span>
      <span className="flex-1">{children}</span>
      {active && <Check className="size-4 text-accent" />}
    </motion.button>
  )
}
