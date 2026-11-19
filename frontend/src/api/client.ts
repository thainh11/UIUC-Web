import type {
  FacultyDetail,
  FacultyPage,
  MonthCount,
  NameCount,
  Overview,
  PaperPage,
  PaperSort,
} from './types'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

type Params = Record<string, string | number | undefined | null>

export async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const url = qs.size ? `${path}?${qs}` : path
  let res: Response
  try {
    res = await fetch(url, { signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'Could not reach the server.')
  }
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? 'Not found.' : 'The server returned an error.')
  return (await res.json()) as T
}

export const PAPERS_PAGE_SIZE = 20
export const FACULTY_PAGE_SIZE = 24

export const getOverview = (signal?: AbortSignal) => get<Overview>('/api/overview', {}, signal)

export const getPublicationsByMonth = (signal?: AbortSignal) =>
  get<MonthCount[]>('/api/stats/publications-by-month', {}, signal)

export const getFields = (signal?: AbortSignal) =>
  get<NameCount[]>('/api/stats/topics', { level: 'field', limit: 30 }, signal)

export type PaperQuery = { query?: string; field?: string; sort: PaperSort; page: number }

export const getPapers = (q: PaperQuery, signal?: AbortSignal) =>
  get<PaperPage>(
    '/api/papers',
    { query: q.query, field: q.field, sort: q.sort, page: q.page, page_size: PAPERS_PAGE_SIZE },
    signal,
  )

export const getFaculty = (q: { query?: string; page: number }, signal?: AbortSignal) =>
  get<FacultyPage>('/api/faculty', { query: q.query, page: q.page, page_size: FACULTY_PAGE_SIZE }, signal)

export const getFacultyDetail = (id: number, signal?: AbortSignal) =>
  get<FacultyDetail>(`/api/faculty/${id}`, {}, signal)
