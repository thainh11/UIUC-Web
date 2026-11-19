import { describe, expect, it } from 'vitest'
import type { ChatSource } from '../api/types'
import { knownRecords, restoreChat, serializeChat, type ChatMessage } from './chatStore'

const person: ChatSource = { ref: 'F1', kind: 'faculty', label: 'Ada Lovelace', facultyId: 7 }
const paper: ChatSource = { ref: 'P1', kind: 'paper', label: 'On engines', date: '2026-01-02', doi: null, paperId: 'W1' }
const user = (id: number, text = 'q'): ChatMessage => ({ id, role: 'user', text })
const answer = (id: number, text = 'a', over: Partial<Extract<ChatMessage, { role: 'assistant' }>> = {}): ChatMessage => ({
  id,
  role: 'assistant',
  text,
  sources: { F1: person, P1: paper },
  status: null,
  streaming: false,
  ...over,
})

describe('serializeChat / restoreChat', () => {
  it('round-trips finished turns, their sources and the open profile', () => {
    const context = { kind: 'faculty' as const, id: 7, name: 'Ada Lovelace' }
    const messages = [user(1), answer(2, 'See [F1].')]
    expect(restoreChat(serializeChat(messages, context))).toEqual({ messages, context })
  })

  it('leaves out errors, half-written answers and a question that has no answer', () => {
    const messages: ChatMessage[] = [
      user(1),
      answer(2),
      user(3),
      { id: 4, role: 'error', text: 'boom', retry: 'x' },
      user(5),
      answer(6, 'half', { streaming: true }),
    ]
    expect(restoreChat(serializeChat(messages, null)).messages.map((m) => m.id)).toEqual([1, 2])
  })

  it('keeps nothing when there is nothing finished and no profile', () => {
    expect(serializeChat([user(1)], null)).toBeNull()
    expect(serializeChat([user(1), answer(2, '  ')], null)).toBeNull()
    expect(serializeChat([], { kind: 'faculty', id: 1, name: 'A' })).not.toBeNull()
  })

  it('keeps the newest 20 messages and starts on a question', () => {
    const messages = Array.from({ length: 15 }, (_, i) => [user(2 * i + 1), answer(2 * i + 2)]).flat()
    const kept = restoreChat(serializeChat(messages, null)).messages
    expect(kept).toHaveLength(20)
    expect(kept[0]).toMatchObject({ role: 'user', id: 11 })
    expect(kept.at(-1)!.id).toBe(30)
  })

  it('restores an answer as finished even if it was saved mid-stream', () => {
    const raw = JSON.stringify({ v: 1, messages: [{ id: 1, role: 'assistant', text: 'x', sources: {}, status: 'Thinking…', streaming: true }], context: null })
    expect(restoreChat(raw).messages[0]).toMatchObject({ streaming: false, status: null })
  })

  it.each([null, '', 'not json', '[]', '{"v":2,"messages":[]}', '{"v":1,"messages":"x"}'])('ignores unusable storage %j', (raw) => {
    expect(restoreChat(raw)).toEqual({ messages: [], context: null })
  })

  it('drops malformed entries and a malformed profile but keeps the rest', () => {
    const raw = JSON.stringify({
      v: 1,
      messages: [{ id: 1, role: 'user', text: 'ok' }, { id: 'x', role: 'user', text: 'bad id' }, { id: 3, role: 'assistant', text: 'no sources' }, 5],
      context: { kind: 'faculty', id: '7', name: 'A' },
    })
    expect(restoreChat(raw)).toEqual({ messages: [{ id: 1, role: 'user', text: 'ok' }], context: null })
  })
})

describe('knownRecords', () => {
  it('lists only records the answers cite, as ids', () => {
    const messages = [user(1), answer(2, 'Only [F1].')]
    expect(knownRecords(messages)).toEqual([{ kind: 'faculty', id: '7' }])
  })

  it('puts a record cited again at the newest end, once', () => {
    const messages = [user(1), answer(2, '[F1] and [P1]'), user(3), answer(4, '[F1]')]
    expect(knownRecords(messages)).toEqual([
      { kind: 'paper', id: 'W1' },
      { kind: 'faculty', id: '7' },
    ])
  })

  it('keeps the newest 30', () => {
    const many = Array.from({ length: 40 }, (_, i): [string, ChatSource] => [`P${i + 1}`, { ...paper, ref: `P${i + 1}`, paperId: `W${i + 1}` }])
    const text = many.map(([ref]) => `[${ref}]`).join(' ')
    const known = knownRecords([answer(1, text, { sources: Object.fromEntries(many) })])
    expect(known).toHaveLength(30)
    expect(known[0]).toEqual({ kind: 'paper', id: 'W11' })
  })
})
