import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { FileAudio, Settings as Cog, Square } from 'lucide-react'
import type { Note, RecState, Settings } from '../types'
import { fmtDuration } from '../lib'
import SpotlightCard from './bits/SpotlightCard'
import { Button, Select, Toggle, Waveform } from './ui'

interface Props {
  note: Note
  rec: RecState
  settings: Settings | null
  onSettings: (patch: Partial<Settings>) => void
  onStart: () => void
  onStop: () => void
  onAddWav: () => void
  onOpenSettings: () => void
}

export default function ControlBar({ note, rec, settings, onSettings, onStart, onStop, onAddWav, onOpenSettings }: Props) {
  const recordingHere = rec.id === note.id
  const recordingElsewhere = rec.id !== null && !recordingHere
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    if (!recordingHere || !rec.started) return setElapsed(0)
    const tick = () => setElapsed(Date.now() / 1000 - rec.started!)
    tick()
    const id = setInterval(tick, 250)
    return () => clearInterval(id)
  }, [recordingHere, rec.started])

  return (
    <SpotlightCard className="shrink-0">
      <div className="flex flex-col gap-3 px-4 py-3.5">
        <div className="flex items-center gap-3">
          {/* record */}
          <motion.button
            whileHover={{ scale: recordingHere || recordingElsewhere ? 1 : 1.04 }}
            whileTap={{ scale: 0.95 }}
            disabled={recordingHere || recordingElsewhere}
            onClick={onStart}
            title={recordingElsewhere ? 'Another note is recording' : undefined}
            className={`inline-flex h-10 cursor-pointer items-center gap-2.5 rounded-full border px-5 text-[13px] font-semibold transition-colors
              disabled:cursor-default ${
                recordingHere
                  ? 'border-danger/60 bg-danger/12 text-ink'
                  : 'border-line bg-card-hi text-ink hover:border-danger/60 disabled:opacity-40'
              }`}
          >
            <span className={`size-2.5 rounded-full bg-danger ${recordingHere ? 'animate-pulse-ring' : ''}`} />
            {recordingHere ? 'Recording' : note.parts ? 'Record more' : 'Record'}
          </motion.button>

          <Button disabled={!recordingHere || !!rec.stopping} onClick={onStop} icon={<Square className="size-3.5 fill-current" />} className="h-10">
            Stop
          </Button>

          <span className={`w-14 font-mono text-[15px] tabular-nums transition-colors ${recordingHere ? 'text-danger' : 'text-mute'}`}>
            {fmtDuration(elapsed)}
          </span>

          <div className="min-w-0 flex-1">
            <Waveform active={recordingHere} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Toggle label="System audio" checked={settings?.use_system ?? true} onChange={(v) => onSettings({ use_system: v })} />
          <Toggle label="Microphone" checked={settings?.use_mic ?? true} onChange={(v) => onSettings({ use_mic: v })} />
          <div className="flex-1" />
          <Select
            className="w-40"
            value={settings?.engine ?? 'local'}
            onChange={(v) => onSettings({ engine: v })}
            options={[
              { value: 'local', label: 'Local Whisper' },
              { value: 'openai', label: 'OpenAI Whisper (cloud)' },
            ]}
          />
          <Select
            className="w-32"
            value={settings?.language ?? 'auto'}
            onChange={(v) => onSettings({ language: v })}
            options={[
              { value: 'auto', label: 'Auto-detect' },
              { value: 'th', label: 'Thai' },
              { value: 'en', label: 'English' },
            ]}
          />
          <Button onClick={onAddWav} icon={<FileAudio className="size-4" />}>
            Add WAV
          </Button>
          <Button onClick={onOpenSettings} aria-label="Settings" title="Settings" className="w-9 px-0!">
            <Cog className="size-4" />
          </Button>
        </div>
      </div>
    </SpotlightCard>
  )
}
