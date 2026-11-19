import type { components } from './schema'

// Generated from the FastAPI OpenAPI document (`npm run gen:api`). Names and snake_case match the backend.
type S = components['schemas']

export type Overview = S['Overview']
export type MonthCount = S['MonthCount']
export type NameCount = S['NameCount']
export type PaperSummary = S['PaperSummary']
export type PaperPage = S['PaperPage']
export type FacultySummary = S['FacultySummary']
export type FacultyPage = S['FacultyPage']
export type FacultyDetail = S['FacultyDetail']
export type FacultyRef = S['FacultyRef']

export type PaperSort = 'date' | 'citations' | 'relevance'

// `POST /api/chat` streams server-sent events, which OpenAPI cannot describe, so these are hand-written to match
// backend/agent/agent.py. A source is a record the model was shown; the answer cites it as `[ref]`.
export type ChatSource =
  | { ref: string; kind: 'paper'; label: string; date: string; doi: string | null; paperId: string }
  | { ref: string; kind: 'faculty'; label: string; facultyId: number }

export type ChatEvent =
  | { type: 'status'; tool: string; text: string }
  | { type: 'sources'; sources: ChatSource[] }
  | { type: 'delta'; text: string }
  | { type: 'reset' }
  | { type: 'done'; cited: string[] }
  | { type: 'error'; message: string }

export type ChatHistoryTurn = { role: 'user' | 'assistant'; content: string }
/** The profile the page is showing, and records cited earlier in the conversation: names only, the server looks them up. */
export type ChatContext = { kind: 'faculty'; id: number }
export type ChatKnown = { kind: 'paper' | 'faculty'; id: string }
