import { useCallback, useEffect, useRef, useState } from 'react'

/** Copy text to the clipboard with a transient `copied` flag. */
export function useClipboard(resetMs = 1500) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setCopied(false), resetMs)
      } catch {
        // Clipboard unavailable (permissions / insecure context) — no-op.
      }
    },
    [resetMs],
  )

  useEffect(() => () => window.clearTimeout(timer.current), [])

  return { copied, copy }
}
