export function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const mm = String(m).padStart(2, '0')
  const rr = String(r).padStart(2, '0')
  return h ? `${h}:${mm}:${rr}` : `${mm}:${rr}`
}

export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** Mirrors Session.append() in Python: keep one chunk per line, file ends with a newline. */
export function appendLine(text: string, line: string): string {
  const base = text && !text.endsWith('\n') ? text + '\n' : text
  return base + line + '\n'
}
