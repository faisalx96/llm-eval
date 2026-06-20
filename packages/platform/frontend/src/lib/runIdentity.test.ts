import { describe, expect, it } from 'vitest'
import { deriveRunName, isUuid, stripModelProvider } from './runIdentity'

const UUID = '1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed'

describe('isUuid', () => {
  it('accepts canonical hyphenated UUIDs in any case', () => {
    expect(isUuid(UUID)).toBe(true)
    expect(isUuid(UUID.toUpperCase())).toBe(true)
    expect(isUuid(`  ${UUID}  `)).toBe(true)
    expect(isUuid('00000000-0000-0000-0000-000000000000')).toBe(true)
  })

  it('rejects non-UUID strings', () => {
    expect(isUuid('')).toBe(false)
    expect(isUuid(null)).toBe(false)
    expect(isUuid(undefined)).toBe(false)
    expect(isUuid('nightly-regression')).toBe(false)
    expect(isUuid('1b9d6bcd')).toBe(false)
    // 32 hex chars without hyphens is not the canonical form
    expect(isUuid(UUID.replaceAll('-', ''))).toBe(false)
    // UUID embedded in a longer string
    expect(isUuid(`run-${UUID}`)).toBe(false)
    // non-hex characters
    expect(isUuid('1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bez')).toBe(false)
  })
})

describe('stripModelProvider', () => {
  it('removes the provider prefix', () => {
    expect(stripModelProvider('qwen/qwen3-235b')).toBe('qwen3-235b')
    expect(stripModelProvider('openai/gpt-4o')).toBe('gpt-4o')
  })

  it('leaves bare model names untouched', () => {
    expect(stripModelProvider('gpt-4o')).toBe('gpt-4o')
  })

  it('keeps a leading slash (legacy semantics: slashIdx must be > 0)', () => {
    expect(stripModelProvider('/weird')).toBe('/weird')
  })

  it('handles missing input', () => {
    expect(stripModelProvider(null)).toBe('')
    expect(stripModelProvider(undefined)).toBe('')
    expect(stripModelProvider('')).toBe('')
  })
})

describe('deriveRunName', () => {
  // Local-time constructor keeps assertions timezone-independent.
  const startedAt = new Date(2026, 5, 11, 14, 30)

  it('prefers the top-level display name', () => {
    expect(
      deriveRunName({
        display_name: 'Nightly regression',
        run_name: 'other',
        run_metadata: { name: 'meta-name' },
      }),
    ).toBe('Nightly regression')
  })

  it('falls back through run_metadata names, then run_name, then external id', () => {
    expect(deriveRunName({ run_metadata: { display_name: 'Meta display' } })).toBe('Meta display')
    expect(deriveRunName({ run_metadata: { name: 'Meta name' } })).toBe('Meta name')
    expect(deriveRunName({ run_metadata: { run_name: 'Meta run name' } })).toBe('Meta run name')
    expect(deriveRunName({ run_name: 'plain-run-name' })).toBe('plain-run-name')
    expect(deriveRunName({ external_run_id: 'ext-42' })).toBe('ext-42')
  })

  it('trims whitespace and skips blank candidates', () => {
    expect(deriveRunName({ run_name: '   ', external_run_id: '  ext-42  ' })).toBe('ext-42')
  })

  it('skips UUID candidates', () => {
    expect(
      deriveRunName({
        run_name: UUID,
        external_run_id: 'ext-7',
      }),
    ).toBe('ext-7')
  })

  it('composes task · model · MMM D HH:mm when no name is given', () => {
    expect(
      deriveRunName({
        task_name: 'support-copilot',
        model_name: 'openai/gpt-4o',
        created_at: startedAt,
      }),
    ).toBe('support-copilot · gpt-4o · Jun 11 14:30')
  })

  it('composes from partial fields', () => {
    expect(deriveRunName({ task_name: 'text2sql' })).toBe('text2sql')
    expect(deriveRunName({ model_name: 'qwen/qwen3-235b' })).toBe('qwen3-235b')
    expect(deriveRunName({ task_name: 'text2sql', created_at: startedAt })).toBe(
      'text2sql · Jun 11 14:30',
    )
  })

  it('uses started_at, then timestamp, when created_at is missing', () => {
    expect(deriveRunName({ task_name: 't', started_at: startedAt })).toBe('t · Jun 11 14:30')
    expect(deriveRunName({ task_name: 't', timestamp: startedAt.getTime() })).toBe(
      't · Jun 11 14:30',
    )
  })

  it('never returns a UUID', () => {
    const uuidOnly = deriveRunName({ run_id: UUID, run_name: UUID, external_run_id: UUID })
    expect(uuidOnly).toBe(`Run ${UUID.slice(0, 8)}`)
    expect(isUuid(uuidOnly)).toBe(false)

    for (const run of [
      { run_id: UUID },
      { run_id: UUID, run_metadata: { name: UUID } },
      { task_name: 'task', run_id: UUID },
      {},
      null,
      undefined,
    ]) {
      expect(isUuid(deriveRunName(run))).toBe(false)
    }
  })

  it('uses a non-UUID run_id as last resort', () => {
    expect(deriveRunName({ run_id: 'ragbench-qwen3-251205-1918' })).toBe(
      'ragbench-qwen3-251205-1918',
    )
  })

  it('falls back to Untitled run when nothing usable exists', () => {
    expect(deriveRunName({})).toBe('Untitled run')
    expect(deriveRunName(null)).toBe('Untitled run')
    expect(deriveRunName(undefined)).toBe('Untitled run')
    expect(deriveRunName({ run_name: '', run_id: '   ' })).toBe('Untitled run')
  })
})
