import { describe, expect, it } from 'vitest'
import { count, pluralize } from './pluralize'

describe('pluralize', () => {
  it('appends s for regular nouns', () => {
    expect(pluralize('run')).toBe('runs')
    expect(pluralize('dataset')).toBe('datasets')
  })

  it('handles consonant+y → ies', () => {
    expect(pluralize('query')).toBe('queries')
    expect(pluralize('entry')).toBe('entries')
  })

  it('keeps vowel+y regular', () => {
    expect(pluralize('day')).toBe('days')
  })

  it('appends es for sibilant endings', () => {
    expect(pluralize('match')).toBe('matches')
    expect(pluralize('status')).toBe('statuses')
    expect(pluralize('box')).toBe('boxes')
  })

  it('uses the irregular map', () => {
    expect(pluralize('child')).toBe('children')
    expect(pluralize('analysis')).toBe('analyses')
    expect(pluralize('criterion')).toBe('criteria')
  })
})

describe('count', () => {
  it('uses the singular for exactly 1', () => {
    expect(count(1, 'run')).toBe('1 run')
  })

  it('pluralizes for other counts including zero', () => {
    expect(count(3, 'run')).toBe('3 runs')
    expect(count(0, 'run')).toBe('0 runs')
    expect(count(2, 'query')).toBe('2 queries')
  })

  it('accepts an explicit plural override', () => {
    expect(count(2, 'corpus', 'corpora')).toBe('2 corpora')
    expect(count(1, 'corpus', 'corpora')).toBe('1 corpus')
  })
})
