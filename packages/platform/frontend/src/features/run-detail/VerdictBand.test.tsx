import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TraceStatsSection } from './TraceStatsSection'
import { VerdictBand } from './VerdictBand'
import { makeRun } from './__fixtures__/runDetail'

afterEach(cleanup)

describe('VerdictBand min-n gating', () => {
  it('renders the neutral in-progress band while RUNNING below min n', () => {
    const run = makeRun({ status: 'RUNNING', completed_items: 3, total_items: 12 })
    render(<VerdictBand run={run} scored={3} gated onMetricClick={vi.fn()} />)

    expect(screen.getByText('3 of 12 scored — too early to judge')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(screen.getByText('item 3 of 12')).toBeInTheDocument()
    // No judgable pass rates while gated.
    expect(screen.queryByText('exact_match')).not.toBeInTheDocument()
  })

  it('renders one clickable card per metric when not gated', () => {
    const onMetricClick = vi.fn()
    render(<VerdictBand run={makeRun()} scored={12} gated={false} onMetricClick={onMetricClick} />)

    // pass_count 6 / (6+6) = 50%
    expect(screen.getAllByText('50.0%')).toHaveLength(2)
    expect(screen.getAllByText('6 pass · 6 fail')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: /exact_match/ }))
    expect(onMetricClick).toHaveBeenCalledWith('exact_match')
  })
})

describe('TraceStatsSection collapse rule', () => {
  it('collapses to one hint line when tokens/llm/tool calls are all zero', () => {
    render(<TraceStatsSection run={makeRun()} />)
    expect(screen.getByText(/no trace data — this task isn't instrumented/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /add qym tracing/i })).toBeInTheDocument()
  })

  it('shows only the non-empty tiles when instrumented', () => {
    const run = makeRun({
      trace_stats: {
        avg_tokens: 812,
        avg_llm_calls: 2.5,
        avg_tool_calls: 0,
        tool_success_rate: null,
        avg_llm_ms: 432.1,
      },
    })
    render(<TraceStatsSection run={run} />)
    expect(screen.queryByText(/no trace data/i)).not.toBeInTheDocument()
    expect(screen.getByText('Avg tokens')).toBeInTheDocument()
    expect(screen.getByText('812')).toBeInTheDocument()
    expect(screen.getByText('Avg LLM calls')).toBeInTheDocument()
    // Zero/null tiles are dropped entirely.
    expect(screen.queryByText('Avg tool calls')).not.toBeInTheDocument()
    expect(screen.queryByText('Tool success')).not.toBeInTheDocument()
  })
})
