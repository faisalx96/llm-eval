import * as RadixTabs from '@radix-ui/react-tabs'
import { forwardRef } from 'react'
import type { ComponentPropsWithoutRef, ElementRef } from 'react'
import { cn } from '@/lib/cn'
import styles from './Tabs.module.css'

/** Root — controlled/uncontrolled via Radix (value / defaultValue). */
export const Tabs = RadixTabs.Root

export const TabsList = forwardRef<
  ElementRef<typeof RadixTabs.List>,
  ComponentPropsWithoutRef<typeof RadixTabs.List>
>(function TabsList({ className, ...props }, ref) {
  return <RadixTabs.List ref={ref} className={cn(styles.list, className)} {...props} />
})

export interface TabsTriggerProps extends ComponentPropsWithoutRef<typeof RadixTabs.Trigger> {
  /** Optional count badge rendered after the label. */
  count?: number
}

export const TabsTrigger = forwardRef<ElementRef<typeof RadixTabs.Trigger>, TabsTriggerProps>(
  function TabsTrigger({ className, count, children, ...props }, ref) {
    return (
      <RadixTabs.Trigger ref={ref} className={cn(styles.trigger, className)} {...props}>
        {children}
        {count != null && <span className={styles.count}>{count}</span>}
      </RadixTabs.Trigger>
    )
  },
)

export const TabsContent = forwardRef<
  ElementRef<typeof RadixTabs.Content>,
  ComponentPropsWithoutRef<typeof RadixTabs.Content>
>(function TabsContent({ className, ...props }, ref) {
  return <RadixTabs.Content ref={ref} className={cn(styles.content, className)} {...props} />
})
