import type { ChatSource } from '../api/types'

/** A piece of an assistant answer: plain, bold or italic text, or a citation marker such as `[P1]`. */
export type Inline = { type: 'text' | 'bold' | 'italic'; text: string } | { type: 'ref'; ref: string }
export type Block = { type: 'p'; inline: Inline[] } | { type: 'ul'; items: Inline[][] }

const TOKEN = /\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*|\[([PF]\d+)\]/g
const BULLET = /^\s*(?:[-*•]|\d+[.)])\s+/
// A marker that the stream has only started to write: "[", "[P", "[P1".
const PARTIAL_REF = /\[(?:[PF]\d*)?$/

export function parseInline(text: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  for (const m of text.matchAll(TOKEN)) {
    if (m.index > last) out.push({ type: 'text', text: text.slice(last, m.index) })
    out.push(m[1] !== undefined ? { type: 'bold', text: m[1] } : m[2] !== undefined ? { type: 'italic', text: m[2] } : { type: 'ref', ref: m[3]! })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ type: 'text', text: text.slice(last) })
  return out
}

/** Paragraphs and bullet lists from the light Markdown the assistant writes. While streaming, a half-written marker is held back. */
export function parseAnswer(text: string, streaming = false): Block[] {
  const source = streaming ? text.replace(PARTIAL_REF, '') : text
  const blocks: Block[] = []
  let paragraph: string[] = []
  let list: Inline[][] | null = null
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'p', inline: parseInline(paragraph.join(' ')) })
    paragraph = []
  }
  const flushList = () => {
    if (list) blocks.push({ type: 'ul', items: list })
    list = null
  }
  for (const line of source.split('\n')) {
    if (!line.trim()) {
      flushParagraph()
      flushList()
    } else if (BULLET.test(line)) {
      flushParagraph()
      list ??= []
      list.push(parseInline(line.replace(BULLET, '')))
    } else if (list && /^\s{2,}\S/.test(line)) {
      list[list.length - 1]!.push(...parseInline(` ${line.trim()}`))
    } else {
      flushList()
      paragraph.push(line.trim())
    }
  }
  flushParagraph()
  flushList()
  return blocks
}

/** Refs used in the text that exist in `sources`, in order of first use. Citation numbers follow this order. */
export function citedRefs(text: string, sources: Record<string, ChatSource>): string[] {
  const refs = [...text.matchAll(/\[([PF]\d+)\]/g)].map((m) => m[1]!)
  return [...new Set(refs)].filter((ref) => ref in sources)
}

/** Earlier assistant turns are sent back as plain text; their refs mean nothing to a new turn. */
export const stripRefs = (text: string) => text.replace(/\s*\[[PF]\d+\]/g, '')
