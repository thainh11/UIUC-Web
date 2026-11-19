import { ChatCircle, Envelope } from '@phosphor-icons/react'
import { useState } from 'react'
import { ApiError, getFacultyDetail } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt } from '../lib/format'
import { Avatar } from './Avatar'
import { Overlay } from './Overlay'
import { PaperRow } from './PaperRow'
import { ErrorBlock, Skeleton } from './states'

const KEYWORDS_SHOWN = 8

type Props = {
  facultyId: number | null
  onClose: () => void
  /** Close the drawer and ask the assistant about this person. */
  onAsk: (id: number, name: string) => void
  getReturnFocus: () => HTMLElement | null
}

export function FacultyDrawer({ facultyId, onClose, onAsk, getReturnFocus }: Props) {
  return (
    <Overlay
      open={facultyId !== null}
      onClose={onClose}
      title="Faculty profile"
      modal
      getReturnFocus={getReturnFocus}
      className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-[30rem] border-l"
    >
      {facultyId !== null && <DrawerBody key={facultyId} id={facultyId} onAsk={onAsk} />}
    </Overlay>
  )
}

function DrawerBody({ id, onAsk }: { id: number; onAsk: Props['onAsk'] }) {
  const { data, error, reload } = useResource((signal) => getFacultyDetail(id, signal), [id])
  const [allKeywords, setAllKeywords] = useState(false)

  if (error) {
    const missing = error instanceof ApiError && error.status === 404
    return (
      <div className="p-4">
        <ErrorBlock message={missing ? 'This profile is not available.' : 'Could not load this profile.'} onRetry={reload} />
      </div>
    )
  }
  if (!data) {
    return (
      <div aria-busy="true" className="p-4">
        <div className="flex gap-4">
          <Skeleton className="size-20 rounded-full" />
          <div className="flex-1">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="mt-2 h-4 w-full" />
          </div>
        </div>
        <Skeleton className="mt-6 h-24" />
      </div>
    )
  }

  const keywords = allKeywords ? data.keywords : data.keywords.slice(0, KEYWORDS_SHOWN)
  return (
    <div className="fade-in flex-1 overflow-y-auto p-4">
      <div className="flex items-start gap-4">
        <Avatar key={data.photo_url ?? data.id} name={data.name} url={data.photo_url} className="size-20 text-2xl" />
        <div className="min-w-0">
          <h3 className="text-primary m-0 font-serif text-2xl font-medium">{data.name}</h3>
          {data.position && <p className="text-muted-fg m-0">{data.position}</p>}
          <p className="m-0 mt-1">
            <a href={`mailto:${data.email}`} className="text-primary inline-flex items-center gap-1 break-all underline underline-offset-2">
              <Envelope size={20} aria-hidden="true" />
              {data.email}
            </a>
          </p>
        </div>
      </div>

      <button type="button" className="btn btn-primary mt-4" onClick={() => onAsk(data.id, data.name)}>
        <ChatCircle size={20} weight="fill" aria-hidden="true" />
        Ask the assistant about this person
      </button>

      {data.top_fields.length > 0 && (
        <section className="mt-6">
          <h4 className="text-muted-fg m-0 mb-2 text-sm font-bold">Main fields (from linked papers)</h4>
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {data.top_fields.map((t) => (
              <li key={t} className="border-border rounded-full border px-2 py-0.5 text-sm">
                {t}
              </li>
            ))}
          </ul>
        </section>
      )}

      {data.keywords.length > 0 && (
        <section className="mt-6">
          <h4 className="text-muted-fg m-0 mb-2 text-sm font-bold">Research keywords (self-listed)</h4>
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {keywords.map((k) => (
              <li key={k} className="bg-surface rounded-full px-2 py-0.5 text-sm">
                {k}
              </li>
            ))}
          </ul>
          {data.keywords.length > KEYWORDS_SHOWN && (
            <button type="button" className="btn mt-3 text-sm" aria-expanded={allKeywords} onClick={() => setAllKeywords((v) => !v)}>
              {allKeywords ? 'Show fewer' : `Show all ${formatInt(data.keywords.length)}`}
            </button>
          )}
        </section>
      )}

      <section className="mt-6">
        <h4 className="text-muted-fg m-0 text-sm font-bold">Linked papers ({formatInt(data.paper_count)})</h4>
        {data.papers.length === 0 ? (
          <p className="m-0 mt-2">No papers could be matched to this person in the last two years.</p>
        ) : (
          <>
            {data.paper_count > data.papers.length && (
              <p className="text-muted-fg m-0 mt-1 text-sm">Showing the {formatInt(data.papers.length)} most recent.</p>
            )}
            <ol className="divide-border m-0 list-none divide-y p-0">
              {data.papers.map((p) => (
                <PaperRow key={p.id} paper={p} />
              ))}
            </ol>
          </>
        )}
      </section>
    </div>
  )
}
