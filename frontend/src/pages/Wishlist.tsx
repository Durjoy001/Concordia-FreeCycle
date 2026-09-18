import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import { CATEGORIES, CATEGORY_LABELS } from '../api/types'
import type { WishlistItem } from '../api/types'
import { EmptyState, ErrorNote, Spinner, formatDate } from '../components/ui'

export function Wishlist(): JSX.Element {
  const [items, setItems] = useState<WishlistItem[]>([])
  const [keywords, setKeywords] = useState('')
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setItems(await api.wishlist.list())
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load your wishlist.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => void load(), [load])

  const add = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const item = await api.wishlist.add(keywords, category === '' ? null : category)
      setItems((current) => [item, ...current])
      setKeywords('')
      setCategory('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add that.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: number): Promise<void> => {
    const previous = items
    setItems((current) => current.filter((item) => item.id !== id))
    try {
      await api.wishlist.remove(id)
    } catch (caught) {
      setItems(previous)
      setError(caught instanceof Error ? caught.message : 'Could not remove that.')
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold">My wishlist</h1>
        <p className="text-sm text-slate-500">
          Describe what you are looking for in plain words. When someone lists something that
          fits, the matching assistant notifies you — “table for studying” will find a study desk.
        </p>
      </div>

      {error !== null && <ErrorNote message={error} />}

      <form onSubmit={(event) => void add(event)} className="card flex flex-col gap-3 p-4 sm:flex-row">
        <input
          className="field flex-1"
          placeholder="e.g. table for studying"
          aria-label="What are you looking for?"
          required
          minLength={2}
          maxLength={240}
          value={keywords}
          onChange={(event) => setKeywords(event.target.value)}
        />
        <select
          className="field sm:w-44"
          aria-label="Category (optional)"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="">Any category</option>
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {CATEGORY_LABELS[value]}
            </option>
          ))}
        </select>
        <button type="submit" className="btn-primary" disabled={busy}>
          Add
        </button>
      </form>

      {loading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <EmptyState title="Your wishlist is empty" hint="Add what you are hoping to find." />
      ) : (
        <ul className="card divide-y divide-slate-100">
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-3 p-3">
              <div className="flex-1">
                <p className="font-medium">{item.keywords}</p>
                <p className="text-xs text-slate-500">
                  {item.category === null ? 'Any category' : CATEGORY_LABELS[item.category]} ·
                  added {formatDate(item.created_at)}
                </p>
              </div>
              <button
                type="button"
                className="btn-secondary"
                aria-label={`Remove ${item.keywords}`}
                onClick={() => void remove(item.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
