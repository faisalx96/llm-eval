/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = 'http://localhost:8000'

/**
 * Every backend-owned path prefix. Anything else is served by Vite (the SPA).
 */
const BACKEND_PATHS = [
  '/api',
  '/v1',
  '/login',
  '/auth',
  '/static',
  '/ui',
  '/docs',
  '/healthz',
  '/openapi.json',
]

/**
 * Proxy entries that ALSO rewrite Origin/Referer to the backend origin.
 *
 * The FastAPI app has a same-origin write guard that validates the Origin and
 * Referer headers on mutating requests. `changeOrigin: true` only rewrites the
 * Host header, so we use the node-http-proxy `configure` hook to overwrite
 * Origin/Referer on the outgoing proxied request as well.
 */
function backendProxy(): Record<string, ProxyOptions> {
  const entries = BACKEND_PATHS.map((path): [string, ProxyOptions] => [
    path,
    {
      target: BACKEND,
      changeOrigin: true,
      configure(proxy) {
        proxy.on('proxyReq', (proxyReq, req) => {
          if (req.headers.origin) {
            proxyReq.setHeader('origin', BACKEND)
          }
          const referer = req.headers.referer
          if (referer) {
            try {
              const parsed = new URL(referer)
              proxyReq.setHeader('referer', `${BACKEND}${parsed.pathname}${parsed.search}`)
            } catch {
              proxyReq.setHeader('referer', `${BACKEND}/`)
            }
          }
        })
      },
    },
  ])
  return Object.fromEntries(entries)
}

export default defineConfig({
  // Empty base → vite treats built URLs as relative; renderBuiltUrl below
  // then decides per host how each URL is rendered. (With the default '/'
  // base, the html host would still prefix '/' even when the hook returns
  // { relative: true } — see toOutputFilePathWithoutRuntime + getBaseInHTML.)
  base: '',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../qym_platform/_static/app',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  experimental: {
    /**
     * The SPA is served behind an arbitrary FastAPI root_path which is only
     * known at runtime (injected as `window.__QYM_ROOT_PATH__`).
     *
     * Vite 5 signature:
     *   renderBuiltUrl(filename, { hostId, hostType, type, ssr })
     *     => string | { relative?: boolean; runtime?: string } | undefined
     *
     * - URLs referenced from JS (dynamic import chunks, assets imported in
     *   code) return the `{ runtime }` form: an expression evaluated in the
     *   browser, prefixing the root path + the backend's /app-assets/ mount.
     * - URLs referenced from HTML/CSS cannot run JS, so they stay relative
     *   to the host file ({ relative: true }); the backend rewrites/serves
     *   index.html so relative asset paths resolve under its app mount.
     */
    renderBuiltUrl(filename, { hostType }) {
      if (hostType === 'js') {
        return { runtime: `window.__QYM_ROOT_PATH__ + ${JSON.stringify(`/app-assets/${filename}`)}` }
      }
      return { relative: true }
    },
  },
  server: {
    port: 5173,
    proxy: backendProxy(),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Playwright specs live in e2e/ and must not run under vitest.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
