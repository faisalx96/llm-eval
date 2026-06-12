import { vi } from 'vitest'

/**
 * jsdom lacks ResizeObserver, which @tanstack/react-virtual and Radix
 * popovers both require. Call once at the top of a test file.
 */
export function stubResizeObserver(): void {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
}
