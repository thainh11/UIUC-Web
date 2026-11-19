import { ArrowClockwise } from '@phosphor-icons/react'
import type { ReactNode } from 'react'

export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="card flex flex-wrap items-center justify-between gap-3 border-error/40 p-4">
      <p className="text-error m-0 font-bold">{message}</p>
      <button type="button" className="btn" onClick={onRetry}>
        <ArrowClockwise size={20} aria-hidden="true" />
        Try again
      </button>
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint: string; action?: ReactNode }) {
  return (
    <div className="card bg-surface flex flex-col items-start gap-2 p-6">
      <p className="text-primary m-0 text-lg font-bold">{title}</p>
      <p className="text-muted-fg m-0">{hint}</p>
      {action}
    </div>
  )
}
