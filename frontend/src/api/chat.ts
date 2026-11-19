import { ApiError } from './client'
import type { ChatContext, ChatEvent, ChatHistoryTurn, ChatKnown } from './types'

/**
 * Split a buffer of server-sent events into complete events and the unfinished rest.
 * An event is `event: <type>` and `data: <json>` lines, ended by a blank line.
 */
export function parseSse(buffer: string): { events: ChatEvent[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const blocks = normalized.split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: ChatEvent[] = []
  for (const block of blocks) {
    let type = ''
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) type = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!type || data.length === 0) continue
    try {
      events.push({ type, ...(JSON.parse(data.join('\n')) as object) } as ChatEvent)
    } catch {
      // A malformed event is dropped; the stream keeps going.
    }
  }
  return { events, rest }
}

/**
 * Ask the assistant and call `onEvent` for each server-sent event as it arrives.
 * Resolves when the stream ends. Rejects with `ApiError` if the request fails; an `error` event is delivered
 * to `onEvent` like any other, so the caller decides what it means.
 */
export async function streamChat(
  message: string,
  history: ChatHistoryTurn[],
  extra: { context?: ChatContext; known: ChatKnown[] },
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify({ message, history, context: extra.context, known: extra.known }),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'Could not reach the server.')
  }
  if (!res.ok || !res.body) throw new ApiError(res.status, 'The assistant is not available right now.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const { events, rest } = parseSse(buffer)
      buffer = rest
      events.forEach(onEvent)
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'The connection was interrupted.')
  }
}
