import { clsx, type ClassValue } from 'clsx'

/** Compose class names. Single chokepoint so a tailwind-merge style
 *  dedupe can be added later without touching call sites. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs)
}
