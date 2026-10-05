// In-memory fake backend so the UI can be developed/tested in a normal browser.
import type { Note, NotePatch } from './types'

const SUMMARY = `## Overview
The team planned the mobile app launch for the end of November and reviewed backend status and testing budget.

## Key Points
1. **Launch timeline**
   1. Alice: the mobile app must launch by end of November.
2. **Backend status**
   1. Bob: the API is ready, but login has a bug.
   2. Bob will fix the login bug by Thursday.
3. **Testing resources**
   1. Budget approved for 2 more testers.

## Decisions
1. Launch target: end of November.
2. Budget approved for 2 more testers.

## Action Items
1. Fix the login bug - Bob - Thursday
2. Onboard 2 more testers - owner not specified

## Open Questions
1. Do we support Android 9?`

const LINES = [
  'Alice: We should ship the app by the end of November.',
  'Bob: The backend is ready but the login still has a bug, I will fix it by Thursday.',
  'Alice: Budget is approved for two more testers.',
  'Carol: Do we need to support Android 9?',
]

export function createMock(emit: (n: string, p: unknown) => void) {
  const now = Date.now()
  const notes: Note[] = [
    { id: 'n3', title: 'Weekly standup', created: new Date(now - 36e5).toISOString(), duration: 754, parts: 2, transcript: LINES.join('\n') + '\n', summary: SUMMARY, transcript_rev: 0, summary_rev: 0 },
    { id: 'n2', title: 'Client call - Acme', created: new Date(now - 864e5).toISOString(), duration: 1980, parts: 1, transcript: 'สวัสดีครับ วันนี้เรามาคุยเรื่องโปรเจกต์ใหม่\n', summary: '', transcript_rev: 0, summary_rev: 0 },
    { id: 'n1', title: 'Retro', created: new Date(now - 3 * 864e5).toISOString(), duration: 0, parts: 0, transcript: '', summary: '', transcript_rev: 0, summary_rev: 0 },
  ]
  let rec: { id: string; t: number; timers: number[] } | null = null
  let settings: any = {
    engine: 'local', language: 'auto', whisper_model: 'small', use_system: true, use_mic: true,
    live_transcript: true, summary_backend: 'auto', summary_prompt: '', device: 'auto', anthropic_key: '', openai_key: '',
    has_anthropic_key: false, has_openai_key: false, anthropic_key_source: '', openai_key_source: '',
    whisper_custom: '', vocabulary: '', claude_model: 'claude-sonnet-5-5', version: 'dev', check_updates: true, last_update_check: 0, skipped_version: '', install_mode: 'installed', default_prompt: 'You are a meeting-minutes assistant...\n\n## Overview\n...',
  }
  // `?update` in the URL pretends 9.9.9 is available, to develop the banner
  const fakeUpdate = new URLSearchParams(location.search).has('update')
  let dl: number | null = null
  const stopDl = () => { if (dl !== null) clearInterval(dl); dl = null }
  const brief = (n: Note) => ({ id: n.id, title: n.title, created: n.created, duration: n.duration, parts: n.parts })
  const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data })
  const find = (id: string) => notes.find((n) => n.id === id)!
  // fake long-running tasks: finish after `ms`, or run `onCancel` when cancelled
  const running = new Map<string, () => void>()
  const start = (kind: string, id: string, ms: number, done: () => void, onCancel?: () => void) => {
    const key = kind + ':' + id
    const finish = () => { running.delete(key); emit('tasks', { id, tasks: [] }); emit('busy', false) }
    const t = window.setTimeout(() => { done(); finish() }, ms)
    running.set(key, () => { clearTimeout(t); onCancel?.(); emit('status', 'Cancelled'); finish() })
  }

  return {
    list_notes: (q: string) => ok(notes.filter((n) => !q || (n.title + n.transcript + n.summary).toLowerCase().includes(q.toLowerCase())).map(brief)),
    get_note: (id: string) => ok({ ...find(id) }),
    create_note: () => {
      const n: Note = { id: 'n' + Date.now(), title: 'New meeting', created: new Date().toISOString(), duration: 0, parts: 0, transcript: '', summary: '', transcript_rev: 0, summary_rev: 0 }
      notes.unshift(n)
      return ok({ ...n })
    },
    save_note: (id: string, patch: NotePatch) => {
      const n = find(id)
      const { title, transcript, summary } = patch
      Object.assign(n, { ...(title !== undefined && { title }), ...(transcript !== undefined && { transcript }), ...(summary !== undefined && { summary }) })
      return ok({ ...brief(n), transcript_rev: n.transcript_rev, summary_rev: n.summary_rev })
    },
    open_external: (url: string) => { window.open(url, '_blank', 'noopener,noreferrer'); return ok(true) },
    delete_note: (id: string) => { notes.splice(notes.findIndex((n) => n.id === id), 1); return ok(true) },
    export_note: () => ok(null),
    start_recording: (id: string) => {
      const timers: number[] = []
      rec = { id, t: Date.now(), timers }
      timers.push(window.setInterval(() => emit('level', 0.02 + 0.09 * Math.abs(Math.sin(Date.now() / 260)) * Math.random()), 80))
      let i = 0
      timers.push(window.setInterval(() => {
        const n = find(id); n.transcript += LINES[i % LINES.length] + '\n'; n.transcript_rev++
        emit('text', { id, text: LINES[i % LINES.length], rev: n.transcript_rev }); i++
      }, 3500))
      emit('recording', { id, started: rec.t / 1000 })
      emit('status', 'Recording…')
      return ok({ id, started: rec.t / 1000 })
    },
    stop_recording: () => {
      if (!rec) return ok({})
      rec.timers.forEach(clearInterval)
      const n = find(rec.id); n.parts += 1; n.duration += (Date.now() - rec.t) / 1000
      rec = null
      emit('recording', { id: null }); emit('status', 'Recording saved.'); emit('notes', null)
      return ok(brief(n))
    },
    add_wav: () => ok(null),
    summarize: (id: string) => {
      emit('busy', true); emit('tasks', { id, tasks: ['summary'] }); emit('status', 'Summarizing with Claude…')
      start('summary', id, 2600, () => { const n = find(id); n.summary = SUMMARY; n.summary_rev++; emit('summary', { id, markdown: SUMMARY, rev: n.summary_rev }); emit('status', 'Summary done.') },
        () => emit('summary', { id, markdown: null }))
      return ok(true)
    },
    retranscribe: (id: string) => {
      emit('busy', true); emit('tasks', { id, tasks: ['refine'] }); emit('status', 'Refining transcript…')
      start('refine', id, 2200, () => { const t = LINES.join('\n') + '\n'; const n = find(id); n.transcript = t; n.transcript_rev++; emit('transcript', { id, text: t, rev: n.transcript_rev }); emit('status', 'Transcript refined.') })
      return ok(true)
    },
    cancel: (kind: string, id: string) => {
      const t = running.get(kind + ':' + id)
      if (!t) return ok(false)
      t()
      return ok(true)
    },
    review: (id: string, transcript: string) => {
      emit('busy', true); emit('tasks', { id, tasks: ['review'] }); emit('status', 'Checking transcript for garbled words…')
      start('review', id, 1800, () => {
        const items = [
          { original: 'Android 9', options: ['Android 9', 'Android 10'], reason: 'maybe a different version', before: 'Carol: Do we need to support ', after: '?' },
          { original: 'by Thursday', options: ['by this Thursday', 'before Thursday'], reason: 'ambiguous deadline', before: 'login still has a bug, I will fix it ', after: '.' },
          { original: 'two more testers', options: ['2 more testers', 'two more test engineers', 'two more testing teams'], reason: 'similar sounding', before: 'Budget is approved for ', after: '.' },
        ].filter((i) => transcript.includes(i.original))
        emit('review', { id, items }); emit('status', 'Found ' + items.length + ' phrase(s) to check.')
      }, () => emit('review', { id, items: null }))
      return ok(true)
    },
    check_for_updates: (force: boolean) => {
      settings.last_update_check = Date.now() / 1000
      const info = { version: '9.9.9', notes_url: 'https://github.com/akirasane/ScribSalmon/releases/tag/v9.9.9', size: 180 << 20, install_mode: settings.install_mode, can_install: true }
      if (fakeUpdate) emit('update_available', info)
      return ok({
        current: 'dev', latest: fakeUpdate ? info.version : null, available: fakeUpdate,
        notes_url: fakeUpdate ? info.notes_url : null, size: fakeUpdate ? info.size : null,
        install_mode: settings.install_mode, skipped: false, can_install: true, force,
      })
    },
    download_update: () => {
      stopDl()
      let pct = 0
      const total = 180 << 20
      dl = window.setInterval(() => {
        pct = Math.min(100, pct + 5)
        emit('update_progress', { pct, received: Math.round((total * pct) / 100), total })
        if (pct >= 100) { stopDl(); emit('update_ready', { version: '9.9.9' }) }
      }, 300)
      return ok(true)
    },
    cancel_update: () => { const was = dl !== null; stopDl(); return ok(was) },
    skip_update: (v: string) => { settings.skipped_version = v; return ok(true) },
    install_update: () => ok(true),
    get_settings: () => ok({ ...settings }),
    save_settings: (s: any) => { settings = { ...settings, ...s }; return ok({ ...settings }) },
  }
}
