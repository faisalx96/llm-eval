import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@/styles/tokens.css'
import '@/styles/global.css'

/**
 * Entry for the single-file export bundle (vite.config.export.ts).
 * Placeholder until the report renderer lands.
 */
function ExportApp() {
  return <main style={{ padding: 'var(--space-xl)' }}>qym export placeholder</main>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ExportApp />
  </StrictMode>,
)
