import * as RadixTooltip from '@radix-ui/react-tooltip'
import type { ReactElement, ReactNode } from 'react'
import styles from './Tooltip.module.css'

export interface TooltipProps {
  /** Tooltip text/content shown on the dark elevated surface. */
  content: ReactNode
  /** A single focusable element (the trigger). Rendered via Radix asChild. */
  children: ReactElement
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** Delay before showing on hover (ms). Focus shows immediately. */
  delayDuration?: number
  defaultOpen?: boolean
  /** Controlled open state (mostly for tests/demos). */
  open?: boolean
}

export function Tooltip({
  content,
  children,
  side = 'top',
  delayDuration = 400,
  defaultOpen,
  open,
}: TooltipProps) {
  return (
    <RadixTooltip.Provider delayDuration={delayDuration} skipDelayDuration={200}>
      <RadixTooltip.Root defaultOpen={defaultOpen} open={open}>
        <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
        <RadixTooltip.Portal>
          <RadixTooltip.Content className={styles.content} side={side} sideOffset={6}>
            {content}
            <RadixTooltip.Arrow className={styles.arrow} width={10} height={5} />
          </RadixTooltip.Content>
        </RadixTooltip.Portal>
      </RadixTooltip.Root>
    </RadixTooltip.Provider>
  )
}
