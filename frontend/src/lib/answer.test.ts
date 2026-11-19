import { describe, expect, it } from 'vitest'
import type { ChatSource } from '../api/types'
import { parseSse } from '../api/chat'
import { citedRefs, parseAnswer, stripRefs } from './answer'

describe('parseAnswer', () => {
  it('turns a lead-in and a bullet list into blocks with bold and citation markers', () => {
    const blocks = parseAnswer('Found two.\n\n- **Jane Doe** — works on vision [F1].\n- A paper [P2] [P3]')
    expect(blocks).toEqual([
      { type: 'p', inline: [{ type: 'text', text: 'Found two.' }] },
      {
        type: 'ul',
        items: [
          [
            { type: 'bold', text: 'Jane Doe' },
            { type: 'text', text: ' — works on vision ' },
            { type: 'ref', ref: 'F1' },
            { type: 'text', text: '.' },
          ],
          [
            { type: 'text', text: 'A paper ' },
            { type: 'ref', ref: 'P2' },
            { type: 'text', text: ' ' },
            { type: 'ref', ref: 'P3' },
          ],
        ],
      },
    ])
  })

  it('reads *italic* titles without eating bullet markers', () => {
    expect(parseAnswer('* *A Title* (2026) [P1]')).toEqual([
      {
        type: 'ul',
        items: [
          [
            { type: 'italic', text: 'A Title' },
            { type: 'text', text: ' (2026) ' },
            { type: 'ref', ref: 'P1' },
          ],
        ],
      },
    ])
  })

  it('holds back a half-written marker only while streaming', () => {
    expect(parseAnswer('See [P', true)).toEqual([{ type: 'p', inline: [{ type: 'text', text: 'See' }] }])
    expect(parseAnswer('See [P')).toEqual([{ type: 'p', inline: [{ type: 'text', text: 'See [P' }] }])
  })

  it('never produces markup from model text', () => {
    const [block] = parseAnswer('<img src=x onerror=alert(1)>')
    expect(block).toEqual({ type: 'p', inline: [{ type: 'text', text: '<img src=x onerror=alert(1)>' }] })
  })
})

describe('citations', () => {
  const sources: Record<string, ChatSource> = {
    P1: { ref: 'P1', kind: 'paper', label: 'A', date: '2026-01-01', doi: null, paperId: 'W1' },
    F1: { ref: 'F1', kind: 'faculty', label: 'B', facultyId: 7 },
  }

  it('lists only known refs, in order of first use', () => {
    expect(citedRefs('x [F1] y [P1] z [F1] w [P9]', sources)).toEqual(['F1', 'P1'])
  })

  it('strips refs from history text', () => {
    expect(stripRefs('Jane [F1] wrote this [P2].')).toBe('Jane wrote this.')
  })
})

describe('parseSse', () => {
  it('returns complete events and keeps the unfinished one', () => {
    const { events, rest } = parseSse(
      'event: status\ndata: {"tool":"search_papers","text":"Searching"}\n\nevent: delta\ndata: {"text":"Hel"}\n\nevent: delta\ndata: {"te',
    )
    expect(events).toEqual([
      { type: 'status', tool: 'search_papers', text: 'Searching' },
      { type: 'delta', text: 'Hel' },
    ])
    expect(rest).toBe('event: delta\ndata: {"te')
  })

  it('accepts CRLF and drops a malformed event without losing the next one', () => {
    const { events } = parseSse('event: delta\r\ndata: nope\r\n\r\nevent: done\r\ndata: {"cited":["P1"]}\r\n\r\n')
    expect(events).toEqual([{ type: 'done', cited: ['P1'] }])
  })
})
