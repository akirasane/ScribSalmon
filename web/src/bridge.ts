import type { Note, NoteBrief, NotePatch, RecState, SaveResult, Settings, SettingsPatch } from './types'

type Res<T> = { ok: true; data: T } | { ok: false; error: string }
type Listener = (payload: any) => void

declare global {
  interface Window {
    pywebview?: { api: Record<string, (...a: any[]) => Promise<Res<any>>> }
    __pyEmit?: (name: string, payload: unknown) => void
    __flushNow?: () => Promise<void>
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

/** pywebview injects window.pywebview.api and fires 'pywebviewready'. The in-memory mock is only
 *  used by the Vite dev server (`?mock`, or a plain browser); the real app never falls back to it. */
function getApi(): Promise<Api> {
  if (apiPromise) return apiPromise
  apiPromise = new Promise<Api>((resolve) => {
    if (window.pywebview?.api) return resolve(window.pywebview.api)
    // import.meta.env.DEV is a build-time constant, so production bundles drop the mock entirely
    const useMock =
      import.meta.env.DEV && (new URLSearchParams(location.search).has('mock') || !(window as any).chrome?.webview)
    if (useMock) {
      setTimeout(async () => {
        if (window.pywebview?.api) return resolve(window.pywebview.api)
        console.info('[bridge] no pywebview detected, using mock backend')
        resolve((await import('./mock')).createMock(emit) as Api)
      }, 900)
    } else {
      setTimeout(() => {
        emit('error', 'Cannot reach the ScribSalmon backend. Restart the app.')
        emit('bridge', 'timeout')
      }, 10000)
    }
    window.addEventListener('pywebviewready', () => resolve(window.pywebview!.api))
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
  saveNote: (id: string, patch: NotePatch) => call<SaveResult>('save_note', id, patch),
  deleteNote: (id: string) => call<boolean>('delete_note', id),
  exportNote: (id: string) => call<string | null>('export_note', id),
  startRecording: (id: string, opts: Record<string, unknown>) => call<RecState>('start_recording', id, opts),
  stopRecording: () => call<NoteBrief>('stop_recording'),
  addWav: (id: string) => call<NoteBrief | null>('add_wav', id),
  summarize: (id: string, transcript: string) => call<boolean>('summarize', id, transcript),
  retranscribe: (id: string) => call<boolean>('retranscribe', id),
  review: (id: string, transcript: string) => call<boolean>('review', id, transcript),
  getSettings: () => call<Settings>('get_settings'),
  saveSettings: (s: SettingsPatch) => call<Settings>('save_settings', s),
  openExternal: (url: string) => call<boolean>('open_external', url),
}
