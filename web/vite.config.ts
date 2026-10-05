import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Injects the Content-Security-Policy <meta> (see comment in index.html). The page gets the
// pywebview JS API, so only our own bundle may run: no remote/inline scripts, no frames, no forms.
function csp(): Plugin {
  return {
    name: 'scribsalmon-csp',
    transformIndexHtml(_html, ctx) {
      const dev = !!ctx.server
      const policy = [
        "default-src 'self'",
        dev ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'" : "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        dev ? "connect-src 'self' ws://127.0.0.1:5173 ws://localhost:5173" : "connect-src 'self'",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-src 'none'",
      ].join('; ')
      return [{ tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: policy }, injectTo: 'head-prepend' }]
    },
  }
}

// base './' so the built index.html works when pywebview serves it from disk
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), csp()],
  server: { port: 5173, strictPort: true },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1500 },
})
