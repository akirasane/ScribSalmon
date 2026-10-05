import type { Note, NoteBrief, RecState, Settings } from './types'
import { createMock } from './mock'

type Res<T> = { ok: true; data: T } | { ok: false; error: string }
type Listener = (payload: any) => void

declare global {
  interface Window {
    pywebview?: { api: Record<string, (...a: any[]) => Promise<Res<any>>> }
    __pyEmit?: (name: string, payload: unknown) => void
  }
}

const listeners = new Map<string, Set<Listener>>()
export function emit(name: string, payload: unknown) {
  listeners.get(name)?.forEach((fn) => fn(payload))
}
window.__pyEmit = emit

export function on(name: string, fn: Listener): () => void {
  if (!listeners.has(name)) listeners.set(name, new Set())
  listeners.get(name)!.add(fn)
  return () => listeners.get(name)!.delete(fn)
}

type Api = Record<string, (...a: any[]) => Promise<Res<any>>>
let apiPromise: Promise<Api> | null = null

/** pywebview injects window.pywebview.api and fires 'pywebviewready'. In a plain browser
 *  (npm run dev preview) we fall back to an in-memory mock so the UI can be developed. */
function getApi(): Promise<Api> {
  if (apiPromise) return apiPromise
  apiPromise = new Promise<Api>((resolve) => {
    if (window.pywebview?.api) return resolve(window.pywebview.api)
    const timer = setTimeout(() => {
      console.info('[bridge] no pywebview detected, using mock backend')
      resolve(createMock(emit) as Api)
    }, 900)
    window.addEventListener('pywebviewready', () => {
      clearTimeout(timer)
      resolve(window.pywebview!.api)
    })
  })
  return apiPromise
}

async function call<T>(method: string, ...args: unknown[]): Promise<T> {
  const api = await getApi()
  const res = await api[method](...args)
  if (!res.ok) throw new Error(res.error)
  return res.data as T
}

export const bridge = {
  listNotes: (q = '') => call<NoteBrief[]>('list_notes', q),
  getNote: (id: string) => call<Note>('get_note', id),
  createNote: () => call<Note>('create_note'),
  saveNote: (id: string, title: string, transcript: string, summary: string) =>
    call<NoteBrief>('save_note', id, title, transcript, summary),
  deleteNote: (id: string) => call<boolean>('delete_note', id),
  exportNote: (id: string) => call<string | null>('export_note', id),
  startRecording: (id: string, opts: Record<string, unknown>) => call<RecState>('start_recording', id, opts),
  stopRecording: () => call<NoteBrief>('stop_recording'),
  addWav: (id: string) => call<NoteBrief | null>('add_wav', id),
  summarize: (id: string, transcript: string) => call<boolean>('summarize', id, transcript),
  retranscribe: (id: string) => call<boolean>('retranscribe', id),
  review: (id: string, transcript: string) => call<boolean>('review', id, transcript),
  getSettings: () => call<Settings>('get_settings'),
  saveSettings: (s: Partial<Settings>) => call<Settings>('save_settings', s),
}
