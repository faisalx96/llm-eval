import { defineConfig } from '@playwright/test'

/**
 * E2E tests run against the real FastAPI server (uvicorn on :8000), which
 * serves the built SPA from qym_platform/_static/app. Build first:
 *   npm run build && npm run build:export
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  use: {
    baseURL: 'http://localhost:8000',
    trace: 'on-first-retry',
  },
})
