import { ArrowSquareOut, PaperPlaneRight, Stop, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState, type RefObject } from 'react'
import { streamChat } from '../api/chat'
import type { ChatEvent, ChatSource } from '../api/types'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { citedRefs, parseAnswer, stripRefs, type Inline } from '../lib/answer'
import { knownRecords, loadChat, saveChat, type ChatMessage, type PageContext } from '../lib/chatStore'
import { formatDay } from '../lib/format'
import { Overlay } from './Overlay'

const SAMPLES = [
  'What are the most recent UIUC papers on AI in war conflict?',
  'Which faculty members work on Computer Vision in Healthcare?',
]

const samplesFor = (context: PageContext | null) =>
  context ? [`What has ${context.name} published recently?`, `What are ${context.name}’s main research topics?`] : SAMPLES

type Message = ChatMessage

type Props = {
  open: boolean
  onClose: () => void
  /** The profile the user asked from; sent with every question until they remove it. */
  context: PageContext | null
  onContextChange: (context: PageContext | null) => void
  onOpenFaculty: (id: number) => void
  getReturnFocus: () => HTMLElement | null
}

export function ChatPanel({ open, onClose, context, onContextChange, onOpenFaculty, getReturnFocus }: Props) {
  // Wide screens: a side panel next to the page, which stays usable. Narrow: a full-screen modal.
  const wide = useMediaQuery('(min-width: 64rem)')
  const [restored] = useState(loadChat)
  const [messages, setMessages] = useState<Message[]>(restored.messages)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const nextId = useRef(Math.max(0, ...restored.messages.map((m) => m.id)) + 1)

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [messages, pending])
  // Kept for a reload of this tab. Not while an answer streams: it would rewrite storage on every word.
  useEffect(() => {
    if (!pending) saveChat(messages, context)
  }, [messages, context, pending])

  const ask = async (text: string, echo = true) => {
    const q = text.trim()
    if (!q || pending) return
    // On a retry the question is already in the log; it is the message being sent, not history.
    const earlier = echo ? messages : messages.slice(0, messages.findLastIndex((m) => m.role === 'user'))
    const recent = earlier.filter((m) => m.role !== 'error' && m.text.trim()).slice(-8)
    const known = knownRecords(recent)
    const history = recent.map((m) => ({ role: m.role === 'user' ? ('user' as const) : ('assistant' as const), content: m.role === 'user' ? m.text : stripRefs(m.text) }))
    const answerId = nextId.current++
    setMessages((m) => [
      ...m.filter((x) => x.role !== 'error'),
      ...(echo ? [{ id: nextId.current++, role: 'user' as const, text: q }] : []),
      { id: answerId, role: 'assistant', text: '', sources: {}, status: 'Thinking…', streaming: true },
    ])
    setDraft('')
    setPending(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl

    const patch = (fn: (a: Extract<Message, { role: 'assistant' }>) => Partial<Extract<Message, { role: 'assistant' }>>) =>
      setMessages((all) => all.map((x) => (x.id === answerId && x.role === 'assistant' ? { ...x, ...fn(x) } : x)))
    const fail = (message: string) =>
      setMessages((all) => [
        ...all.filter((x) => x.id !== answerId),
        { id: nextId.current++, role: 'error', text: `${message} Your question was not answered.`, retry: q },
      ])
    let failed = false
    const onEvent = (event: ChatEvent) => {
      if (event.type === 'status') patch(() => ({ status: event.text }))
      else if (event.type === 'sources')
        patch((a) => ({ sources: { ...a.sources, ...Object.fromEntries(event.sources.map((src) => [src.ref, src])) } }))
      else if (event.type === 'delta') patch((a) => ({ text: a.text + event.text, status: null }))
      else if (event.type === 'reset') patch(() => ({ text: '' }))
      else if (event.type === 'done') patch(() => ({ status: null, streaming: false }))
      else if (event.type === 'error') {
        failed = true
        fail(event.message)
      }
    }
    try {
      await streamChat(q, history, { context: context ? { kind: context.kind, id: context.id } : undefined, known }, onEvent, ctrl.signal)
      if (!failed) patch(() => ({ status: null, streaming: false }))
    } catch (e) {
      if (ctrl.signal.aborted) {
        patch(() => ({ status: null, streaming: false }))
        return
      }
      fail(e instanceof Error && e.message ? e.message : 'Something went wrong.')
    } finally {
      if (abortRef.current === ctrl) {
        abortRef.current = null
        setPending(false)
      }
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    abortRef.current = null
    setPending(false)
  }

  const newChat = () => {
    stop()
    setMessages([])
    setDraft('')
    onContextChange(null)
  }

  const citation = (ref: string, number: number, sources: Record<string, ChatSource>) => {
    const src = sources[ref]
    if (!src) return null
    const cls = 'text-primary font-bold underline underline-offset-2'
    const label = `${src.label}${src.kind === 'faculty' ? ' (faculty)' : ''}`
    if (src.kind === 'faculty')
      return (
        <button type="button" className={`${cls} cursor-pointer`} aria-label={label} title={label} onClick={() => onOpenFaculty(src.facultyId)}>
          [{number}]
        </button>
      )
    return src.doi ? (
      <a href={src.doi} target="_blank" rel="noopener noreferrer" className={cls} aria-label={`${label} (opens in new tab)`} title={label}>
        [{number}]
      </a>
    ) : (
      <span className={cls} title={label}>
        [{number}]
      </span>
    )
  }

  const inline = (parts: Inline[], order: string[], sources: Record<string, ChatSource>) =>
    parts.map((part, i) =>
      part.type === 'bold' ? (
        <strong key={i}>{part.text}</strong>
      ) : part.type === 'italic' ? (
        <em key={i}>{part.text}</em>
      ) : part.type === 'ref' ? (
        <span key={i}>{citation(part.ref, order.indexOf(part.ref) + 1, sources)}</span>
      ) : (
        part.text
      ),
    )

  return (
    <Overlay
      open={open}
      onClose={onClose}
      title="Assistant"
      modal={!wide}
      initialFocus={inputRef as RefObject<HTMLElement | null>}
      getReturnFocus={getReturnFocus}
      className="fixed inset-0 m-0 h-dvh max-h-none w-full max-w-none lg:inset-auto lg:right-6 lg:bottom-24 lg:h-[min(40rem,calc(100dvh-11rem))] lg:w-[380px] lg:rounded-xl lg:border"
    >
      <div className="border-border flex items-center justify-between gap-3 border-b px-4 py-2">
        <p className="text-muted-fg m-0 text-sm">Searches UIUC papers from the last two years and the faculty directory.</p>
        {(messages.length > 0 || context) && (
          <button type="button" className="btn shrink-0 text-sm" onClick={newChat}>
            New chat
          </button>
        )}
      </div>

      <div ref={logRef} role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div>
            <p className="m-0 mb-3">Try a question:</p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {samplesFor(context).map((s) => (
                <li key={s}>
                  <button type="button" className="btn h-auto w-full justify-start py-2 text-left font-normal" onClick={() => ask(s)}>
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {messages.map((m) =>
          m.role === 'user' ? (
            <p key={m.id} className="bg-primary text-primary-fg m-0 ml-8 rounded-xl rounded-br-sm px-3 py-2">
              <span className="sr-only">You: </span>
              {m.text}
            </p>
          ) : m.role === 'error' ? (
            <div key={m.id} className="border-error/40 mr-8 rounded-xl border p-3">
              <p className="text-error m-0 font-bold">{m.text}</p>
              <button type="button" className="btn mt-2" disabled={pending} onClick={() => ask(m.retry, false)}>
                Try again
              </button>
            </div>
          ) : (
            <div key={m.id} className="bg-surface mr-8 rounded-xl rounded-bl-sm px-3 py-2">
              <span className="sr-only">Assistant: </span>
              {(() => {
                const order = citedRefs(m.text, m.sources)
                return (
                  <>
                    <div className="max-w-prose space-y-2">
                      {parseAnswer(m.text, m.streaming).map((block, i) =>
                        block.type === 'p' ? (
                          <p key={i} className="m-0">
                            {inline(block.inline, order, m.sources)}
                          </p>
                        ) : (
                          <ul key={i} className="m-0 list-disc space-y-1 pl-5">
                            {block.items.map((item, k) => (
                              <li key={k}>{inline(item, order, m.sources)}</li>
                            ))}
                          </ul>
                        ),
                      )}
                    </div>
                    {m.status && <p className="text-muted-fg m-0 text-sm">{m.status}</p>}
                    {!m.streaming && order.length > 0 && (
                      <ol className="m-0 mt-2 list-none space-y-2 p-0 text-sm">
                        {order.map((ref, n) => {
                          const src = m.sources[ref]!
                          return (
                            <li key={ref} className="flex gap-2">
                              <span className="text-muted-fg num">[{n + 1}]</span>
                              <span>
                                {src.kind === 'faculty' ? (
                                  <button type="button" className="text-primary cursor-pointer text-left font-bold underline underline-offset-2" onClick={() => onOpenFaculty(src.facultyId)}>
                                    {src.label} <span className="text-muted-fg font-normal no-underline">(faculty)</span>
                                  </button>
                                ) : src.doi ? (
                                  <a href={src.doi} target="_blank" rel="noopener noreferrer" className="text-primary font-bold underline underline-offset-2">
                                    {src.label}
                                    <ArrowSquareOut size={16} aria-hidden="true" className="ml-1 inline align-[-2px]" />
                                    <span className="sr-only"> (opens in new tab)</span>
                                  </a>
                                ) : (
                                  <span className="text-primary font-bold">{src.label}</span>
                                )}
                                {src.kind === 'paper' && <span className="text-muted-fg num block">{formatDay(src.date)}</span>}
                              </span>
                            </li>
                          )
                        })}
                      </ol>
                    )}
                  </>
                )
              })()}
            </div>
          ),
        )}

        {pending && (
          <p role="status" className="text-muted-fg m-0 flex items-center justify-between gap-3">
            <span>Working on your question…</span>
            <button type="button" className="btn" onClick={stop}>
              <Stop size={20} aria-hidden="true" />
              Stop
            </button>
          </p>
        )}
      </div>

      {context && (
        <p className="bg-surface border-border m-0 flex items-center justify-between gap-2 border-t px-4 py-1 text-sm">
          <span>
            Asking about <strong>{context.name}</strong>
          </span>
          <button type="button" className="btn size-8 p-0" aria-label={`Stop asking about ${context.name}`} onClick={() => onContextChange(null)}>
            <X size={16} aria-hidden="true" />
          </button>
        </p>
      )}

      <form
        className="border-border flex items-end gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(draft)
        }}
      >
        <label className="flex-1">
          <span className="sr-only">Ask about UIUC research</span>
          <textarea
            ref={inputRef}
            rows={2}
            value={draft}
            placeholder="Ask about papers or faculty"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                void ask(draft)
              }
            }}
            className="field block resize-none py-2"
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={pending || !draft.trim()}>
          <PaperPlaneRight size={20} aria-hidden="true" />
          Send
        </button>
      </form>
    </Overlay>
  )
}
