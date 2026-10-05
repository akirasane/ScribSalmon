import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Plus } from 'lucide-react'
import { bridge, on } from './bridge'
import { appendLine } from './lib'
import type { Note, NoteBrief, NotePatch, RecState, ReviewItem, Settings, SettingsPatch, Toast } from './types'
import Aurora from './components/bits/Aurora'
import BlurText from './components/bits/BlurText'
import Logo from './components/Logo'
import Sidebar from './components/Sidebar'
import NoteView from './components/NoteView'
import SettingsModal from './components/SettingsModal'
import ReviewModal from './components/ReviewModal'
import { Button, Modal, Toasts } from './components/ui'

export default function App() {
  const [notes, setNotes] = useState<NoteBrief[]>([])
  const [query, setQuery] = useState('')
  const [selId, setSelId] = useState<string | null>(null)
  const [note, setNote] = useState<Note | null>(null)
  const [rec, setRec] = useState<RecState>({ id: null })
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Ready')
  const [summarizing, setSummarizing] = useState(false)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [ready, setReady] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([])
  const [reviewOpen, setReviewOpen] = useState(false)
  const [confirmRefine, setConfirmRefine] = useState(false)
  const [stopping, setStopping] = useState(false)

  const noteRef = useRef<Note | null>(null)
  noteRef.current = note
  const selRef = useRef<string | null>(null)
  selRef.current = selId
  const queryRef = useRef('')
  queryRef.current = query
  const dirtyFields = useRef(new Set<'title' | 'transcript' | 'summary'>())
  const timer = useRef<number | undefined>(undefined)
  const toastId = useRef(0)

  const toast = useCallback((kind: Toast['kind'], text: string) => {
    const id = ++toastId.current
    setToasts((t) => [...t, { id, kind, text }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 8000 : 4000)
  }, [])
  const guard = useCallback(
    async <T,>(p: Promise<T>): Promise<T | undefined> => {
      try {
        return await p
      } catch (e) {
        toast('error', e instanceof Error ? e.message : String(e))
      }
    },
    [toast],
  )

  const refreshList = useCallback(async (q?: string) => {
    const list = await bridge.listNotes(q ?? queryRef.current).catch(() => null)
    if (list) setNotes(list)
    return list
  }, [])

  const flush = useCallback(async () => {
    window.clearTimeout(timer.current)
    const n = noteRef.current
    if (!dirtyFields.current.size || !n) return
    const fields = [...dirtyFields.current]
    dirtyFields.current.clear()
    const id = n.id
    const patch: NotePatch = {}
    if (fields.includes('title')) patch.title = n.title
    if (fields.includes('transcript')) {
      patch.transcript = n.transcript
      patch.transcript_rev = n.transcript_rev
    }
    if (fields.includes('summary')) {
      patch.summary = n.summary
      patch.summary_rev = n.summary_rev
    }
    const res = await guard(bridge.saveNote(id, patch))
    if (!res) {
      // save failed: keep the edits marked so the next flush retries them
      if (noteRef.current?.id === id) fields.forEach((f) => dirtyFields.current.add(f))
      return
    }
    setNotes((l) => l.map((x) => (x.id === res.id ? { ...x, id: res.id, title: res.title, created: res.created, duration: res.duration, parts: res.parts } : x)))
    if (res.appended?.length) {
      // live text arrived while we were saving: merge it into the local copy and save again
      setNote((cur) =>
        cur?.id === id ? { ...cur, transcript: res.appended!.reduce(appendLine, cur.transcript), transcript_rev: res.transcript_rev } : cur,
      )
      dirtyFields.current.add('transcript')
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => void flushRef.current(), 800)
    }
    const lost = res.conflict ?? []
    if (lost.length) {
      if (lost.includes('transcript')) toast('error', 'Transcript was replaced by Refine; your recent edit was discarded.')
      if (lost.includes('summary')) toast('error', 'Summary was regenerated; your recent edit was discarded.')
      const fresh = await bridge.getNote(id).catch(() => null)
      if (fresh) setNote((cur) => (cur?.id === id ? fresh : cur))
    }
  }, [guard, toast])
  const flushRef = useRef(flush)
  flushRef.current = flush

  const edit = useCallback(
    (patch: Partial<Pick<Note, 'title' | 'transcript' | 'summary'>>) => {
      setNote((n) => (n ? { ...n, ...patch } : n))
      if (patch.title !== undefined) setNotes((l) => l.map((x) => (x.id === selRef.current ? { ...x, title: patch.title! } : x)))
      for (const k of ['title', 'transcript', 'summary'] as const) if (patch[k] !== undefined) dirtyFields.current.add(k)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(flush, 800)
    },
    [flush],
  )

  const select = useCallback(
    async (id: string | null) => {
      await flush()
      setSelId(id)
      if (!id) return setNote(null)
      const n = await guard(bridge.getNote(id))
      if (n) setNote(n)
    },
    [flush, guard],
  )

  // ---- initial load + backend events
  useEffect(() => {
    ;(async () => {
      const [list, s] = await Promise.all([bridge.listNotes('').catch(() => []), bridge.getSettings().catch(() => null)])
      setNotes(list)
      if (s) setSettings(s)
      if (list[0]) {
        setSelId(list[0].id)
        const n = await bridge.getNote(list[0].id).catch(() => null)
        if (n) setNote(n)
      }
      setReady(true)
    })()

    const offs = [
      on('text', ({ id, text, rev }: { id: string; text: string; rev?: number }) => {
        if (id !== selRef.current) return
        setNote((n) => {
          if (!n || n.id !== id) return n
          if (rev !== undefined && rev <= n.transcript_rev) return n // already merged by a save
          return { ...n, transcript: appendLine(n.transcript, text), transcript_rev: rev ?? n.transcript_rev }
        })
      }),
      on('summary', ({ id, markdown, rev }: { id: string; markdown: string | null; rev?: number }) => {
        setSummarizing(false)
        if (markdown && id === selRef.current)
          setNote((n) => (n && n.id === id ? { ...n, summary: markdown, summary_rev: rev ?? n.summary_rev } : n))
      }),
      on('transcript', ({ id, text, rev }: { id: string; text: string; rev?: number }) => {
        if (id === selRef.current) setNote((n) => (n && n.id === id ? { ...n, transcript: text, transcript_rev: rev ?? n.transcript_rev } : n))
      }),
      on('review', ({ id, items }: { id: string; items: ReviewItem[] | null }) => {
        setReviewing(false)
        if (id !== selRef.current || !items) return
        if (items.length) {
          setReviewItems(items)
          setReviewOpen(true)
        } else toast('info', 'No unclear words found.')
      }),
      on('status', (m: string) => setStatus(m)),
      on('busy', (b: boolean) => setBusy(b)),
      on('error', (m: string) => toast('error', m)),
      on('recording', (r: RecState) => setRec(r)),
      on('notes', () => {
        refreshList()
        const id = selRef.current
        if (id) bridge.getNote(id).then((n) => setNote((cur) => (cur && cur.id === id && dirtyFields.current.size === 0 ? { ...cur, duration: n.duration, parts: n.parts } : cur))).catch(() => {})
      }),
    ]
    const bye = () => void flushRef.current()
    window.addEventListener('beforeunload', bye)
    window.__flushNow = () => flushRef.current()
    return () => {
      delete window.__flushNow
      offs.forEach((o) => o())
      window.removeEventListener('beforeunload', bye)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // search
  useEffect(() => {
    const t = setTimeout(() => refreshList(query), 180)
    return () => clearTimeout(t)
  }, [query, refreshList])

  // ---- actions
  const newNote = async () => {
    await flush()
    const n = await guard(bridge.createNote())
    if (!n) return
    setQuery('')
    await refreshList('')
    setSelId(n.id)
    setNote(n)
  }

  const removeNote = async () => {
    const n = noteRef.current
    if (!n) return
    setConfirmDelete(false)
    window.clearTimeout(timer.current)
    dirtyFields.current.clear()
    if (!(await guard(bridge.deleteNote(n.id)))) return
    const list = (await refreshList()) ?? []
    await select(list[0]?.id ?? null)
  }

  const patchSettings = async (patch: SettingsPatch) => {
    // the server response is the source of truth (secret keys always come back blank)
    const saved = await guard(bridge.saveSettings(patch))
    if (saved) setSettings(saved)
  }

  const checkWords = async () => {
    if (!note) return
    await flush()
    setReviewing(true)
    if (!(await guard(bridge.review(note.id, note.transcript)))) setReviewing(false)
  }

  const applyFixes = (fixes: [string, string][]) => {
    if (!note) return
    let t = note.transcript
    let n = 0
    for (const [from, to] of fixes) {
      if (t.includes(from)) {
        t = t.replace(from, () => to)
        n++
      }
    }
    edit({ transcript: t })
    setReviewOpen(false)
    toast('info', `Applied ${n} fix${n === 1 ? '' : 'es'}.`)
  }

  const refine = async () => {
    if (!note) return
    setConfirmRefine(false)
    await flush()
    await guard(bridge.retranscribe(note.id))
  }

  const openSettings = async () => {
    if (!settings) {
      const s = await guard(bridge.getSettings())
      if (!s) return
      setSettings(s)
    }
    setSettingsOpen(true)
  }

  const start = async () => {
    if (!note) return
    await flush()
    const r = await guard(
      bridge.startRecording(note.id, {
        system: settings?.use_system,
        mic: settings?.use_mic,
        engine: settings?.engine,
        language: settings?.language,
      }),
    )
    if (r) setRec({ id: r.id, started: r.started })
  }

  const stop = async () => {
    if (stopping) return
    setStopping(true)
    try {
      await guard(bridge.stopRecording())
    } finally {
      setStopping(false)
    }
  }

  const summarize = async () => {
    if (!note) return
    await flush()
    setSummarizing(true)
    if (!(await guard(bridge.summarize(note.id, note.transcript)))) setSummarizing(false)
  }

  return (
    <div className="flex h-full bg-bg">
      <Sidebar
        notes={notes}
        selId={selId}
        rec={rec}
        query={query}
        onQuery={setQuery}
        onSelect={(id) => id !== selId && select(id)}
        onNew={newNote}
        onSettings={openSettings}
      />

      <main className="relative min-w-0 flex-1 overflow-hidden">
        {/* React Bits Aurora, very faint, fades out downward */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-80 opacity-[0.28]"
          style={{ maskImage: 'linear-gradient(to bottom, black, transparent)', WebkitMaskImage: 'linear-gradient(to bottom, black, transparent)' }}
        >
          <Aurora />
        </div>

        <div className="relative h-full px-8 pt-7 pb-4">
          <AnimatePresence mode="wait" initial={false}>
            {note ? (
              <NoteView
                key={note.id}
                note={note}
                rec={stopping ? { ...rec, stopping } : rec}
                settings={settings}
                summarizing={summarizing}
                busy={busy}
                status={status}
                onEdit={edit}
                onSettings={patchSettings}
                onStart={start}
                onStop={stop}
                onAddWav={async () => {
                  await flush()
                  await guard(bridge.addWav(note.id))
                }}
                onOpenSettings={openSettings}
                onSummarize={summarize}
                onExport={async () => {
                  await flush()
                  const p = await guard(bridge.exportNote(note.id))
                  if (p) toast('info', `Exported to ${p}`)
                }}
                onDelete={() => setConfirmDelete(true)}
                onRefine={() => setConfirmRefine(true)}
                onReview={checkWords}
                reviewing={reviewing}
              />
            ) : (
              ready && (
                <motion.div key="empty" className="flex h-full flex-col items-center justify-center gap-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <motion.div
                    className="mb-2"
                    animate={{ y: [0, -7, 0] }}
                    transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
                  >
                    <Logo className="size-24 drop-shadow-[0_10px_30px_rgba(255,106,92,0.35)]" />
                  </motion.div>
                  <BlurText text="No notes yet" className="text-[26px] font-semibold tracking-tight" />
                  <p className="text-[13.5px] text-mute">Create a note, then record a meeting.</p>
                  <Button variant="primary" className="mt-3 h-10 px-6" icon={<Plus className="size-4" strokeWidth={2.6} />} onClick={newNote}>
                    Create your first note
                  </Button>
                </motion.div>
              )
            )}
          </AnimatePresence>
        </div>
      </main>

      <SettingsModal
        open={settingsOpen}
        settings={settings}
        onClose={() => setSettingsOpen(false)}
        onSave={async (s) => {
          const saved = await guard(bridge.saveSettings(s))
          if (saved) setSettings(saved)
        }}
      />

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} width="max-w-md">
        <div className="space-y-4 p-7">
          <h3 className="text-[18px] font-semibold">Delete this note?</h3>
          <p className="text-[13.5px] leading-relaxed text-mute">
            “{note?.title}” and its recordings will be permanently deleted. This cannot be undone.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" onClick={removeNote}>
              Delete
            </Button>
          </div>
        </div>
      </Modal>

      <ReviewModal open={reviewOpen} items={reviewItems} onClose={() => setReviewOpen(false)} onApply={applyFixes} />

      <Modal open={confirmRefine} onClose={() => setConfirmRefine(false)} width="max-w-md">
        <div className="space-y-4 p-7">
          <h3 className="text-[18px] font-semibold">Refine the transcript?</h3>
          <p className="text-[13.5px] leading-relaxed text-mute">
            The whole recording is transcribed again with full context, which is usually more accurate for Thai than the
            live version. It can take a few minutes, and it <span className="text-ink">replaces the current transcript</span>,
            including your edits.
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <Button onClick={() => setConfirmRefine(false)}>Cancel</Button>
            <Button variant="primary" onClick={refine}>
              Refine
            </Button>
          </div>
        </div>
      </Modal>

      <Toasts items={toasts} dismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  )
}
