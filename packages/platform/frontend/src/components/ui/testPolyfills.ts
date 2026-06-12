/**
 * jsdom lacks layout/observer APIs that Radix popper-positioned layers
 * (tooltip, dropdown) depend on. Import this at the top of any test file
 * that opens a floating Radix layer.
 *
 * Lives in components/ui (not src/test/setup.ts) because that setup file
 * is shared infrastructure owned by the shell scaffold.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const g = globalThis as any

if (typeof g.ResizeObserver === 'undefined') {
  g.ResizeObserver = ResizeObserverStub
}

if (typeof window !== 'undefined') {
  const proto = window.HTMLElement.prototype as any
  if (typeof proto.scrollIntoView !== 'function') {
    proto.scrollIntoView = () => {}
  }
  if (typeof proto.hasPointerCapture !== 'function') {
    proto.hasPointerCapture = () => false
  }
  if (typeof proto.setPointerCapture !== 'function') {
    proto.setPointerCapture = () => {}
  }
  if (typeof proto.releasePointerCapture !== 'function') {
    proto.releasePointerCapture = () => {}
  }
}

export {}
