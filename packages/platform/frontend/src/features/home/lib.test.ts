import { describe, expect, it } from 'vitest'
import { slugify } from './lib'

describe('slugify', () => {
  it('lowercases and hyphenates', () => {
    expect(slugify('Customer Support Copilot')).toBe('customer-support-copilot')
  })

  it('strips symbols and edge hyphens', () => {
    expect(slugify('  Text2SQL — Bench!  ')).toBe('text2sql-bench')
  })

  it('caps length at 64', () => {
    expect(slugify('x'.repeat(100))).toHaveLength(64)
  })
})
