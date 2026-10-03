import { resolve } from 'path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Companion (Phase 1) web build: same renderer, but the CSP must let the
 * transport shim reach any LAN desktop (`ws://192.168.x.x:18973`) instead of
 * index.html's Electron-only loopback rule. The flag guarding the widening
 * is which config you build with: electron-vite for desktop, this for web.
 *
 * Port note (why `:*` everywhere): a CSP source with an omitted port only
 * matches the scheme's default port in Chromium — `ws://*` matches nothing
 * a companion actually uses, so every LAN connect (and every device build
 * shipping this HTML) was blocked at the browser's CSP layer. Explicit
 * `ws://*:*`/`http://*:*` is the "any port" form that works.
 */
function webCsp(): Plugin {
  return {
    name: 'syncflow-web-csp',
    transformIndexHtml(html) {
      return html.replace(
        'connect-src ws://127.0.0.1:*',
        'connect-src ws://*:* wss://*:* http://*:* https://*:*'
      )
    },
  }
}

export default defineConfig({
  root: '.',
  plugins: [react(), webCsp()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist-web',
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, 'index.html'),
    },
  },
})
