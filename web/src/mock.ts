// In-memory fake backend so the UI can be developed/tested in a normal browser.
import type { Note } from './types'

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
    { id: 'n3', title: 'Weekly standup', created: new Date(now - 36e5).toISOString(), duration: 754, parts: 2, transcript: LINES.join('\n') + '\n', summary: SUMMARY },
    { id: 'n2', title: 'Client call - Acme', created: new Date(now - 864e5).toISOString(), duration: 1980, parts: 1, transcript: 'สวัสดีครับ วันนี้เรามาคุยเรื่องโปรเจกต์ใหม่\n', summary: '' },
    { id: 'n1', title: 'Retro', created: new Date(now - 3 * 864e5).toISOString(), duration: 0, parts: 0, transcript: '', summary: '' },
  ]
  let rec: { id: string; t: number; timers: number[] } | null = null
  let settings: any = {
    engine: 'local', language: 'auto', whisper_model: 'small', use_system: true, use_mic: true,
    live_transcript: true, summary_backend: 'auto', summary_prompt: '', anthropic_key: '', openai_key: '',
    whisper_custom: '', vocabulary: '', claude_model: 'claude-sonnet-5-5', default_prompt: 'You are a meeting-minutes assistant...\n\n## Overview\n...',
  }
  const brief = (n: Note) => ({ id: n.id, title: n.title, created: n.created, duration: n.duration, parts: n.parts })
  const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data })
  const find = (id: string) => notes.find((n) => n.id === id)!

  return {
    list_notes: (q: string) => ok(notes.filter((n) => !q || (n.title + n.transcript + n.summary).toLowerCase().includes(q.toLowerCase())).map(brief)),
    get_note: (id: string) => ok({ ...find(id) }),
    create_note: () => {
      const n: Note = { id: 'n' + Date.now(), title: 'New meeting', created: new Date().toISOString(), duration: 0, parts: 0, transcript: '', summary: '' }
      notes.unshift(n)
      return ok({ ...n })
    },
    save_note: (id: string, title: string, transcript: string, summary: string) => {
      Object.assign(find(id), { title, transcript, summary })
      return ok(brief(find(id)))
    },
    delete_note: (id: string) => { notes.splice(notes.findIndex((n) => n.id === id), 1); return ok(true) },
    export_note: () => ok(null),
    start_recording: (id: string) => {
      const timers: number[] = []
      rec = { id, t: Date.now(), timers }
      timers.push(window.setInterval(() => emit('level', 0.02 + 0.09 * Math.abs(Math.sin(Date.now() / 260)) * Math.random()), 80))
      let i = 0
      timers.push(window.setInterval(() => {
        emit('text', { id, text: LINES[i % LINES.length] })
        const n = find(id); n.transcript += LINES[i % LINES.length] + '\n'; i++
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
      emit('busy', true); emit('status', 'Summarizing with Claude…')
      setTimeout(() => { find(id).summary = SUMMARY; emit('summary', { id, markdown: SUMMARY }); emit('busy', false); emit('status', 'Summary done.') }, 2600)
      return ok(true)
    },
    retranscribe: (id: string) => {
      emit('busy', true); emit('status', 'Refining transcript…')
      setTimeout(() => { const t = LINES.join('\n') + '\n'; find(id).transcript = t; emit('transcript', { id, text: t }); emit('busy', false); emit('status', 'Transcript refined.') }, 2200)
      return ok(true)
    },
    review: (id: string, transcript: string) => {
      emit('busy', true); emit('status', 'Checking transcript for garbled words…')
      setTimeout(() => {
        const items = [
          { original: 'Android 9', options: ['Android 9', 'Android 10'], reason: 'maybe a different version', before: 'Carol: Do we need to support ', after: '?' },
          { original: 'by Thursday', options: ['by this Thursday', 'before Thursday'], reason: 'ambiguous deadline', before: 'login still has a bug, I will fix it ', after: '.' },
          { original: 'two more testers', options: ['2 more testers', 'two more test engineers', 'two more testing teams'], reason: 'similar sounding', before: 'Budget is approved for ', after: '.' },
        ].filter((i) => transcript.includes(i.original))
        emit('review', { id, items }); emit('busy', false); emit('status', 'Found ' + items.length + ' phrase(s) to check.')
      }, 1800)
      return ok(true)
    },
    get_settings: () => ok({ ...settings }),
    save_settings: (s: any) => { settings = { ...settings, ...s }; return ok({ ...settings }) },
  }
}
