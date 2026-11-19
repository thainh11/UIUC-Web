import { MagnifyingGlass } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { FACULTY_PAGE_SIZE, getFaculty } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt } from '../lib/format'
import { MAX_QUERY, type PageState } from '../lib/urlState'
import { Avatar } from './Avatar'
import { Pagination } from './Pagination'
import { EmptyState, ErrorBlock, Skeleton } from './states'

const DEBOUNCE_MS = 300

type Props = {
  state: Pick<PageState, 'fq' | 'fpage'>
  update: (patch: Partial<PageState>) => void
  onOpenFaculty: (id: number, opener: HTMLElement) => void
}

export function FacultySection({ state, update, onOpenFaculty }: Props) {
  const { fq, fpage } = state
  const [draft, setDraft] = useState(fq)
  const summaryRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (draft === fq) return
    const t = setTimeout(() => update({ fq: draft, fpage: 1 }), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [draft, fq, update])

  const { data, error, loading, reload } = useResource(
    (signal) => getFaculty({ query: fq || undefined, page: fpage }, signal),
    [fq, fpage],
  )

  const goToPage = (p: number) => {
    update({ fpage: p })
    requestAnimationFrame(() => summaryRef.current?.focus())
  }

  return (
    <div>
      <form
        role="search"
        className="max-w-xl"
        onSubmit={(e) => {
          e.preventDefault()
          update({ fq: draft, fpage: 1 })
        }}
      >
        <label className="block">
          <span className="text-muted-fg mb-1 block text-sm font-bold">Search by name or research keyword</span>
          <span className="relative block">
            <MagnifyingGlass size={20} aria-hidden="true" className="text-muted-fg pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" />
            <input
              type="search"
              value={draft}
              maxLength={MAX_QUERY}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="e.g. Jiawei Han, robotics"
              className="field pl-10"
            />
          </span>
        </label>
      </form>

      <p
        ref={summaryRef}
        tabIndex={-1}
        aria-live="polite"
        className="num text-primary mt-4 mb-3 scroll-mt-[calc(var(--header-h)+1rem)] font-bold outline-offset-4"
      >
        {data ? `${formatInt(data.total)} faculty${fq ? ` matching “${fq}”` : ''}` : 'Loading faculty'}
      </p>

      <div aria-busy={loading} className={loading && data ? 'opacity-60 transition-opacity' : ''}>
        {error ? (
          <ErrorBlock message="Could not load faculty." onRetry={reload} />
        ) : !data ? (
          <ul aria-hidden="true" className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <li key={i}>
                <Skeleton className="h-28" />
              </li>
            ))}
          </ul>
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No matches"
            hint="Try a surname or a single keyword."
            action={
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setDraft('')
                  update({ fq: '', fpage: 1 })
                }}
              >
                Clear search
              </button>
            }
          />
        ) : (
          <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  onClick={(e) => onOpenFaculty(f.id, e.currentTarget)}
                  className="card hover:bg-surface flex h-full w-full cursor-pointer items-start gap-3 p-4 text-left transition-colors"
                >
                  <Avatar key={f.photo_url ?? f.id} name={f.name} url={f.photo_url} />
                  <span className="min-w-0 flex-1">
                    <span className="text-primary block font-bold">{f.name}</span>
                    {f.position && <span className="text-muted-fg line-clamp-2 block text-sm">{f.position}</span>}
                    <span className="num text-muted-fg mt-1 block text-sm">
                      {f.paper_count > 0 ? `${formatInt(f.paper_count)} linked papers` : 'No linked papers yet'}
                    </span>
                    {f.top_fields.length > 0 && (
                      <span className="mt-2 flex flex-wrap gap-1">
                        {f.top_fields.map((t) => (
                          <span key={t} className="border-border rounded-full border px-2 text-xs">
                            {t}
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {data && (
        <Pagination label="Faculty pages" page={data.page} pageSize={FACULTY_PAGE_SIZE} total={data.total} onChange={goToPage} />
      )}
    </div>
  )
}
