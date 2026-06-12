import * as RadixDropdown from '@radix-ui/react-dropdown-menu'
import { forwardRef } from 'react'
import type { ComponentPropsWithoutRef, ElementRef, ReactElement, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import styles from './DropdownMenu.module.css'

export interface DropdownMenuProps {
  /** The trigger element (typically an IconButton kebab). Radix asChild. */
  trigger: ReactElement
  children: ReactNode
  align?: 'start' | 'center' | 'end'
}

/** The app kebab menu. Compose with DropdownMenuItem / DropdownMenuSeparator. */
export function DropdownMenu({ trigger, children, align = 'end' }: DropdownMenuProps) {
  return (
    <RadixDropdown.Root>
      <RadixDropdown.Trigger asChild>{trigger}</RadixDropdown.Trigger>
      <RadixDropdown.Portal>
        <RadixDropdown.Content className={styles.content} align={align} sideOffset={4}>
          {children}
        </RadixDropdown.Content>
      </RadixDropdown.Portal>
    </RadixDropdown.Root>
  )
}

export interface DropdownMenuItemProps
  extends ComponentPropsWithoutRef<typeof RadixDropdown.Item> {
  /** Optional leading icon (lucide element). Decorative. */
  icon?: ReactNode
  /** Destructive item → red text. */
  danger?: boolean
}

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof RadixDropdown.Item>,
  DropdownMenuItemProps
>(function DropdownMenuItem({ icon, danger = false, className, children, ...props }, ref) {
  return (
    <RadixDropdown.Item
      ref={ref}
      className={cn(styles.item, danger && styles.danger, className)}
      {...props}
    >
      {icon != null && (
        <span className={styles.icon} aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </RadixDropdown.Item>
  )
})

export function DropdownMenuSeparator() {
  return <RadixDropdown.Separator className={styles.separator} />
}
