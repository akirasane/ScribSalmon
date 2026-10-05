import { useEffect, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import type { Settings, SettingsPatch, UpdateCheck } from '../types'
import { Button, Modal, Select, Toggle } from './ui'

interface Props {
  open: boolean
  settings: Settings | null
  onClose: () => void
  onSave: (s: SettingsPatch) => Promise<void>
  /** Forced update check; resolves with the result, rejects with a readable message */
  onCheckUpdates: () => Promise<UpdateCheck>
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

type KeyName = 'anthropic' | 'openai'

function keyPlaceholder(source: Settings['anthropic_key_source'], envVar: string, cleared: boolean) {
  if (cleared) return 'Will be removed on save'
  if (source === 'saved') return 'Saved – type to replace'
  if (source === 'unreadable') return 'Re-enter key'
  if (source === 'env') return `Using ${envVar} from environment`
  return 'Not set'
}

export default function SettingsModal({ open, settings, onClose, onSave, onCheckUpdates }: Props) {
  const [d, setD] = useState<Settings | null>(settings)
  const [saving, setSaving] = useState(false)
  const [clear, setClear] = useState<Record<KeyName, boolean>>({ anthropic: false, openai: false })

  const [checking, setChecking] = useState(false)
  const [checkMsg, setCheckMsg] = useState('')
  const [lastCheck, setLastCheck] = useState(0)

  useEffect(() => {
    if (open) {
      setCheckMsg('')
      setLastCheck(settings?.last_update_check ?? 0)
      setD(settings)
      setClear({ anthropic: false, openai: false })
    }
  }, [open, settings])

  if (!d) return <Modal open={false} onClose={onClose}>{null}</Modal>
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setD({ ...d, [k]: v })

  const checkNow = async () => {
    setChecking(true)
    setCheckMsg('')
    try {
      const r = await onCheckUpdates()
      setLastCheck(Date.now() / 1000)
      setCheckMsg(r.available && r.latest ? `v${r.latest} available` : 'Up to date')
    } catch (e) {
      setCheckMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }

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
          <Field label="Device">
            <Select
              value={d.device ?? 'auto'}
              onChange={(v) => set('device', v)}
              options={[
                { value: 'auto', label: 'Auto (GPU if it works, else CPU)' },
                { value: 'cpu', label: 'CPU' },
                { value: 'cuda', label: 'NVIDIA GPU (CUDA)' },
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
            <div className="flex items-center gap-2">
              <input
                type="password"
                autoComplete="off"
                className={input}
                value={d.anthropic_key}
                placeholder={keyPlaceholder(d.anthropic_key_source, 'ANTHROPIC_API_KEY', clear.anthropic)}
                onChange={(e) => {
                  set('anthropic_key', e.target.value)
                  if (e.target.value) setClear((c) => ({ ...c, anthropic: false }))
                }}
              />
              {d.anthropic_key_source === 'saved' && (
                <Button className="h-10 px-3" disabled={clear.anthropic} onClick={() => { set('anthropic_key', ''); setClear((c) => ({ ...c, anthropic: true })) }}>
                  Remove
                </Button>
              )}
            </div>
          </Field>
          {d.anthropic_key_source === 'unreadable' && (
            <p className="-mt-2 text-xs text-red-600">Saved key can't be decrypted on this Windows account, re-enter it.</p>
          )}
          <Field label="OpenAI API key">
            <div className="flex items-center gap-2">
              <input
                type="password"
                autoComplete="off"
                className={input}
                value={d.openai_key}
                placeholder={keyPlaceholder(d.openai_key_source, 'OPENAI_API_KEY', clear.openai)}
                onChange={(e) => {
                  set('openai_key', e.target.value)
                  if (e.target.value) setClear((c) => ({ ...c, openai: false }))
                }}
              />
              {d.openai_key_source === 'saved' && (
                <Button className="h-10 px-3" disabled={clear.openai} onClick={() => { set('openai_key', ''); setClear((c) => ({ ...c, openai: true })) }}>
                  Remove
                </Button>
              )}
            </div>
          </Field>
          {d.openai_key_source === 'unreadable' && (
            <p className="-mt-2 text-xs text-red-600">Saved key can't be decrypted on this Windows account, re-enter it.</p>
          )}
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

        <div className="space-y-2">
          <span className="text-[11px] font-semibold tracking-[0.12em] text-mute uppercase">Updates</span>
          <Toggle label="Check for updates on launch" checked={d.check_updates ?? true} onChange={(v) => set('check_updates', v)} />
          <div className="flex flex-wrap items-center gap-3">
            <Button className="h-8 px-3" disabled={checking} onClick={checkNow}>
              {checking ? 'Checking…' : 'Check now'}
            </Button>
            {checkMsg && <span className="text-[12.5px] text-ink">{checkMsg}</span>}
            <span className="text-[12px] text-mute">
              {lastCheck > 0 ? `Last checked ${new Date(lastCheck * 1000).toLocaleString()}` : 'Never checked'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <span className="text-[12px] text-mute">ScribSalmon v{settings?.version ?? 'dev'}</span>
          <div className="flex-1" />
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={saving}
            onClick={async () => {
              setSaving(true)
              try {
                const patch: Record<string, unknown> = {}
                for (const k of Object.keys(d) as (keyof Settings)[]) {
                  if (k === 'anthropic_key' || k === 'openai_key') continue
                  if (k === 'default_prompt' || k === 'version' || k === 'last_update_check' || k === 'skipped_version' || k === 'install_mode' || k.startsWith('has_') || k.endsWith('_source')) continue
                  if (d[k] !== settings?.[k]) patch[k] = d[k]
                }
                if (d.anthropic_key.trim()) patch.anthropic_key = d.anthropic_key.trim()
                else if (clear.anthropic) patch.clear_anthropic_key = true
                if (d.openai_key.trim()) patch.openai_key = d.openai_key.trim()
                else if (clear.openai) patch.clear_openai_key = true
                await onSave(patch as SettingsPatch)
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
