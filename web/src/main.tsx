import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { openExternal } from './external'

// Links never navigate the app window: http(s) opens in the system browser, everything else is ignored.
const onLink = (e: MouseEvent) => {
  const a = (e.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
  if (!a) return
  const raw = a.getAttribute('href') || ''
  if (raw.startsWith('#')) return
  e.preventDefault()
  openExternal(a.href)
}
document.addEventListener('click', onLink, true)
document.addEventListener('auxclick', onLink, true)
// dropping a file onto the window must not navigate to it
window.addEventListener('dragover', (e) => e.preventDefault())
window.addEventListener('drop', (e) => e.preventDefault())
// keep the native context menu where copy/paste is useful (text fields, selections); block it elsewhere
if (!import.meta.env.DEV)
  window.addEventListener('contextmenu', (e) => {
    const t = e.target as Element | null
    if (t?.closest?.('input, textarea, [contenteditable=""], [contenteditable="true"]')) return
    if (window.getSelection()?.toString()) return
    e.preventDefault()
  })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
