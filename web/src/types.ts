export interface NoteBrief {
  id: string
  title: string
  created: string
  duration: number
  parts: number
}

export interface Note extends NoteBrief {
  transcript: string
  summary: string
  transcript_rev: number
  summary_rev: number
}

export interface RecState {
  id: string | null
  started?: number
  /** UI-only: a stop request is in flight (set by App, read by ControlBar) */
  stopping?: boolean
}

export interface Settings {
  engine: 'local' | 'openai'
  language: 'auto' | 'th' | 'en'
  whisper_model: string
  whisper_custom: string
  vocabulary: string
  use_system: boolean
  use_mic: boolean
  live_transcript: boolean
  summary_backend: 'auto' | 'cli' | 'api'
  summary_prompt: string
  device: 'auto' | 'cpu' | 'cuda'
  /** Always blank from the backend; only set when the user types a new key. */
  anthropic_key: string
  openai_key: string
  has_anthropic_key: boolean
  has_openai_key: boolean
  anthropic_key_source: 'saved' | 'env' | 'unreadable' | ''
  openai_key_source: 'saved' | 'env' | 'unreadable' | ''
  claude_model: string
  default_prompt: string
  /** App version, read-only, from the backend */
  version?: string
}

export interface Toast {
  id: number
  kind: 'error' | 'info'
  text: string
}

export interface ReviewItem {
  original: string
  options: string[]
  reason: string
  before: string
  after: string
  /** position of `original` in the transcript when it was checked */
  index?: number
}

export type TaskKind = 'refine' | 'summary' | 'review'

export interface Backlog {
  pending: number
  seconds_behind: number
}

export type SettingsPatch = Partial<Settings> & { clear_anthropic_key?: boolean; clear_openai_key?: boolean }

export type NotePatch = Partial<Pick<Note, 'title' | 'transcript' | 'summary' | 'transcript_rev' | 'summary_rev'>>

export type SaveResult = NoteBrief & {
  transcript_rev: number
  summary_rev: number
  appended?: string[]
  conflict?: string[]
}
