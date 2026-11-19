import type { ChatKnown, ChatSource } from '../api/types'
import { citedRefs } from './answer'

export type ChatMessage =
  | { id: number; role: 'user'; text: string }
  | {
      id: number
      role: 'assistant'
      text: string
      sources: Record<string, ChatSource>
      /** What the assistant is doing right now ("Searching papers for …"); null once it writes or finishes. */
      status: string | null
      streaming: boolean
    }
  | { id: number; role: 'error'; text: string; retry: string }

/** The record the page is showing when the user asks. `name` is only for display; the server gets kind and id. */
export type PageContext = { kind: 'faculty'; id: number; name: string }

const KEY = 'uiuc.chat.v1'
/** Matches the server: `history` holds at most 20 turns, and the model sees the last 8. */
const MAX_MESSAGES = 20
const MAX_KNOWN = 30

/**
 * What to keep for a reload: finished turns only. Errors, half-written answers and a question whose answer was lost
 * are left out. Null when there is nothing worth keeping.
 */
export function serializeChat(messages: ChatMessage[], context: PageContext | null): string | null {
  const kept = messages.filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.streaming && m.text.trim()))
  while (kept.at(-1)?.role === 'user') kept.pop()
  const tail = kept.slice(-MAX_MESSAGES)
  while (tail[0]?.role === 'assistant') tail.shift()
  return tail.length || context ? JSON.stringify({ v: 1, messages: tail, context }) : null
}

const isObject = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x)

/** Inverse of `serializeChat`. Anything that does not look like what it wrote is dropped, never thrown on. */
export function restoreChat(raw: string | null): { messages: ChatMessage[]; context: PageContext | null } {
  const empty = { messages: [], context: null }
  if (!raw) return empty
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return empty
  }
  if (!isObject(data) || data.v !== 1 || !Array.isArray(data.messages)) return empty
  const messages: ChatMessage[] = []
  for (const m of data.messages as unknown[]) {
    if (!isObject(m) || typeof m.id !== 'number' || typeof m.text !== 'string') continue
    if (m.role === 'user') messages.push({ id: m.id, role: 'user', text: m.text })
    else if (m.role === 'assistant' && isObject(m.sources))
      messages.push({ id: m.id, role: 'assistant', text: m.text, sources: m.sources as Record<string, ChatSource>, status: null, streaming: false })
  }
  const c = data.context
  const context = isObject(c) && c.kind === 'faculty' && typeof c.id === 'number' && typeof c.name === 'string' ? { kind: 'faculty' as const, id: c.id, name: c.name } : null
  return { messages, context }
}

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null // blocked: the chat works, it just is not kept
  }
}

export const loadChat = () => restoreChat(storage()?.getItem(KEY) ?? null)

export function saveChat(messages: ChatMessage[], context: PageContext | null) {
  const raw = serializeChat(messages, context)
  try {
    if (raw) storage()?.setItem(KEY, raw)
    else storage()?.removeItem(KEY)
  } catch {
    // Quota exceeded or storage refused: keep chatting without persistence.
  }
}

/** Records the assistant cited in these messages, oldest first, newest 30. The server rebuilds their text from ids. */
export function knownRecords(messages: ChatMessage[]): ChatKnown[] {
  const seen = new Map<string, ChatKnown>()
  for (const m of messages) {
    if (m.role !== 'assistant') continue
    for (const ref of citedRefs(m.text, m.sources)) {
      const src = m.sources[ref]!
      const item: ChatKnown = src.kind === 'faculty' ? { kind: 'faculty', id: String(src.facultyId) } : { kind: 'paper', id: src.paperId }
      const key = `${item.kind}:${item.id}`
      seen.delete(key) // seen again later: move to the newest end
      seen.set(key, item)
    }
  }
  return [...seen.values()].slice(-MAX_KNOWN)
}
