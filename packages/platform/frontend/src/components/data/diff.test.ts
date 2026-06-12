import { describe, expect, it } from 'vitest'
import { diffWords, type DiffSegment } from './diff'

function reconstructA(segments: DiffSegment[]): string {
  return segments
    .filter((s) => s.type !== 'ins')
    .map((s) => s.text)
    .join('')
}

function reconstructB(segments: DiffSegment[]): string {
  return segments
    .filter((s) => s.type !== 'del')
    .map((s) => s.text)
    .join('')
}

describe('diffWords', () => {
  it('returns a single equal segment for identical strings', () => {
    expect(diffWords('hello world', 'hello world')).toEqual([
      { type: 'equal', text: 'hello world' },
    ])
  })

  it('returns [] for two empty strings', () => {
    expect(diffWords('', '')).toEqual([])
  })

  it('handles empty → text as a pure insertion', () => {
    expect(diffWords('', 'new text')).toEqual([{ type: 'ins', text: 'new text' }])
  })

  it('handles text → empty as a pure deletion', () => {
    expect(diffWords('old text', '')).toEqual([{ type: 'del', text: 'old text' }])
  })

  it('diffs a single word substitution exactly', () => {
    expect(diffWords('a b c', 'a x c')).toEqual([
      { type: 'equal', text: 'a ' },
      { type: 'del', text: 'b' },
      { type: 'ins', text: 'x' },
      { type: 'equal', text: ' c' },
    ])
  })

  it('marks pure additions at the end', () => {
    const segs = diffWords('select id', 'select id from users')
    expect(segs[0]).toEqual({ type: 'equal', text: 'select id' })
    expect(segs.filter((s) => s.type === 'del')).toEqual([])
    expect(reconstructB(segs)).toBe('select id from users')
  })

  it('marks pure removals at the start', () => {
    const segs = diffWords('really very fast', 'fast')
    expect(segs.filter((s) => s.type === 'ins')).toEqual([])
    expect(segs[segs.length - 1].text.trim()).toBe('fast')
  })

  it('reconstructs both inputs from the segments (sentence fixture)', () => {
    const a = 'The quick brown fox jumps over the lazy dog.'
    const b = 'The slow brown cat jumps over the dog, twice.'
    const segs = diffWords(a, b)
    expect(reconstructA(segs)).toBe(a)
    expect(reconstructB(segs)).toBe(b)
  })

  it('reconstructs both inputs for multi-line code fixture', () => {
    const a = 'SELECT name, age\nFROM users\nWHERE age > 21'
    const b = 'SELECT name, email\nFROM users\nWHERE age >= 21\nORDER BY name'
    const segs = diffWords(a, b)
    expect(reconstructA(segs)).toBe(a)
    expect(reconstructB(segs)).toBe(b)
    // The unchanged middle survives as equal.
    expect(
      segs.some((s) => s.type === 'equal' && s.text.includes('FROM users')),
    ).toBe(true)
  })

  it('classifies changed words on the correct sides', () => {
    const segs = diffWords('status: pass', 'status: fail')
    const dels = segs.filter((s) => s.type === 'del').map((s) => s.text)
    const inss = segs.filter((s) => s.type === 'ins').map((s) => s.text)
    expect(dels.join('')).toContain('pass')
    expect(inss.join('')).toContain('fail')
    expect(dels.join('')).not.toContain('fail')
  })

  it('never emits two adjacent segments of the same type', () => {
    const segs = diffWords(
      'one two three four five six',
      'one TWO three FOUR five SIX seven',
    )
    for (let i = 1; i < segs.length; i++) {
      expect(segs[i].type).not.toBe(segs[i - 1].type)
    }
  })

  it('preserves whitespace runs exactly', () => {
    const a = 'a  b\t\tc'
    const b = 'a  b\t\td'
    const segs = diffWords(a, b)
    expect(reconstructA(segs)).toBe(a)
    expect(reconstructB(segs)).toBe(b)
  })
})
