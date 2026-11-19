import { describe, expect, it } from 'vitest'
import { initials, realPhotoUrl, toChartPoints, trendSummary } from './format'
import { effectiveSort, parseState, serializeState } from './urlState'

const months = [
  { month: '2024-11', count: 120, year_only: 0 },
  { month: '2024-12', count: 800, year_only: 0 },
  { month: '2025-01', count: 900, year_only: 0 },
  { month: '2025-02', count: 850, year_only: 0 },
  { month: '2025-03', count: 40, year_only: 0 },
]

describe('toChartPoints', () => {
  const pts = toChartPoints(months)

  it('marks only the first and last months as partial', () => {
    expect(pts.map((p) => p.partial)).toEqual([true, false, false, false, true])
  })

  it('splits the line so each partial month is joined to its neighbour by a dashed segment', () => {
    expect(pts.map((p) => p.dashStart)).toEqual([120, 800, null, null, null])
    expect(pts.map((p) => p.dashEnd)).toEqual([null, null, null, 850, 40])
    expect(pts.map((p) => p.solid)).toEqual([null, 800, 900, 850, null])
  })
})

describe('trendSummary', () => {
  it('ignores the partial months when naming the lowest month', () => {
    expect(trendSummary(months)).toContain('Lowest: Dec 2024 (800)')
    expect(trendSummary(months)).toContain('Highest full month: Jan 2025 (900)')
  })
})

describe('year-only dates', () => {
  // 600 of January's 900 papers only carry a year: the month really has 300.
  const withYearOnly = months.map((m) => (m.month === '2025-01' ? { ...m, year_only: 600 } : m))

  it('are left off the line', () => {
    const jan = toChartPoints(withYearOnly)[2]!
    expect([jan.count, jan.solid, jan.yearOnly]).toEqual([300, 300, 600])
  })

  it('do not make January the busiest month, and the summary says they are not plotted', () => {
    const summary = trendSummary(withYearOnly)
    expect(summary).toContain('Highest full month: Feb 2025 (850)')
    expect(summary).toContain('Lowest: Jan 2025 (300)')
    expect(summary).toContain('600 papers with only a publication year are not plotted.')
  })
})

describe('url state', () => {
  it('round-trips and keeps a default page URL clean', () => {
    const s = parseState('?q=deep+learning&field=Computer+Science&sort=citations&page=3&fq=han&fpage=2')
    expect(s).toEqual({ q: 'deep learning', field: 'Computer Science', sort: 'citations', page: 3, fq: 'han', fpage: 2 })
    expect(parseState(serializeState(s))).toEqual(s)
    expect(serializeState(parseState(''))).toBe('')
  })

  it('rejects hostile or malformed params instead of passing them to the API', () => {
    const s = parseState('?sort=drop+table&page=-4&fpage=abc')
    expect(s.sort).toBeNull()
    expect(s.page).toBe(1)
    expect(s.fpage).toBe(1)
  })

  it('clamps a long query and a huge page from an old link to what the API accepts', () => {
    const s = parseState(`?q=${'a'.repeat(400)}&page=999999&fq=${'b'.repeat(301)}&fpage=100001`)
    expect([s.q.length, s.page, s.fq.length, s.fpage]).toEqual([300, 100_000, 300, 100_000])
  })

  it('only offers relevance when there is a search term', () => {
    expect(effectiveSort({ q: '', sort: 'relevance' })).toBe('date')
    expect(effectiveSort({ q: 'x', sort: null })).toBe('relevance')
    expect(effectiveSort({ q: 'x', sort: 'citations' })).toBe('citations')
    expect(effectiveSort({ q: '', sort: null })).toBe('date')
  })
})

describe('faculty avatar helpers', () => {
  it('uses first and last name initials, skipping punctuation', () => {
    expect(initials('Jiawei Han')).toBe('JH')
    expect(initials('Madonna')).toBe('M')
    expect(initials('Maria  del Carmen, Lopez')).toBe('ML')
    expect(initials('')).toBe('?')
  })

  it('treats the Experts "no portrait" image as no photo', () => {
    expect(realPhotoUrl('https://experts.illinois.edu/assets/no-portrait-473c.png')).toBeNull()
    expect(realPhotoUrl(null)).toBeNull()
    expect(realPhotoUrl('https://media.academic.online/faculty_images/x.jpg')).not.toBeNull()
  })
})
