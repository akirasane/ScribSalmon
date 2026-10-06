import { useState } from 'react'
import { ClipboardCopy, Download, FolderOpen, RotateCw } from 'lucide-react'
import { openExternal } from '../external'
import type { GpuPhase, GpuProgress, GpuState, GpuStatus } from '../types'
import { Button } from './ui'

/** Download state owned by App so a download keeps going with Settings closed. */
export interface GpuDownload {
  active: boolean
  progress: GpuProgress | null
  error: string
}

interface Props {
  status: GpuStatus | null
  download: GpuDownload
  onDownload: () => void
  onCancel: () => void
  onRestart: () => void
  /** App shows a toast with the result */
  onOpenLogFolder: () => Promise<void>
  onCopyDiagnostics: () => Promise<void>
}

const DOWNLOAD_MB = 553
const DISK_MB = 735
const EULA_URL = 'https://docs.nvidia.com/cuda/eula/index.html'
const FOLDER = '%LOCALAPPDATA%\\ScribSalmon\\gpu-libs'

const DOT: Record<GpuState, string> = {
  active: 'bg-green-500',
  ready: 'bg-green-500',
  libs_missing: 'bg-amber-400',
  driver_old: 'bg-amber-400',
  failed: 'bg-danger',
  no_gpu: 'bg-mute',
}

const PHASE: Record<GpuPhase, string> = {
  download: 'Downloading',
  verify: 'Verifying',
  extract: 'Installing',
}

const mb = (n: number) => `${(n / 1048576).toFixed(n >= 1048576 * 100 ? 0 : 1)} MB`

function details(s: GpuStatus): string {
  const parts: string[] = []
  if (s.gpu_name) parts.push(s.gpu_name)
  if (s.driver) parts.push(`driver ${s.driver}`)
  if (s.driver_cuda) parts.push(`CUDA ${s.driver_cuda}`)
  if (s.vram_mb) parts.push(`${(s.vram_mb / 1024).toFixed(s.vram_mb % 1024 ? 1 : 0)} GB VRAM`)
  if (s.gpu_present) {
    parts.push(
      s.libs_installed_version
        ? `cuBLAS ${s.libs_installed_version} (downloaded)`
        : s.missing_dlls.length
          ? `missing ${s.missing_dlls.join(', ')}`
          : 'cuBLAS found',
    )
  }
  return parts.join(' · ')
}

export default function GpuPanel({ status, download, onDownload, onCancel, onRestart, onOpenLogFolder, onCopyDiagnostics }: Props) {
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
    }
  }

  const s = status
  const canDownload = !!s && s.gpu_present && s.state !== 'driver_old' && s.state !== 'ready' && s.state !== 'active'
  // After a fresh install the CUDA load can still fail inside this process: offer a restart then.
  const canRestart = !!s && s.state === 'failed' && !!s.libs_installed_version
  const p = download.progress

  return (
    <div className="rounded-2xl border border-line bg-card/60 p-4" aria-label="GPU status">
      <div className="flex items-start gap-2.5">
        <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${s ? DOT[s.state] : 'bg-mute'}`} />
        <div className="min-w-0 flex-1">
          <p className="selectable text-[13px] leading-snug">{s ? s.message : 'Checking GPU…'}</p>
          {s?.hint && <p className="selectable mt-1 text-[12px] leading-snug text-mute">{s.hint}</p>}
          {s && details(s) && <p className="selectable mt-1.5 text-[12px] leading-snug break-words text-mute">{details(s)}</p>}
        </div>
      </div>

      {download.active && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[12px] text-mute">
            <span>
              {PHASE[p?.phase ?? 'download']}
              {p && p.phase === 'download' && p.total > 0 ? ` ${mb(p.received)} / ${mb(p.total)}` : ''}
            </span>
            <span>{Math.round(p?.pct ?? 0)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p?.pct ?? 0)}>
            <div className="h-full rounded-full bg-gradient-to-r from-accent to-accent2 transition-[width] duration-200" style={{ width: `${Math.max(2, Math.min(100, p?.pct ?? 0))}%` }} />
          </div>
          <div className="mt-2">
            <Button className="h-8 px-3" onClick={onCancel}>
              Cancel download
            </Button>
          </div>
        </div>
      )}

      {!download.active && download.error && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="selectable min-w-0 flex-1 text-[12.5px] text-danger">{download.error}</span>
          <Button className="h-8 px-3" icon={<RotateCw className="size-3.5" />} onClick={onDownload}>
            Retry
          </Button>
        </div>
      )}

      {!download.active && !confirm && canDownload && !download.error && (
        <div className="mt-3">
          <Button className="h-8 px-3" icon={<Download className="size-3.5" />} onClick={() => setConfirm(true)}>
            Download GPU libraries ({DOWNLOAD_MB} MB)
          </Button>
        </div>
      )}

      {!download.active && confirm && (
        <div className="mt-3 rounded-xl border border-accent/40 bg-card p-3.5 text-[12.5px] leading-relaxed">
          <p className="font-medium">Download NVIDIA cuBLAS 12 libraries?</p>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-mute">
            <li>
              Download size: {DOWNLOAD_MB} MB, about {DISK_MB} MB on disk once installed.
            </li>
            <li>
              Saved to <span className="selectable">{FOLDER}</span>
            </li>
            <li>Source: PyPI, published by NVIDIA (checked against a pinned SHA-256).</li>
            <li>
              Licensed by NVIDIA under the{' '}
              <button type="button" className="cursor-pointer text-accent underline underline-offset-2" onClick={() => openExternal(EULA_URL)}>
                CUDA EULA
              </button>
              .
            </li>
          </ul>
          <div className="mt-3 flex gap-2">
            <Button
              variant="primary"
              className="h-8 px-4"
              onClick={() => {
                setConfirm(false)
                onDownload()
              }}
            >
              Download
            </Button>
            <Button className="h-8 px-3" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {canRestart && (
          <Button variant="primary" className="h-8 px-3" icon={<RotateCw className="size-3.5" />} onClick={onRestart}>
            Restart ScribSalmon
          </Button>
        )}
        <Button className="h-8 px-3" icon={<FolderOpen className="size-3.5" />} disabled={busy} onClick={() => run(onOpenLogFolder)}>
          Open log folder
        </Button>
        <Button className="h-8 px-3" icon={<ClipboardCopy className="size-3.5" />} disabled={busy} onClick={() => run(onCopyDiagnostics)}>
          Copy diagnostics
        </Button>
      </div>
    </div>
  )
}
