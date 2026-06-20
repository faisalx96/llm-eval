/** Irregular plural forms used across the platform's copy. */
const IRREGULARS: Record<string, string> = {
  child: 'children',
  person: 'people',
  criterion: 'criteria',
  analysis: 'analyses',
  matrix: 'matrices',
  index: 'indices',
}

/** Pluralize an English noun: run → runs, query → queries, match → matches. */
export function pluralize(word: string): string {
  const irregular = IRREGULARS[word.toLowerCase()]
  if (irregular) return irregular
  if (/[^aeiou]y$/i.test(word)) return `${word.slice(0, -1)}ies`
  if (/(s|x|z|ch|sh)$/i.test(word)) return `${word}es`
  return `${word}s`
}

/**
 * Format a count with its noun: count(1, 'run') → '1 run',
 * count(3, 'run') → '3 runs'. Pass `plural` to override the derived form.
 */
export function count(n: number, word: string, plural?: string): string {
  const label = n === 1 ? word : (plural ?? pluralize(word))
  return `${n} ${label}`
}
