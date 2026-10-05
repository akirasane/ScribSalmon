import { AnimatePresence, motion } from 'motion/react'
import { Plus, Search, Settings as Cog } from 'lucide-react'
import type { NoteBrief, RecState } from '../types'
import { fmtDate, fmtDuration } from '../lib'
import { Button } from './ui'
import Logo from './Logo'

interface Props {
  notes: NoteBrief[]
  selId: string | null
  rec: RecState
  query: string
  onQuery: (q: string) => void
  onSelect: (id: string) => void
  onNew: () => void
  onSettings: () => void
}

export default function Sidebar({ notes, selId, rec, query, onQuery, onSelect, onNew, onSettings }: Props) {
  return (
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-line bg-surface px-4 pt-6 pb-4">
      <div className="flex items-center gap-2.5 px-1">
        <Logo className="size-9 shrink-0 drop-shadow-[0_4px_14px_rgba(255,106,92,0.35)]" />
        <div className="leading-tight">
          <div className="gradient-text text-[17px] font-semibold tracking-tight">ScribSalmon</div>
          <div className="text-[11px] text-mute">voice to meeting notes</div>
        </div>
        <button
          onClick={onSettings}
          aria-label="Open settings"
          title="Settings"
          className="ml-auto grid size-9 cursor-pointer place-items-center rounded-xl border border-transparent text-mute transition-colors hover:border-line hover:bg-card hover:text-ink"
        >
          <Cog className="size-[18px]" />
        </button>
      </div>

      <label className="group relative mt-6 block">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-mute transition-colors group-focus-within:text-accent" />
        <input
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search notes…"
          className="h-10 w-full rounded-xl border border-line bg-card pr-3 pl-9 text-[13px] outline-none transition-colors placeholder:text-mute hover:border-[#3d2c25] focus:border-accent"
        />
      </label>

      <ul className="mt-4 -mr-2 flex-1 space-y-1 overflow-y-auto pr-2">
        <AnimatePresence initial={false} mode="popLayout">
          {notes.map((n) => {
            const sel = n.id === selId
            return (
              <motion.li
                key={n.id}
                layout
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -24 }}
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              >
                <button
                  onClick={() => onSelect(n.id)}
                  className="relative block w-full cursor-pointer rounded-xl px-4 py-3 text-left transition-colors hover:bg-card"
                >
                  {sel && (
                    <motion.div
                      layoutId="note-sel"
                      transition={{ type: 'spring', stiffness: 480, damping: 36 }}
                      className="absolute inset-0 rounded-xl border border-accent/35 bg-gradient-to-r from-accent/10 to-accent2/10"
                    >
                      <span className="absolute top-3.5 bottom-3.5 left-0 w-[3px] rounded-full bg-accent" />
                    </motion.div>
                  )}
                  <div className="relative">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13.5px] font-semibold">{n.title}</span>
                      {rec.id === n.id && <span className="size-2 shrink-0 animate-pulse-ring rounded-full bg-danger" />}
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-mute">
                      {fmtDate(n.created)} · {fmtDuration(n.duration)}
                    </div>
                  </div>
                </button>
              </motion.li>
            )
          })}
        </AnimatePresence>
        {notes.length === 0 && query && <li className="px-3 py-6 text-center text-[12px] text-mute">No matches</li>}
      </ul>

      <Button variant="primary" className="mt-3 h-10 w-full" icon={<Plus className="size-4" strokeWidth={2.6} />} onClick={onNew}>
        New note
      </Button>
    </aside>
  )
}
