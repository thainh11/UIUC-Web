import { ArrowSquareOut, LockOpen } from '@phosphor-icons/react'
import type { PaperSummary } from '../api/types'
import { formatDay, formatInt } from '../lib/format'

type Props = {
  paper: PaperSummary
  /** Omit where the faculty member is already the page's subject (the drawer). */
  onOpenFaculty?: (id: number, opener: HTMLElement) => void
}

export function PaperRow({ paper: p, onOpenFaculty }: Props) {
  const more = p.author_count - p.authors.length
  return (
    <li className="py-4">
      <p className="m-0 text-base leading-snug font-bold">
        {p.doi ? (
          <a href={p.doi} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">
            {p.title}
            <ArrowSquareOut size={16} aria-hidden="true" className="ml-1 inline align-[-2px]" />
            <span className="sr-only"> (opens in new tab)</span>
          </a>
        ) : (
          <span className="text-primary">{p.title}</span>
        )}
      </p>
      <p className="text-muted-fg m-0 mt-1 text-sm">
        {p.authors.join(', ')}
        {more > 0 && ` +${formatInt(more)} more`}
      </p>
      <p className="text-muted-fg num m-0 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <time dateTime={p.publication_date}>{formatDay(p.publication_date)}</time>
        {p.venue && <span>{p.venue}</span>}
        <span>Cited {formatInt(p.cited_by_count)}</span>
        {p.is_oa && (
          <span className="text-primary inline-flex items-center gap-1 rounded-full bg-[#dfe6f1] px-2 py-0.5 font-bold">
            <LockOpen size={16} aria-hidden="true" />
            Open access
          </span>
        )}
      </p>
      {(p.topic || p.faculty.length > 0) && (
        <p className="m-0 mt-2 flex flex-wrap items-center gap-2 text-sm">
          {p.topic && <span className="border-border rounded-full border px-2 py-0.5">{p.topic}</span>}
          {onOpenFaculty &&
            p.faculty.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={(e) => onOpenFaculty(f.id, e.currentTarget)}
                className="text-primary hover:bg-surface min-h-8 cursor-pointer rounded-full border border-current px-2 font-bold"
              >
                <span className="sr-only">UIUC faculty: </span>
                {f.name}
              </button>
            ))}
        </p>
      )}
    </li>
  )
}
