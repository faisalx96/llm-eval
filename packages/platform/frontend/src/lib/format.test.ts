import { describe, expect, it } from 'vitest'
import {
  fmtCount,
  fmtDate,
  fmtDateTime,
  fmtMs,
  fmtPercent,
  fmtRelativeTime,
  fmtRelativeTimeWithTitle,
  fmtShortDateTime,
  fmtTokens,
  middleEllipsis,
  toDate,
} from './format'

describe('fmtPercent', () => {
  it('renders one decimal place by default', () => {
    expect(fmtPercent(0.528)).toBe('52.8%')
    expect(fmtPercent(0.5)).toBe('50.0%')
    expect(fmtPercent(1 / 3)).toBe('33.3%')
  })

  it('renders exact 0 and 1 without decimals', () => {
    expect(fmtPercent(0)).toBe('0%')
    expect(fmtPercent(1)).toBe('100%')
  })

  it('honors the dp option', () => {
    expect(fmtPercent(0.5234, { dp: 2 })).toBe('52.34%')
    expect(fmtPercent(0.5234, { dp: 0 })).toBe('52%')
  })

  it('renders em dash for missing values', () => {
    expect(fmtPercent(null)).toBe('—')
    expect(fmtPercent(undefined)).toBe('—')
    expect(fmtPercent(NaN)).toBe('—')
  })

  it('handles out-of-range fractions', () => {
    expect(fmtPercent(2.5)).toBe('250.0%')
    expect(fmtPercent(-0.123)).toBe('-12.3%')
  })
})

describe('fmtMs', () => {
  it('renders integer milliseconds under one second', () => {
    expect(fmtMs(0)).toBe('0ms')
    expect(fmtMs(129)).toBe('129ms')
    expect(fmtMs(999.4)).toBe('999ms')
  })

  it('renders one decimal of seconds under ten seconds', () => {
    expect(fmtMs(1000)).toBe('1.0s')
    expect(fmtMs(2300)).toBe('2.3s')
    expect(fmtMs(9940)).toBe('9.9s')
  })

  it('renders integer seconds between ten seconds and a minute', () => {
    expect(fmtMs(10000)).toBe('10s')
    expect(fmtMs(42400)).toBe('42s')
  })

  it('renders minutes and seconds under an hour', () => {
    expect(fmtMs(60000)).toBe('1m 0s')
    expect(fmtMs(106000)).toBe('1m 46s')
    expect(fmtMs(3599000)).toBe('59m 59s')
  })

  it('renders hours and minutes from one hour up', () => {
    expect(fmtMs(3600000)).toBe('1h 0m')
    expect(fmtMs(11400000)).toBe('3h 10m')
    expect(fmtMs(86400000)).toBe('24h 0m')
  })

  it('renders em dash for missing or negative values', () => {
    expect(fmtMs(null)).toBe('—')
    expect(fmtMs(undefined)).toBe('—')
    expect(fmtMs(-1)).toBe('—')
    expect(fmtMs(NaN)).toBe('—')
    expect(fmtMs(Infinity)).toBe('—')
  })
})

describe('fmtCount', () => {
  it('renders grouped integers below 10K', () => {
    expect(fmtCount(0)).toBe('0')
    expect(fmtCount(999)).toBe('999')
    expect(fmtCount(1234)).toBe('1,234')
    expect(fmtCount(9999)).toBe('9,999')
  })

  it('abbreviates from 10K up', () => {
    expect(fmtCount(10000)).toBe('10.0K')
    expect(fmtCount(12345)).toBe('12.3K')
    expect(fmtCount(999999)).toBe('1000.0K')
    expect(fmtCount(1234567)).toBe('1.2M')
  })

  it('keeps the sign on negatives', () => {
    expect(fmtCount(-12345)).toBe('-12.3K')
    expect(fmtCount(-42)).toBe('-42')
  })

  it('renders em dash for missing values', () => {
    expect(fmtCount(null)).toBe('—')
    expect(fmtCount(undefined)).toBe('—')
    expect(fmtCount(NaN)).toBe('—')
  })
})

describe('fmtTokens', () => {
  it('never abbreviates token counts', () => {
    expect(fmtTokens(0)).toBe('0')
    expect(fmtTokens(1234)).toBe('1,234')
    expect(fmtTokens(1234567)).toBe('1,234,567')
  })

  it('rounds fractional inputs', () => {
    expect(fmtTokens(1234.6)).toBe('1,235')
  })

  it('renders em dash for missing values', () => {
    expect(fmtTokens(null)).toBe('—')
    expect(fmtTokens(undefined)).toBe('—')
    expect(fmtTokens(NaN)).toBe('—')
  })
})

