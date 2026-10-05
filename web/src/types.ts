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
}

export interface RecState {
  id: string | null
  started?: number
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
  anthropic_key: string
  openai_key: string
  claude_model: string
  default_prompt: string
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
}
