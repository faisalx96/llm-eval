/**
 * Word-level diff via longest-common-subsequence over word/whitespace tokens.
 *
 * Tokens preserve the original text exactly (whitespace runs are their own
 * tokens), so concatenating the `equal` + `del` segments reproduces `a` and
 * `equal` + `ins` segments reproduces `b`.
 */

export type DiffType = 'equal' | 'ins' | 'del'

export interface DiffSegment {
  type: DiffType
  text: string
}

/** Above this n*m product, fall back to whole-string replace (keeps O(n*m) DP bounded). */
const MAX_DP_CELLS = 1_000_000

function tokenize(s: string): string[] {
  return s.match(/\S+|\s+/g) ?? []
}

/**
 * Diff two strings at word granularity.
 *
 * Returns merged segments (no two adjacent segments share a type).
 * Insertions/deletions interleave del-first at each divergence point.
 */
export function diffWords(a: string, b: string): DiffSegment[] {
  if (a === b) return a ? [{ type: 'equal', text: a }] : []

  const at = tokenize(a)
  const bt = tokenize(b)
  const n = at.length
  const m = bt.length

  if (n === 0) return [{ type: 'ins', text: b }]
  if (m === 0) return [{ type: 'del', text: a }]
  if (n * m > MAX_DP_CELLS) {
    return [
      { type: 'del', text: a },
      { type: 'ins', text: b },
    ]
  }

  // dp[i][j] = LCS length of at[i..] vs bt[j..], flattened row-major.
  const width = m + 1
  const dp = new Uint32Array((n + 1) * width)
  for (let i = n - 1; i >= 0; i--) {
    const row = i * width
    const below = (i + 1) * width
    for (let j = m - 1; j >= 0; j--) {
      dp[row + j] =
        at[i] === bt[j]
          ? dp[below + j + 1] + 1
          : Math.max(dp[below + j], dp[row + j + 1])
    }
  }

  const segments: DiffSegment[] = []
  const push = (type: DiffType, text: string): void => {
    const last = segments[segments.length - 1]
    if (last && last.type === type) last.text += text
    else segments.push({ type, text })
  }

  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (at[i] === bt[j]) {
      push('equal', at[i])
      i++
      j++
    } else if (dp[(i + 1) * width + j] >= dp[i * width + j + 1]) {
      push('del', at[i])
      i++
    } else {
      push('ins', bt[j])
      j++
    }
  }
  while (i < n) push('del', at[i++])
  while (j < m) push('ins', bt[j++])

  return segments
}
