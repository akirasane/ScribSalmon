import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Plus } from 'lucide-react'
import { bridge, on } from './bridge'
import { appendLine } from './lib'
import type { Backlog, Note, NoteBrief, NotePatch, RecState, ReviewItem, Settings, SettingsPatch, TaskKind, Toast, UpdateCheck, UpdateInfo, UpdatePhase, GpuStatus, GpuProgress, GpuFallback } from './types'
import Aurora from './components/bits/Aurora'
import BlurText from './components/bits/BlurText'
import Logo from './components/Logo'
import Sidebar from './components/Sidebar'
import NoteView from './components/NoteView'
import SettingsModal from './components/SettingsModal'
import ReviewModal from './components/ReviewModal'
import UpdateBanner from './components/UpdateBanner'
import type { GpuDownload } from './components/GpuPanel'
import { Button, Modal, Toasts } from './components/ui'

export default function App() {
  const [notes, setNotes] = useState<NoteBrief[]>([])
  const [query, setQuery] = useState('')
  const [selId, setSelId] = useState<string | null>(null)
  const [note, setNote] = useState<Note | null>(null)
  const [rec, setRec] = useState<RecState>({ id: null })
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Ready')
  const [tasks, setTasks] = useState<Record<string, TaskKind[]>>({})
  const [backlog, setBacklog] = useState<Record<string, Backlog>>({})
  const [settings, setSettings] = useState<Settings | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [ready, setReady] = useState(false)
  const [reviewItems, setReviewItems] = useState<ReviewItem[]>([])
  const [reviewOpen, setReviewOpen] = useState(false)
  const [confirmRefine, setConfirmRefine] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [updPhase, setUpdPhase] = useState<UpdatePhase>('idle')
  const [updInfo, setUpdInfo] = useState<UpdateInfo | null>(null)
  const [updPct, setUpdPct] = useState(0)
  const [updError, setUpdError] = useState('')

  const noteRef = useRef<Note | null>(null)
  noteRef.current = note
  const selRef = useRef<string | null>(null)
  selRef.current = selId
  const queryRef = useRef('')
  queryRef.current = query
  const dirtyFields = useRef(new Set<'title' | 'transcript' | 'summary'>())
  const timer = useRef<number | undefined>(undefined)
  const toastId = useRef(0)
  const [gpu, setGpu] = useState<GpuStatus | null>(null)
  const [gpuDl, setGpuDl] = useState<GpuDownload>({ active: false, progress: null, error: '' })

  const toast = useCallback((kind: Toast['kind'], text: string, action?: Toast['action']) => {
    const id = ++toastId.current
    setToasts((t) => [...t, { id, kind, text, action }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 12000 : kind === 'error' ? 8000 : 4000)
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

  const showUpdate = useCallback((info: UpdateInfo) => {
    setUpdInfo(info)
    // never knock a download/install that is already in progress back to "available"
    setUpdPhase((p) => (p === 'downloading' || p === 'ready' || p === 'installing' ? p : 'available'))
  }, [])

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
      // silent launch check: the backend throttles it and swallows network errors
      bridge
        .checkForUpdates(false)
        .then(() => bridge.getSettings())
        .then(setSettings)
        .catch(() => {})
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
      on('tasks', ({ id, tasks: kinds }: { id: string; tasks: TaskKind[] }) =>
        setTasks((t) => {
          const { [id]: _drop, ...rest } = t
          return kinds.length ? { ...rest, [id]: kinds } : rest
        }),
      ),
      on('backlog', ({ id, pending, seconds_behind }: { id: string } & Backlog) =>
        setBacklog((b) => {
          const { [id]: _drop, ...rest } = b
          return pending > 0 ? { ...rest, [id]: { pending, seconds_behind } } : rest
        }),
      ),
      on('summary', ({ id, markdown, rev }: { id: string; markdown: string | null; rev?: number }) => {
        if (markdown && id === selRef.current)
          setNote((n) => (n && n.id === id ? { ...n, summary: markdown, summary_rev: rev ?? n.summary_rev } : n))
      }),
      on('transcript', ({ id, text, rev }: { id: string; text: string; rev?: number }) => {
        if (id === selRef.current) setNote((n) => (n && n.id === id ? { ...n, transcript: text, transcript_rev: rev ?? n.transcript_rev } : n))
      }),
      on('review', ({ id, items }: { id: string; items: ReviewItem[] | null }) => {
        if (id !== selRef.current || !items) return
        if (items.length) {
          setReviewItems(items)
          setReviewOpen(true)
        } else toast('info', 'No unclear words found.')
      }),
      on('update_available', (u: Omit<UpdateInfo, 'can_install'>) =>
        showUpdate({ ...u, can_install: u.install_mode !== 'source' && u.size != null }),
      ),
      on('update_progress', ({ pct }: { pct: number }) => {
        setUpdPhase((p) => (p === 'available' || p === 'downloading' ? 'downloading' : p))
        setUpdPct(Math.max(0, Math.min(100, Math.round(pct))))
      }),
      on('update_ready', () => setUpdPhase('ready')),
      on('update_error', ({ message }: { message: string }) => {
        setUpdError(message)
        setUpdPhase('error')
      }),
      on('gpu_progress', (p: GpuProgress) => {
        setGpuDl({ active: true, progress: p, error: '' })
      }),
      on('gpu_ready', ({ status: st }: { status?: GpuStatus }) => {
        setGpuDl({ active: false, progress: null, error: '' })
        if (st) setGpu(st)
        else bridge.gpuStatus().then(setGpu).catch(() => {})
        toast('info', 'GPU libraries installed - used from the next transcription')
      }),
      on('gpu_error', ({ message }: { message: string }) => {
        setGpuDl({ active: false, progress: null, error: message })
        toast('error', message)
      }),
      on('gpu_fallback', ({ reason }: GpuFallback) => {
        toast('error', `GPU unavailable, using CPU: ${reason}`, {
          label: 'Open Settings → GPU',
          onClick: () => void openSettingsRef.current(),
        })
        bridge.gpuStatus().then(setGpu).catch(() => {})
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
    await guard(bridge.review(note.id, note.transcript))
  }

  // Apply fixes against the CURRENT transcript (it may have changed while the dialog was open):
  // locate before+original+after (must be unique), else `original` if it occurs exactly once, else skip.
  const applyFixes = (fixes: [string, string][]) => {
    const cur = noteRef.current
    if (!cur) return
    const t = cur.transcript
    const unique = (needle: string) => {
      const a = needle ? t.indexOf(needle) : -1
      return a >= 0 && t.indexOf(needle, a + 1) < 0 ? a : -1
    }
    const used = new Set<number>()
    const spans: { start: number; len: number; to: string }[] = []
    let skipped = 0
    for (const [from, to] of fixes) {
      const k = reviewItems.findIndex((it, i) => !used.has(i) && it.original === from)
      if (k >= 0) used.add(k)
      const it = k >= 0 ? reviewItems[k] : undefined
      let at = -1
      if (it) {
        const ctx = unique(it.before + it.original + it.after)
        if (ctx >= 0) at = ctx + it.before.length
      }
      if (at < 0) at = unique(from)
      if (at < 0) skipped++
      else spans.push({ start: at, len: from.length, to })
    }
    spans.sort((a, b) => b.start - a.start) // right to left keeps earlier offsets valid
    let out = t
    let fixed = 0
    let edge = Infinity
    for (const s of spans) {
      if (s.start + s.len > edge) {
        skipped++ // overlaps a span we already replaced
        continue
      }
      out = out.slice(0, s.start) + s.to + out.slice(s.start + s.len)
      edge = s.start
      fixed++
    }
    if (fixed) edit({ transcript: out })
    setReviewOpen(false)
    toast(skipped ? 'error' : 'info', `${fixed} fixed, ${skipped} skipped${skipped ? ' (text changed)' : ''}`)
  }

  const refine = async () => {
    if (!note) return
    setConfirmRefine(false)
    await flush()
    await guard(bridge.retranscribe(note.id))
  }

  const startUpdate = async () => {
    setUpdError('')
    setUpdPct(0)
    setUpdPhase('downloading')
    if (!(await guard(bridge.downloadUpdate()))) setUpdPhase('available')
  }

  const cancelUpdate = async () => {
    await guard(bridge.cancelUpdate())
    setUpdPhase('available')
  }

  const skipUpdate = async () => {
    if (!updInfo) return
    if ((await guard(bridge.skipUpdate(updInfo.version))) !== undefined) setUpdPhase('idle')
  }

  const installUpdate = async () => {
    setUpdPhase('installing')
    await flush()
    // on success the backend closes the window a moment later
    if (!(await guard(bridge.installUpdate()))) setUpdPhase('ready')
  }

  // Settings > Check now: a manual check ignores the 24 h throttle and a skipped version
  const checkUpdatesNow = async (): Promise<UpdateCheck> => {
    const r = await bridge.checkForUpdates(true)
    if (r.available && r.latest) {
      showUpdate({ version: r.latest, notes_url: r.notes_url ?? '', size: r.size, install_mode: r.install_mode, can_install: r.can_install })
    }
    return r
  }

  const openSettings = async () => {
    if (!settings) {
      const s = await guard(bridge.getSettings())
      if (!s) return
      setSettings(s)
    }
    setSettingsOpen(true)
  }
  const openSettingsRef = useRef(openSettings)
  openSettingsRef.current = openSettings

  // fresh GPU status every time Settings opens
  useEffect(() => {
    if (settingsOpen) bridge.gpuStatus().then(setGpu).catch(() => {})
  }, [settingsOpen])

  const startGpuDownload = async () => {
    setGpuDl({ active: true, progress: { pct: 0, received: 0, total: 0, phase: 'download' }, error: '' })
    if (!(await guard(bridge.downloadGpuLibs()))) setGpuDl((d) => (d.error ? d : { active: false, progress: null, error: '' }))
  }

  const cancelGpuDownload = async () => {
    await guard(bridge.cancelGpuDownload())
    setGpuDl({ active: false, progress: null, error: '' })
  }

  const restartApp = async () => {
    await flush()
    await guard(bridge.restartApp())
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
    await guard(bridge.summarize(note.id, note.transcript))
  }

  const cancelTask = (kind: TaskKind) => {
    if (note) void guard(bridge.cancel(kind, note.id))
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

      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* React Bits Aurora, very faint, fades out downward */}
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-80 opacity-[0.28]"
          style={{ maskImage: 'linear-gradient(to bottom, black, transparent)', WebkitMaskImage: 'linear-gradient(to bottom, black, transparent)' }}
        >
          <Aurora />
        </div>

        <UpdateBanner
          phase={updPhase}
          info={updInfo}
          pct={updPct}
          error={updError}
          blocked={rec.id !== null || busy}
          onUpdate={startUpdate}
          onCancel={cancelUpdate}
          onSkip={skipUpdate}
          onDismiss={() => setUpdPhase('idle')}
          onInstall={installUpdate}
        />

        <div className="relative min-h-0 flex-1 px-8 pt-7 pb-4">
          <AnimatePresence mode="wait" initial={false}>
            {note ? (
              <NoteView
                key={note.id}
                note={note}
                rec={stopping ? { ...rec, stopping } : rec}
                settings={settings}
                tasks={tasks[note.id] ?? []}
                backlog={backlog[note.id]}
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
                onCancel={cancelTask}
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
        onCheckUpdates={checkUpdatesNow}
        gpu={{
          status: gpu,
          download: gpuDl,
          onDownload: startGpuDownload,
          onCancel: cancelGpuDownload,
          onRestart: restartApp,
          onOpenLogFolder: async () => {
            await guard(bridge.openLogFolder())
          },
          onCopyDiagnostics: async () => {
            const ok = await guard(bridge.copyDiagnostics())
            if (ok !== undefined) toast(ok ? 'info' : 'error', ok ? 'Diagnostics copied to the clipboard' : 'Could not copy diagnostics to the clipboard')
          },
        }}
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
