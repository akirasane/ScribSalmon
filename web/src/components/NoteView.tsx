import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Download, Pencil, Eye, Sparkles, SpellCheck, Trash2, Wand2 } from 'lucide-react'
import type { Note, RecState, Settings } from '../types'
import { fmtDate, fmtDuration } from '../lib'
import SpotlightCard from './bits/SpotlightCard'
import ShinyText from './bits/ShinyText'
import ControlBar from './ControlBar'
import { Button } from './ui'
import { openExternal } from '../external'

interface Props {
  note: Note
  rec: RecState
  settings: Settings | null
  summarizing: boolean
  busy: boolean
  status: string
  onEdit: (patch: Partial<Pick<Note, 'title' | 'transcript' | 'summary'>>) => void
  onSettings: (patch: Partial<Settings>) => void
  onStart: () => void
  onStop: () => void
  onAddWav: () => void
  onOpenSettings: () => void
  onSummarize: () => void
  onExport: () => void
  onDelete: () => void
  onRefine: () => void
  onReview: () => void
  reviewing: boolean
}

export default function NoteView(p: Props) {
  const { note, rec } = p
  const [editSummary, setEditSummary] = useState(false)
  const tx = useRef<HTMLTextAreaElement>(null)
  const recordingHere = rec.id === note.id

  // keep the newest transcript line in view while recording
  useEffect(() => {
    if (recordingHere && tx.current) tx.current.scrollTop = tx.current.scrollHeight
  }, [note.transcript, recordingHere])

  useEffect(() => setEditSummary(false), [note.id])

  return (
    <motion.div
      key={note.id}
      className="flex h-full min-h-0 flex-col gap-3"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
    >
      {/* header */}
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <input
            value={note.title}
            onChange={(e) => p.onEdit({ title: e.target.value })}
            placeholder="Untitled note"
            className="w-full border-b border-transparent bg-transparent pb-1 text-[28px] font-semibold tracking-tight outline-none transition-colors placeholder:text-mute hover:border-line focus:border-accent"
          />
          <div className="mt-1 text-[12.5px] text-mute">
            {fmtDate(note.created)} · {note.parts} recording{note.parts === 1 ? '' : 's'} · {fmtDuration(note.duration)}
          </div>
        </div>
        <Button variant="danger" onClick={p.onDelete} icon={<Trash2 className="size-4" />} className="mt-1" aria-label="Delete note">
          Delete
        </Button>
      </div>

      <ControlBar
        note={note}
        rec={rec}
        settings={p.settings}
        onSettings={p.onSettings}
        onStart={p.onStart}
        onStop={p.onStop}
        onAddWav={p.onAddWav}
        onOpenSettings={p.onOpenSettings}
      />

      {/* panels */}
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
        <SpotlightCard className="min-h-0">
          <PanelHead title="Transcript">
            <Button
              className="h-8 px-3"
              onClick={p.onRefine}
              disabled={p.busy || recordingHere || !note.parts}
              icon={<Wand2 className="size-3.5" />}
              title="Re-transcribe the whole recording with full context (slower, more accurate)"
            >
              Refine
            </Button>
            <Button
              className="h-8 px-3"
              onClick={p.onReview}
              disabled={p.reviewing || !note.transcript.trim()}
              icon={<SpellCheck className="size-3.5" />}
              title="Ask Claude which words look mis-heard, then choose the right ones"
            >
              {p.reviewing ? 'Checking…' : 'Check words'}
            </Button>
          </PanelHead>
          <textarea
            ref={tx}
            value={note.transcript}
            onChange={(e) => p.onEdit({ transcript: e.target.value })}
            placeholder="Transcript appears here as you record (editable)…"
            className="min-h-0 flex-1 resize-none bg-transparent px-5 pb-4 text-[14.5px] leading-relaxed outline-none placeholder:text-mute"
          />
        </SpotlightCard>

        <SpotlightCard className="min-h-0" spotlightColor="rgba(255, 198, 92, 0.10)">
          <PanelHead title="Summary">
            <Button
              variant="ghost"
              className="h-8 px-3"
              onClick={() => setEditSummary((v) => !v)}
              icon={editSummary ? <Eye className="size-3.5" /> : <Pencil className="size-3.5" />}
              disabled={!note.summary}
            >
              {editSummary ? 'Preview' : 'Edit'}
            </Button>
            <Button variant="ghost" className="h-8 px-3" onClick={p.onExport} icon={<Download className="size-3.5" />}>
              Export
            </Button>
            <Button
              variant="primary"
              className="h-8 px-4"
              onClick={p.onSummarize}
              disabled={p.summarizing || !note.transcript.trim()}
              icon={<Sparkles className="size-3.5" />}
            >
              {p.summarizing ? 'Summarizing…' : 'Summarize'}
            </Button>
          </PanelHead>

          <div className="selectable min-h-0 flex-1 overflow-y-auto px-5 pb-5">
            <AnimatePresence mode="wait" initial={false}>
              {p.summarizing ? (
                <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-3 pt-1">
                  <ShinyText text="Claude is writing your meeting notes…" speed={2.2} className="text-[13px]" />
                  {[92, 78, 86, 60, 82].map((w, i) => (
                    <motion.div
                      key={i}
                      className="h-3 rounded-full bg-card-hi"
                      style={{ width: `${w}%` }}
                      animate={{ opacity: [0.35, 0.8, 0.35] }}
                      transition={{ duration: 1.6, repeat: Infinity, delay: i * 0.15 }}
                    />
                  ))}
                </motion.div>
              ) : editSummary ? (
                <motion.textarea
                  key="edit"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  value={note.summary}
                  onChange={(e) => p.onEdit({ summary: e.target.value })}
                  className="h-full w-full resize-none bg-transparent font-mono text-[13px] leading-relaxed outline-none"
                />
              ) : note.summary ? (
                <motion.div key="view" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="md">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      a: ({ href, children }) => (
                        <a href={href} rel="noopener noreferrer"
                          onClick={(e) => { e.preventDefault(); if (href) openExternal(href) }}>{children}</a>
                      ),
                      img: ({ alt }) => <span>{alt}</span>,
                    }}
                  >{note.summary}</ReactMarkdown>
                </motion.div>
              ) : (
                <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="pt-1 text-[13.5px] text-mute">
                  Press <span className="text-ink">Summarize</span> to turn the transcript into numbered meeting notes.
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </SpotlightCard>
      </div>

      {/* status */}
      <div className="relative shrink-0 pt-1">
        <div className="relative h-[3px] overflow-hidden rounded-full">
          <AnimatePresence>
            {p.busy && (
              <motion.div className="absolute inset-0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
                <div className="absolute inset-y-0 left-0 w-1/3 animate-slide rounded-full bg-gradient-to-r from-transparent via-accent to-accent2" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <div className="mt-1.5 h-4 text-[12px]">
          {p.busy ? <ShinyText text={p.status} speed={2} className="text-[12px]" /> : <span className="text-mute">{p.status}</span>}
        </div>
      </div>
    </motion.div>
  )
}

function PanelHead({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="flex shrink-0 items-center gap-2 px-5 pt-4 pb-3">
      <span className="text-[11px] font-semibold tracking-[0.12em] text-mute uppercase">{title}</span>
      <div className="flex-1" />
      {children}
    </div>
  )
}
