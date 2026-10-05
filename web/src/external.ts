// Open http(s) links in the system browser via the Python backend; never navigate the app window.
export function openExternal(href: string) {
  let u: URL
  try { u = new URL(href, location.href) } catch { return }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return
  const api = (window as any).pywebview?.api
  if (api?.open_external) void api.open_external(u.href)
  else window.open(u.href, '_blank', 'noopener,noreferrer')
}
