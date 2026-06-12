import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

/**
 * Standalone export bundle: builds ONLY export.html (everything inlined into a
 * single self-contained HTML file via vite-plugin-singlefile) so the backend
 * can stamp data into it and hand it out as a downloadable report.
 *
 * Output: ../qym_platform/_static/app/export/export.html
 *
 * NOTE: run `npm run build:export` AFTER `npm run build` — the main build has
 * emptyOutDir enabled on _static/app and wipes this directory.
 */
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../qym_platform/_static/app/export',
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./export.html', import.meta.url)),
    },
  },
})
