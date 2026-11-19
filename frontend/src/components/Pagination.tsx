import { CaretLeft, CaretRight } from '@phosphor-icons/react'
import { formatInt } from '../lib/format'

type Props = { label: string; page: number; pageSize: number; total: number; onChange: (page: number) => void }

export function Pagination({ label, page, pageSize, total, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages === 1) return null
  return (
    <nav aria-label={label} className="mt-6 flex items-center justify-between gap-3">
      <button type="button" className="btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <CaretLeft size={20} aria-hidden="true" />
        Previous
      </button>
      <span className="num text-muted-fg">
        Page {formatInt(page)} of {formatInt(pages)}
      </span>
      <button type="button" className="btn" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        Next
        <CaretRight size={20} aria-hidden="true" />
      </button>
    </nav>
  )
}