describe('date formatting', () => {
  // Construct via local-time components so assertions hold in any timezone.
  const d = new Date(2026, 5, 11, 9, 5) // Jun 11 2026 09:05 local

  it('fmtDateTime renders MMM D, YYYY HH:mm', () => {
    expect(fmtDateTime(d)).toBe('Jun 11, 2026 09:05')
    expect(fmtDateTime(new Date(2025, 11, 31, 23, 59))).toBe('Dec 31, 2025 23:59')
  })

  it('fmtShortDateTime renders MMM D HH:mm', () => {
    expect(fmtShortDateTime(d)).toBe('Jun 11 09:05')
  })

  it('fmtDate renders MMM D, YYYY', () => {
    expect(fmtDate(d)).toBe('Jun 11, 2026')
  })

  it('accepts timestamps and ISO strings', () => {
    expect(fmtDateTime(d.getTime())).toBe('Jun 11, 2026 09:05')
    expect(fmtDate(d.toISOString())).toBe('Jun 11, 2026')
  })

  it('renders em dash for invalid input', () => {
    expect(fmtDateTime(null)).toBe('—')
    expect(fmtDateTime('not a date')).toBe('—')
    expect(fmtShortDateTime(undefined)).toBe('—')
    expect(fmtDate('')).toBe('—')
  })

  it('toDate rejects invalid values', () => {
    expect(toDate('nope')).toBeNull()
    expect(toDate('')).toBeNull()
    expect(toDate(null)).toBeNull()
    expect(toDate(d)).toEqual(d)
  })
})

describe('fmtRelativeTime', () => {
  const now = new Date(2026, 5, 11, 12, 0, 0)

  it('renders just now under a minute', () => {
    expect(fmtRelativeTime(new Date(now.getTime() - 30_000), now)).toBe('just now')
    expect(fmtRelativeTime(now, now)).toBe('just now')
  })

  it('clamps future timestamps to just now', () => {
    expect(fmtRelativeTime(new Date(now.getTime() + 60 * 60_000), now)).toBe('just now')
  })

  it('renders minutes, hours, days', () => {
    expect(fmtRelativeTime(new Date(now.getTime() - 5 * 60_000), now)).toBe('5m ago')
    expect(fmtRelativeTime(new Date(now.getTime() - 2 * 3_600_000), now)).toBe('2h ago')
    expect(fmtRelativeTime(new Date(now.getTime() - 3 * 86_400_000), now)).toBe('3d ago')
    expect(fmtRelativeTime(new Date(now.getTime() - 29 * 86_400_000), now)).toBe('29d ago')
  })

  it('falls back to the absolute date after 30 days', () => {
    expect(fmtRelativeTime(new Date(2026, 0, 2, 12, 0), now)).toBe('Jan 2, 2026')
  })

  it('renders em dash for invalid input', () => {
    expect(fmtRelativeTime(null, now)).toBe('—')
    expect(fmtRelativeTime('garbage', now)).toBe('—')
  })

  it('fmtRelativeTimeWithTitle pairs label with the absolute datetime', () => {
    const date = new Date(2026, 5, 11, 10, 0)
    expect(fmtRelativeTimeWithTitle(date, now)).toEqual({
      label: '2h ago',
      title: 'Jun 11, 2026 10:00',
    })
  })
})

describe('middleEllipsis', () => {
  it('returns short strings unchanged', () => {
    expect(middleEllipsis('abc', 10)).toBe('abc')
    expect(middleEllipsis('exactly10!', 10)).toBe('exactly10!')
  })

  it('truncates the middle and never exceeds max', () => {
    expect(middleEllipsis('0123456789abcdef', 9)).toBe('0123…cdef')
    expect(middleEllipsis('abcdefghij', 5)).toBe('ab…ij')
    const long = 'x'.repeat(200)
    for (const max of [4, 7, 16, 64]) {
      expect(middleEllipsis(long, max)).toHaveLength(max)
      expect(middleEllipsis(long, max)).toContain('…')
    }
  })

  it('keeps head and tail visible', () => {
    const id = 'run-2026-06-11-support-copilot-gpt4o-final'
    const out = middleEllipsis(id, 20)
    expect(out.startsWith('run-2026-')).toBe(true)
    expect(out.endsWith('o-final')).toBe(true)
  })

  it('handles degenerate max values', () => {
    expect(middleEllipsis('abcdef', 1)).toBe('…')
    expect(middleEllipsis('abcdef', 0)).toBe('…')
    expect(middleEllipsis('abcdef', 2)).toBe('a…')
  })

  it('handles null and undefined', () => {
    expect(middleEllipsis(null, 5)).toBe('')
    expect(middleEllipsis(undefined, 5)).toBe('')
  })
})
