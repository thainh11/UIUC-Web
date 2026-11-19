import { MagnifyingGlass, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { getPapers, PAPERS_PAGE_SIZE } from '../api/client'
import { useResource } from '../hooks/useResource'
import { formatInt } from '../lib/format'
import { effectiveSort, MAX_QUERY, type PageState } from '../lib/urlState'
import { PaperRow } from './PaperRow'
import { Pagination } from './Pagination'
import { EmptyState, ErrorBlock, Skeleton } from './states'
import type { PaperSort } from '../api/types'

const DEBOUNCE_MS = 300

type Props = {
  state: Pick<PageState, 'q' | 'field' | 'sort' | 'page'>
  update: (patch: Partial<PageState>) => void
  onOpenFaculty: (id: number, opener: HTMLElement) => void
}

export function PapersSection({ state, update, onOpenFaculty }: Props) {
  const { q, field, page } = state
  const sort = effectiveSort(state)
  const [draft, setDraft] = useState(q)
  const summaryRef = useRef<HTMLParagraphElement>(null)

  // Commit the typed text after a pause; a new term always returns to page 1.
  useEffect(() => {
    if (draft === q) return
    const t = setTimeout(() => update({ q: draft, page: 1 }), DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [draft, q, update])

  const { data, error, loading, reload } = useResource(
    (signal) => getPapers({ query: q || undefined, field: field ?? undefined, sort, page }, signal),
    [q, field, sort, page],
  )

  const goToPage = (p: number) => {
    update({ page: p })
    requestAnimationFrame(() => summaryRef.current?.focus())
  }
  const clearFilters = () => {
    setDraft('')
    update({ q: '', field: null, sort: null, page: 1 })
  }

  const filtered = Boolean(q || field)
  const first = data ? (data.page - 1) * data.page_size + 1 : 0
  const summary = data
    ? data.total === 0
      ? 'No papers'
      : `${formatInt(data.total)} ${data.total === 1 ? 'paper' : 'papers'}` +
        (field ? ` in ${field}` : '') +
        (q ? ` matching “${q}”` : '') +
        (data.total > data.page_size ? `, showing ${formatInt(first)}–${formatInt(first + data.items.length - 1)}` : '')
    : 'Loading papers'

  return (
    <div>
      <form
        className="grid gap-3 sm:grid-cols-[1fr_auto]"
        role="search"
        onSubmit={(e) => {
          e.preventDefault()
          update({ q: draft, page: 1 })
        }}
      >
        <label className="block">
          <span className="text-muted-fg mb-1 block text-sm font-bold">Search titles and abstracts</span>
          <span className="relative block">
            <MagnifyingGlass size={20} aria-hidden="true" className="text-muted-fg pointer-events-none absolute top-1/2 left-3 -translate-y-1/2" />
            <input
              type="search"
              value={draft}
              maxLength={MAX_QUERY}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="e.g. protein folding"
              className="field pl-10"
            />
          </span>
        </label>
        <label className="block sm:w-48">
          <span className="text-muted-fg mb-1 block text-sm font-bold">Sort by</span>
          <select
            className="field"
            value={sort}
            onChange={(e) => update({ sort: e.target.value as PaperSort, page: 1 })}
          >
            <option value="date">Most recent</option>
            <option value="citations">Most cited</option>
            {q && <option value="relevance">Relevance</option>}
          </select>
        </label>
      </form>

      {field && (
        <p className="m-0 mt-3">
          <button type="button" className="btn text-sm" onClick={() => update({ field: null, page: 1 })}>
            Field: {field}
            <X size={16} aria-hidden="true" />
            <span className="sr-only">Remove field filter</span>
          </button>
        </p>
      )}

      <p
        id="papers-summary"
        ref={summaryRef}
        tabIndex={-1}
        aria-live="polite"
        className="num text-primary mt-4 mb-0 scroll-mt-[calc(var(--header-h)+1rem)] font-bold outline-offset-4"
      >
        {summary}
      </p>

      <div aria-busy={loading} className={loading && data ? 'opacity-60 transition-opacity' : ''}>
        {error ? (
          <ErrorBlock message="Could not load papers." onRetry={reload} />
        ) : !data ? (
          <ul className="m-0 list-none p-0" aria-hidden="true">
            {Array.from({ length: 5 }, (_, i) => (
              <li key={i} className="border-border border-t py-4">
                <Skeleton className="h-5 w-4/5" />
                <Skeleton className="mt-2 h-4 w-3/5" />
                <Skeleton className="mt-2 h-4 w-2/5" />
              </li>
            ))}
          </ul>
        ) : data.items.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              title="No matches"
              hint={q ? 'Try a shorter phrase or fewer words, or clear the filters.' : 'No papers in this field.'}
              action={
                filtered && (
                  <button type="button" className="btn" onClick={clearFilters}>
                    Clear filters
                  </button>
                )
              }
            />
          </div>
        ) : (
          <ol className="divide-border m-0 list-none divide-y p-0">
            {data.items.map((p) => (
              <PaperRow key={p.id} paper={p} onOpenFaculty={onOpenFaculty} />
            ))}
          </ol>
        )}
      </div>

      {data && (
        <Pagination label="Papers pages" page={data.page} pageSize={PAPERS_PAGE_SIZE} total={data.total} onChange={goToPage} />
      )}
    </div>
  )
}
