import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { ClaimWithPickup, Listing } from '../api/types'
import { ListingCard } from '../components/ListingCard'
import { CopyButton, EmptyState, ErrorNote, Spinner, formatDate } from '../components/ui'

export function MyListings(): JSX.Element {
  const [listings, setListings] = useState<Listing[]>([])
  const [claims, setClaims] = useState<ClaimWithPickup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [page, mine] = await Promise.all([
        api.listings.browse({ mine: true, limit: 60 }),
        api.claims.mine(),
      ])
      setListings(page.items)
      setClaims(mine)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load your listings.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => void load(), [load])

  if (loading) return <Spinner />

  return (
    <div className="space-y-8">
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">My listings</h1>
          <Link to="/listings/new" className="btn-primary">
            Give away something
          </Link>
        </div>
        {error !== null && <ErrorNote message={error} />}
        {listings.length === 0 ? (
          <EmptyState title="You have not listed anything yet" />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {listings.map((listing) => (
              <ListingCard key={listing.id} listing={listing} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-bold">Items I have claimed</h2>
        {claims.length === 0 ? (
          <EmptyState title="No claims yet" hint="Browse the board and claim something." />
        ) : (
          <ul className="space-y-3">
            {claims.map(({ claim, pickup }) => (
              <li key={claim.id} className="card space-y-2 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/listings/${claim.listing_id}`} className="font-medium hover:underline">
                    Listing #{claim.listing_id}
                  </Link>
                  <span className="badge bg-slate-100 text-slate-700">{claim.status}</span>
                  <span className="ml-auto text-xs text-slate-500">
                    {formatDate(claim.created_at)}
                  </span>
                </div>
                {pickup !== null && (
                  <div className="space-y-2 rounded-lg bg-emerald-50 p-3 text-sm">
                    <p>
                      Accepted by <strong>{pickup.owner_display_name}</strong> ·{' '}
                      <a className="text-maroon hover:underline" href={`mailto:${pickup.owner_email}`}>
                        {pickup.owner_email}
                      </a>
                    </p>
                    <p className="text-slate-600">📍 {pickup.pickup_area}</p>
                    {pickup.drafted_message !== null && (
                      <>
                        <p className="whitespace-pre-wrap rounded bg-white p-2 text-slate-700">
                          {pickup.drafted_message}
                        </p>
                        <CopyButton text={pickup.drafted_message} />
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
