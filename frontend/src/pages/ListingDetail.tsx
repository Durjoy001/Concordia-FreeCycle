import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import type { Claim, Listing, PickupDetails } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import {
  AiBadge,
  CategoryBadge,
  ConditionBadge,
  CopyButton,
  ErrorNote,
  InfoNote,
  Spinner,
  StatusBadge,
  formatDate,
} from '../components/ui'

function PhotoCarousel({ photos, title }: { photos: string[]; title: string }): JSX.Element {
  const [index, setIndex] = useState(0)
  const current = photos[index]

  if (current === undefined) {
    return (
      <div className="flex aspect-[4/3] items-center justify-center rounded-xl bg-slate-100 text-5xl text-slate-300">
        <span aria-hidden>📦</span>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-xl bg-slate-100">
        <img src={current} alt={`${title} (${index + 1} of ${photos.length})`}
             className="aspect-[4/3] w-full object-contain" />
        {photos.length > 1 && (
          <>
            <button
              type="button"
              aria-label="Previous photo"
              className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 px-3 py-1 shadow"
              onClick={() => setIndex((value) => (value - 1 + photos.length) % photos.length)}
            >
              ‹
            </button>
            <button
              type="button"
              aria-label="Next photo"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 px-3 py-1 shadow"
              onClick={() => setIndex((value) => (value + 1) % photos.length)}
            >
              ›
            </button>
          </>
        )}
      </div>
      {photos.length > 1 && (
        <div className="flex gap-2 overflow-x-auto">
          {photos.map((photo, position) => (
            <button
              key={photo}
              type="button"
              aria-label={`Show photo ${position + 1}`}
              className={`h-16 w-16 shrink-0 overflow-hidden rounded-lg border-2 ${
                position === index ? 'border-maroon' : 'border-transparent'
              }`}
              onClick={() => setIndex(position)}
            >
              <img src={photo} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function ListingDetail(): JSX.Element {
  const { id } = useParams<{ id: string }>()
  const listingId = Number(id)
  const navigate = useNavigate()
  const { user } = useAuth()

  const [listing, setListing] = useState<Listing | null>(null)
  const [claims, setClaims] = useState<Claim[]>([])
  const [pickup, setPickup] = useState<PickupDetails | null>(null)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const fetched = await api.listings.get(listingId)
      setListing(fetched)
      if (fetched.is_owner) {
        setClaims(await api.claims.forListing(listingId))
      } else if (user !== null) {
        // A claimer reaches their own claim (and its pickup details) via /claims/mine.
        const mine = await api.claims.mine()
        const own = mine.find((entry) => entry.claim.listing_id === listingId)
        setPickup(own?.pickup ?? null)
      }
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 404
          ? 'This listing is no longer available.'
          : caught instanceof Error
            ? caught.message
            : 'Could not load this listing.',
      )
    } finally {
      setLoading(false)
    }
  }, [listingId, user])

  useEffect(() => void load(), [load])

  const claim = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    setBusy(true)
    setNotice(null)
    try {
      await api.claims.create(listingId, message)
      setMessage('')
      setNotice('Your claim has been sent. The owner will accept or decline it.')
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not send your claim.')
    } finally {
      setBusy(false)
    }
  }

  const act = async (claimId: number, action: 'accept' | 'decline'): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.claims.act(claimId, action)
      setPickup(result.pickup)
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not update the claim.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (): Promise<void> => {
    if (!window.confirm('Remove this listing? It will no longer be visible to others.')) return
    await api.listings.remove(listingId)
    navigate('/my-listings')
  }

  if (loading) return <Spinner />
  if (listing === null) {
    return (
      <div className="space-y-4">
        <ErrorNote message={error ?? 'Listing not found.'} />
        <Link to="/" className="btn-secondary">
          Back to browse
        </Link>
      </div>
    )
  }

  const pendingClaims = claims.filter((entry) => entry.status === 'pending')
  const acceptedClaim = claims.find((entry) => entry.status === 'accepted')
  // The draft is stored on the claim, so it is still here after a page reload; the
  // accept response is only a faster path to the same string.
  const draftedForOwner = acceptedClaim?.drafted_message ?? pickup?.drafted_message ?? null

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <PhotoCarousel photos={listing.photos} title={listing.title} />

      <div className="space-y-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-bold">{listing.title}</h1>
          <div className="flex flex-wrap gap-1">
            <CategoryBadge category={listing.category} />
            <ConditionBadge condition={listing.condition} />
            <StatusBadge status={listing.status} />
            {listing.ai_generated && <AiBadge />}
          </div>
          <p className="text-sm text-slate-500">
            Offered by {listing.owner.display_name} · {formatDate(listing.created_at)}
          </p>
        </div>

        {listing.flagged === true && (
          <InfoNote>
            <strong>This listing is hidden from other students.</strong>{' '}
            {listing.flag_reason ?? 'It was flagged by the moderation assistant.'} Edit it or
            remove it.
          </InfoNote>
        )}

        {listing.description !== '' && (
          <p className="whitespace-pre-wrap text-slate-700">{listing.description}</p>
        )}

        <p className="text-sm">
          <span className="font-medium">Pickup area:</span> {listing.pickup_area}
        </p>

        {error !== null && <ErrorNote message={error} />}
        {notice !== null && (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p>
        )}

        {/* --- claimer's view --- */}
        {!listing.is_owner && (
          <>
            {pickup !== null ? (
              <div className="card space-y-2 p-4">
                <h2 className="font-semibold">Your claim was accepted 🎉</h2>
                <p className="text-sm">
                  Contact {pickup.owner_display_name} at{' '}
                  <a className="text-maroon hover:underline" href={`mailto:${pickup.owner_email}`}>
                    {pickup.owner_email}
                  </a>
                </p>
                {pickup.drafted_message === null ? (
                  <p className="text-sm text-slate-500">
                    No drafted message available — write to them directly.
                  </p>
                ) : (
                  <>
                    <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm">
                      {pickup.drafted_message}
                    </p>
                    <CopyButton text={pickup.drafted_message} />
                  </>
                )}
              </div>
            ) : user === null ? (
              <Link to="/login" className="btn-primary">
                Sign in to claim
              </Link>
            ) : listing.status !== 'available' ? (
              <p className="text-sm text-slate-500">
                This item is no longer available to claim.
              </p>
            ) : (
              <form onSubmit={(event) => void claim(event)} className="card space-y-3 p-4">
                <h2 className="font-semibold">Claim this item</h2>
                <textarea
                  className="field min-h-20"
                  maxLength={1000}
                  placeholder="Say hello and suggest when you could pick it up."
                  aria-label="Message to the owner"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                />
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy ? 'Sending…' : 'Claim it'}
                </button>
              </form>
            )}
          </>
        )}

        {/* --- owner's view --- */}
        {listing.is_owner && (
          <div className="space-y-4">
            <div className="flex gap-2">
              <button type="button" className="btn-secondary" onClick={() => void remove()}>
                Remove listing
              </button>
            </div>

            {acceptedClaim !== undefined && (
              <div className="card space-y-2 p-4">
                <h2 className="font-semibold">
                  Accepted: {acceptedClaim.claimer.display_name}
                </h2>
                {draftedForOwner === null ? (
                  <p className="text-sm text-slate-500">
                    No drafted pickup message is available — message them yourself.
                  </p>
                ) : (
                  <>
                    <p className="text-sm text-slate-500">
                      ✨ Drafted for you — edit it however you like.
                    </p>
                    <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm">
                      {draftedForOwner}
                    </p>
                    <CopyButton text={draftedForOwner} />
                  </>
                )}
              </div>
            )}

            <div className="card p-4">
              <h2 className="mb-2 font-semibold">
                Pending claims ({pendingClaims.length})
              </h2>
              {pendingClaims.length === 0 ? (
                <p className="text-sm text-slate-500">Nobody has claimed this yet.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {pendingClaims.map((entry) => (
                    <li key={entry.id} className="space-y-2 py-3">
                      <p className="font-medium">{entry.claimer.display_name}</p>
                      {entry.message !== '' && (
                        <p className="whitespace-pre-wrap text-sm text-slate-600">
                          “{entry.message}”
                        </p>
                      )}
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="btn-primary"
                          disabled={busy}
                          onClick={() => void act(entry.id, 'accept')}
                        >
                          Accept
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          disabled={busy}
                          onClick={() => void act(entry.id, 'decline')}
                        >
                          Decline
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
