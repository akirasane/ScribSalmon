import { useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import type { Settings } from '../types'
import { Button, Modal, Select, Toggle } from './ui'

interface Props {
  open: boolean
  settings: Settings | null
  onClose: () => void
  onSave: (s: Partial<Settings>) => Promise<void>
}

const input =
  'h-10 w-full rounded-xl border border-line bg-card px-3 text-[13px] outline-none transition-colors hover:border-[#3d2c25] focus:border-accent'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid grid-cols-[170px_1fr] items-center gap-3">
      <span className="text-[13px] text-mute">{label}</span>
      {children}
    </label>
  )
}

export default function SettingsModal({ open, settings, onClose, onSave }: Props) {
  const [d, setD] = useState<Settings | null>(settings)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) setD(settings)
  }, [open, settings])

  if (!d) return <Modal open={false} onClose={onClose}>{null}</Modal>
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setD({ ...d, [k]: v })

  return (
    <Modal open={open} onClose={onClose} width="max-w-2xl">
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-7">
        <h2 className="text-[20px] font-semibold tracking-tight">Settings</h2>

        <div>
          <Toggle label="Live transcript while recording" checked={d.live_transcript} onChange={(v) => set('live_transcript', v)} />
          <p className="mt-1.5 ml-[48px] text-[12px] text-mute">Off = record only (light on CPU), then transcribe after Stop.</p>
        </div>

        <div className="space-y-3">
          <Field label="Local Whisper model">
            <Select
              value={d.whisper_model}
              onChange={(v) => set('whisper_model', v)}
              options={[
                { value: 'tiny', label: 'tiny (fastest, rough)' },
                { value: 'base', label: 'base' },
                { value: 'small', label: 'small' },
                { value: 'medium', label: 'medium' },
                { value: 'large-v3-turbo', label: 'large-v3-turbo (good, fast)' },
                { value: 'large-v3', label: 'large-v3 (most accurate, slow on CPU)' },
                { value: 'Thaweewat/whisper-th-medium-ct2', label: 'Thai fine-tuned medium (best for Thai, ~1.5 GB)' },
              ]}
            />
          </Field>
          <Field label="Custom model (optional)">
            <input
              className={input}
              value={d.whisper_custom}
              placeholder="Hugging Face repo id or folder (overrides the model above)"
              onChange={(e) => set('whisper_custom', e.target.value)}
            />
          </Field>
          <Field label="Names & terms">
            <textarea
              rows={3}
              className="selectable w-full resize-y rounded-xl border border-line bg-card px-3 py-2 text-[13px] leading-relaxed outline-none transition-colors hover:border-[#3d2c25] focus:border-accent"
              value={d.vocabulary}
              placeholder="People, products, jargon spelled the way you want, e.g. สมชาย, Kubernetes, PromptPay"
              onChange={(e) => set('vocabulary', e.target.value)}
            />
          </Field>
          <Field label="Summary backend">
            <Select
              value={d.summary_backend}
              onChange={(v) => set('summary_backend', v)}
              options={[
                { value: 'auto', label: 'Auto (Claude Code CLI if installed, else API key)' },
                { value: 'cli', label: 'Claude Code CLI (your Claude Code login)' },
                { value: 'api', label: 'Anthropic API key' },
              ]}
            />
          </Field>
          <Field label="Anthropic API key">
            <input type="password" className={input} value={d.anthropic_key} onChange={(e) => set('anthropic_key', e.target.value)} />
          </Field>
          <Field label="OpenAI API key">
            <input type="password" className={input} value={d.openai_key} onChange={(e) => set('openai_key', e.target.value)} />
          </Field>
          <Field label="Claude model (API)">
            <input className={input} value={d.claude_model} onChange={(e) => set('claude_model', e.target.value)} />
          </Field>
        </div>

        <div>
          <div className="mb-1 flex items-center">
            <span className="text-[11px] font-semibold tracking-[0.12em] text-mute uppercase">Summary prompt</span>
            <div className="flex-1" />
            <Button className="h-8 px-3" icon={<RotateCcw className="size-3.5" />} onClick={() => set('summary_prompt', d.default_prompt)}>
              Reset to default
            </Button>
          </div>
          <p className="mb-2 text-[12px] text-mute">Use {'{transcript}'} to place the text; otherwise it is appended at the end.</p>
          <textarea
            value={d.summary_prompt || d.default_prompt}
            onChange={(e) => set('summary_prompt', e.target.value)}
            rows={10}
            className="selectable w-full resize-y rounded-2xl border border-line bg-card p-4 font-mono text-[12.5px] leading-relaxed outline-none transition-colors focus:border-accent"
          />
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={saving}
            onClick={async () => {
              setSaving(true)
              try {
                await onSave(d)
                onClose()
              } finally {
                setSaving(false)
              }
            }}
          >
            Save
          </Button>
        </div>
      </div>
    </Modal>
  )
}
