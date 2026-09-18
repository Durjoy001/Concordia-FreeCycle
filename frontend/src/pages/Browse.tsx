import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import { CATEGORIES, CATEGORY_LABELS } from '../api/types'
import type { Category, Listing } from '../api/types'
import { ListingCard } from '../components/ListingCard'
import { EmptyState, ErrorNote, Spinner } from '../components/ui'

const PAGE_SIZE = 24

function isCategory(value: string | null): value is Category {
  return value !== null && (CATEGORIES as readonly string[]).includes(value)
}

export function Browse(): JSX.Element {
  const [params, setParams] = useSearchParams()
  const category = isCategory(params.get('category')) ? (params.get('category') as Category) : null
  const search = params.get('search') ?? ''
  const offset = Number(params.get('offset') ?? '0')

  const [searchDraft, setSearchDraft] = useState(search)
  const [listings, setListings] = useState<Listing[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => setSearchDraft(search), [search])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    api.listings
      .browse({
        ...(category === null ? {} : { category }),
        ...(search === '' ? {} : { search }),
        limit: PAGE_SIZE,
        offset,
      })
      .then((page) => {
        if (!active) return
        setListings(page.items)
        setTotal(page.total)
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : 'Could not load listings.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [category, search, offset])

  const update = (changes: Record<string, string | null>): void => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    if (!('offset' in changes)) next.delete('offset')
    setParams(next)
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Free stuff near campus</h1>
        <p className="text-sm text-slate-500">
          {total} {total === 1 ? 'item' : 'items'} available right now.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <form
          className="flex flex-1 gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            update({ search: searchDraft })
          }}
        >
          <input
            className="field"
            type="search"
            placeholder="Search titles, descriptions, pickup areas…"
            aria-label="Search listings"
            value={searchDraft}
            onChange={(event) => setSearchDraft(event.target.value)}
          />
          <button type="submit" className="btn-secondary">
            Search
          </button>
        </form>

        <select
          className="field sm:w-48"
          aria-label="Filter by category"
          value={category ?? ''}
          onChange={(event) => update({ category: event.target.value })}
        >
          <option value="">All categories</option>
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {CATEGORY_LABELS[value]}
            </option>
          ))}
        </select>
      </div>

      {error !== null && <ErrorNote message={error} />}

      {loading ? (
        <Spinner />
      ) : listings.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          hint={
            search !== '' || category !== null
              ? 'Try a different search or category.'
              : 'Be the first to give something away.'
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {listings.map((listing) => (
            <ListingCard key={listing.id} listing={listing} />
          ))}
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3">
          <button
            type="button"
            className="btn-secondary"
            disabled={offset === 0}
            onClick={() => update({ offset: String(Math.max(0, offset - PAGE_SIZE)) })}
          >
            Previous
          </button>
          <span className="text-sm text-slate-500">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button
            type="button"
            className="btn-secondary"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => update({ offset: String(offset + PAGE_SIZE) })}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
