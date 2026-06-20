import { describe, expect, it } from 'vitest'
import {
  SPAN_KIND_HUES,
  classifySpan,
  extractErrorInfo,
  extractMessages,
  extractReasoning,
  extractScores,
  spanCost,
  spanModel,
  spanStatus,
  spanTokens,
} from './spans'
import type { TraceData, TraceSpan } from './types'
// tsconfig has no resolveJsonModule — fixtures load via Vite ?raw (see metrics.test.ts).
import traceOkRaw from './__fixtures__/trace-item-ok.json?raw'

const okData = JSON.parse(traceOkRaw) as TraceData

function span(attributes: Record<string, unknown>, rest: Partial<TraceSpan> = {}): TraceSpan {
  return { span_id: 's', attributes, ...rest }
}

describe('classifySpan', () => {
  it('classifies the seeded fixture spans (CHAIN / AGENT / EVALUATOR)', () => {
    const kinds = (okData.spans ?? []).map(classifySpan)
    expect(kinds).toEqual(['CHAIN', 'AGENT', 'EVALUATOR'])
  })

  it('reads attribute aliases and normalizes casing/punctuation', () => {
    expect(classifySpan(span({ 'openinference.span.kind': 'llm' }))).toBe('LLM')
    expect(classifySpan(span({ 'ai.openinference.span.kind': 'Tool' }))).toBe('TOOL')
    expect(classifySpan(span({ 'span.kind': 're-triever' }))).toBe('RETRIEVER')
    expect(classifySpan(span({ 'openinference.span.kind': 'EMBEDDING' }))).toBe('EMBED')
    expect(classifySpan(span({}, { kind: 'CHAIN' }))).toBe('CHAIN')
    expect(classifySpan(span({}))).toBe('DEFAULT')
    expect(classifySpan(span({ 'openinference.span.kind': 'INTERNAL' }))).toBe('DEFAULT')
  })

  it('maps every kind to an existing CSS token (no raw hex)', () => {
    for (const hue of Object.values(SPAN_KIND_HUES)) {
      expect(hue).toMatch(/^var\(--[a-z0-9-]+\)$/)
    }
  })
})

describe('spanModel / spanTokens / spanCost', () => {
  it('takes the basename of provider-prefixed model names', () => {
    expect(spanModel(span({ 'llm.model_name': 'openai/gpt-4o' }))).toBe('gpt-4o')
    expect(spanModel(span({ 'gen_ai.request.model': 'claude-sonnet-4-6' }))).toBe('claude-sonnet-4-6')
    expect(spanModel(span({}))).toBe('')
  })

  it('returns null for missing/zero tokens and cost', () => {
    expect(spanTokens(span({}))).toBeNull()
    expect(spanTokens(span({ 'llm.token_count.total': 0 }))).toBeNull()
    expect(spanTokens(span({ 'gen_ai.usage.total_tokens': 321 }))).toBe(321)
    expect(spanCost(span({}))).toBeNull()
    expect(spanCost(span({ 'llm.cost.total': 0.004 }))).toBe(0.004)
  })
})

describe('spanStatus', () => {
  it('normalizes to ok/error/unset', () => {
    expect(spanStatus({ status: 'ERROR' })).toBe('error')
    expect(spanStatus({ status: 'error' })).toBe('error')
    expect(spanStatus({ status: 'OK' })).toBe('ok')
    expect(spanStatus({ status: 'UNSET' })).toBe('unset')
    expect(spanStatus({ status: null })).toBe('unset')
    expect(spanStatus(null)).toBe('unset')
  })
})

describe('extractScores', () => {
  it('reads score.* events from the fixture root span', () => {
    const root = (okData.spans ?? [])[0]
    const scores = extractScores(root)
    expect(scores.map((s) => s.name)).toEqual(['exact_match', 'answer_relevancy', 'tone_compliance'])
    expect(scores.map((s) => s.value)).toEqual([1, 1, 1])
  })

  it('returns [] when there are no events', () => {
    expect(extractScores(span({}))).toEqual([])
  })
})

describe('extractErrorInfo', () => {
  it('prefers the exception event', () => {
    const s = span(
      { 'error.message': 'attr-level' },
      {
        events: [
          {
            name: 'exception',
            attributes: {
              'exception.type': 'RuntimeError',
              'exception.message': 'boom',
              'exception.stacktrace': 'trace...',
            },
          },
        ],
      },
    )
    expect(extractErrorInfo(s)).toEqual({ type: 'RuntimeError', message: 'boom', stacktrace: 'trace...' })
  })

  it('falls back to error attributes, else null', () => {
    expect(extractErrorInfo(span({ 'otel.status_description': 'failed hard' }))).toEqual({
      type: '',
      message: 'failed hard',
      stacktrace: '',
    })
    expect(extractErrorInfo(span({}))).toBeNull()
  })
})

describe('extractMessages', () => {
  it('parses flattened messages with tool calls and multi-part content', () => {
    const attrs = {
      'llm.input_messages.0.message.role': 'system',
      'llm.input_messages.0.message.content': 'be nice',
      'llm.input_messages.1.message.role': 'assistant',
      'llm.input_messages.1.message.contents.0.message_content.type': 'text',
      'llm.input_messages.1.message.contents.0.message_content.text': 'part one',
      'llm.input_messages.1.message.contents.1.message_content.type': 'text',
      'llm.input_messages.1.message.contents.1.message_content.text': 'part two',
      'llm.input_messages.1.message.tool_calls.0.tool_call.function.name': 'search',
      'llm.input_messages.1.message.tool_calls.0.tool_call.function.arguments': '{"q":1}',
      'llm.input_messages.1.message.tool_calls.0.tool_call.id': 'tc-1',
      'llm.input_messages.2.message.role': 'tool',
      'llm.input_messages.2.message.content': 'result',
      'llm.input_messages.2.message.tool_call_id': 'tc-1',
    }
    const msgs = extractMessages(attrs, 'llm.input_messages')
    expect(msgs).toHaveLength(3)
    expect(msgs[0]).toMatchObject({ role: 'system', content: 'be nice' })
    expect(msgs[1].content).toBe('part one\n\npart two')
    expect(msgs[1].toolCalls).toEqual([{ name: 'search', arguments: '{"q":1}', id: 'tc-1' }])
    expect(msgs[2]).toMatchObject({ role: 'tool', toolCallId: 'tc-1' })
  })

  it('stops at the first index gap', () => {
    const msgs = extractMessages(
      { 'llm.output_messages.1.message.role': 'assistant' },
      'llm.output_messages',
    )
    expect(msgs).toEqual([])
  })
})

describe('extractReasoning', () => {
  it('reads gen_ai completion reasoning attributes', () => {
    expect(extractReasoning(span({ 'gen_ai.completion.0.reasoning': 'because' }))).toBe('because')
  })

  it('reads reasoning out of output.value choices JSON', () => {
    const s = span({
      'output.value': JSON.stringify({ choices: [{ message: { reasoning: 'deep thought' } }] }),
    })
    expect(extractReasoning(s)).toBe('deep thought')
    expect(extractReasoning(span({ 'output.value': 'not json' }))).toBeNull()
  })
})
