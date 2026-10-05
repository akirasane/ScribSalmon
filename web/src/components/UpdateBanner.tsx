import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpCircle, X } from 'lucide-react'
import { openExternal } from '../external'
import type { UpdateInfo, UpdatePhase } from '../types'
import { Button } from './ui'

interface Props {
  phase: UpdatePhase
  info: UpdateInfo | null
  pct: number
  error: string
  /** recording or a transcription/summary task is running: installing would interrupt it */
  blocked: boolean
  onUpdate: () => void
  onCancel: () => void
  onSkip: () => void
  onDismiss: () => void
  onInstall: () => void
}

const small = 'h-7 px-3 text-[12px]'

export default function UpdateBanner({ phase, info, pct, error, blocked, onUpdate, onCancel, onSkip, onDismiss, onInstall }: Props) {
  const releasePage = () => info && openExternal(info.notes_url)
  const canInstall = !!info && info.can_install && info.install_mode !== 'source'

  return (
    <AnimatePresence initial={false}>
      {phase !== 'idle' && info && (
        <motion.div
          key="update-banner"
          role="status"
          className="relative z-10 overflow-hidden border-b border-line bg-card/90 backdrop-blur"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 py-2 text-[13px]">
            <ArrowUpCircle className="size-4 shrink-0 text-accent" />

            {phase === 'available' && (
              <>
                <span className="text-ink">ScribSalmon {info.version} is available</span>
                <div className="flex-1" />
                {canInstall ? (
                  <>
                    <Button variant="primary" className={small} onClick={onUpdate}>Update</Button>
                    <Button className={small} onClick={releasePage}>What's new</Button>
                  </>
                ) : (
                  <Button variant="primary" className={small} onClick={releasePage}>Release page</Button>
                )}
                <Button className={small} onClick={onSkip}>Skip this version</Button>
                <button type="button" aria-label="Dismiss" title="Dismiss until next launch" onClick={onDismiss} className="cursor-pointer rounded-full p-1 text-mute hover:text-ink">
                  <X className="size-4" />
                </button>
              </>
            )}

            {phase === 'downloading' && (
              <>
                <span className="text-ink">Downloading… {pct}%</span>
                <div className="h-1.5 min-w-24 flex-1 overflow-hidden rounded-full bg-[#33241e]">
                  <div className="h-full bg-gradient-to-r from-accent to-accent2 transition-[width] duration-200" style={{ width: `${pct}%` }} />
                </div>
                <Button className={small} onClick={onCancel}>Cancel</Button>
              </>
            )}

            {phase === 'ready' && (
              <>
                <span className="text-ink">ScribSalmon {info.version} is ready to install</span>
                {blocked && <span className="text-mute">Finish recording/transcription first</span>}
                <div className="flex-1" />
                <Button variant="primary" className={small} disabled={blocked} onClick={onInstall}>Restart &amp; update</Button>
                <button type="button" aria-label="Dismiss" title="Dismiss until next launch" onClick={onDismiss} className="cursor-pointer rounded-full p-1 text-mute hover:text-ink">
                  <X className="size-4" />
                </button>
              </>
            )}

            {phase === 'installing' && <span className="text-ink">Installing… ScribSalmon will restart</span>}

            {phase === 'error' && (
              <>
                <span className="min-w-0 flex-1 truncate text-danger" title={error}>{error || 'Update failed.'}</span>
                {canInstall && <Button className={small} onClick={onUpdate}>Retry</Button>}
                <Button className={small} onClick={releasePage}>Release page</Button>
                <button type="button" aria-label="Dismiss" onClick={onDismiss} className="cursor-pointer rounded-full p-1 text-mute hover:text-ink">
                  <X className="size-4" />
                </button>
              </>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
