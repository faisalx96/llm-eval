import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// vitest globals are off, so RTL's auto-cleanup never registers itself.
// Without this, components leak between tests within a file.
afterEach(() => {
  cleanup()
})
