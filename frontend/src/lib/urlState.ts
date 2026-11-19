import type { PaperSort } from '../api/types'

export type PageState = {
  q: string
  field: string | null
  sort: PaperSort | null // null = automatic: relevance when searching, otherwise date
  page: number
  fq: string
  fpage: number
}

export const INITIAL_STATE: PageState = { q: '', field: null, sort: null, page: 1, fq: '', fpage: 1 }

const SORTS: readonly PaperSort[] = ['date', 'citations', 'relevance']

/** API limits on `query` and `page` (papers and faculty). Larger values from an old link would get a 422. */
export const MAX_QUERY = 300
const MAX_PAGE = 100_000

function positiveInt(v: string | null): number {
  const n = Number(v)
  return Number.isInteger(n) && n >= 1 ? Math.min(n, MAX_PAGE) : 1
}

export function parseState(search: string): PageState {
  const p = new URLSearchParams(search)
  const sort = p.get('sort')
  return {
    q: (p.get('q') ?? '').slice(0, MAX_QUERY),
    field: p.get('field') || null,
    sort: SORTS.includes(sort as PaperSort) ? (sort as PaperSort) : null,
    page: positiveInt(p.get('page')),
    fq: (p.get('fq') ?? '').slice(0, MAX_QUERY),
    fpage: positiveInt(p.get('fpage')),
  }
}

/** Query string for the state, defaults omitted so a clean page has a clean URL. */
export function serializeState(s: PageState): string {
  const p = new URLSearchParams()
  if (s.q) p.set('q', s.q)
  if (s.field) p.set('field', s.field)
  if (s.sort) p.set('sort', s.sort)
  if (s.page > 1) p.set('page', String(s.page))
  if (s.fq) p.set('fq', s.fq)
  if (s.fpage > 1) p.set('fpage', String(s.fpage))
  const out = p.toString()
  return out ? `?${out}` : ''
}

/** Sort actually sent to the API. Relevance only exists with a search term. */
export function effectiveSort(s: Pick<PageState, 'q' | 'sort'>): PaperSort {
  if (s.sort === 'relevance' && !s.q) return 'date'
  return s.sort ?? (s.q ? 'relevance' : 'date')
}
