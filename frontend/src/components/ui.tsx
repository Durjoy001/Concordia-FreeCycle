/** Small presentational pieces shared across pages. */

import type { ReactNode } from 'react'

import { CATEGORY_LABELS, CONDITION_LABELS } from '../api/types'
import type { Category, Condition, ListingStatus } from '../api/types'

export function Spinner({ label = 'Loading…' }: { label?: string }): JSX.Element {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-maroon"
        aria-hidden
      />
      {label}
    </div>
  )
}

export function ErrorNote({ message }: { message: string }): JSX.Element {
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </p>
  )
}

export function InfoNote({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{children}</div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }): JSX.Element {
  return (
    <div className="card p-10 text-center">
      <p className="font-medium text-slate-700">{title}</p>
      {hint !== undefined && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    </div>
  )
}

export function CategoryBadge({ category }: { category: Category }): JSX.Element {
  return <span className="badge bg-slate-100 text-slate-700">{CATEGORY_LABELS[category]}</span>
}

export function ConditionBadge({ condition }: { condition: Condition }): JSX.Element {
  return (
    <span className="badge bg-slate-100 text-slate-600">{CONDITION_LABELS[condition]}</span>
  )
}

const STATUS_STYLES: Record<ListingStatus, string> = {
  available: 'bg-emerald-100 text-emerald-800',
  claimed: 'bg-amber-100 text-amber-800',
  completed: 'bg-slate-200 text-slate-700',
  removed: 'bg-slate-200 text-slate-500',
}

export function StatusBadge({ status }: { status: ListingStatus }): JSX.Element {
  return <span className={`badge ${STATUS_STYLES[status]}`}>{status}</span>
}

export function AiBadge({ confidence }: { confidence?: number }): JSX.Element {
  return (
    <span
      className="badge bg-violet-100 text-violet-800"
      title="These fields were drafted by the AI assistant from your photo."
    >
      ✨ AI-drafted
      {confidence !== undefined && ` · ${Math.round(confidence * 100)}% confident`}
    </span>
  )
}

export function CopyButton({ text }: { text: string }): JSX.Element {
  return (
    <button
      type="button"
      className="btn-secondary"
      onClick={() => {
        void navigator.clipboard?.writeText(text)
      }}
    >
      Copy message
    </button>
  )
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}
