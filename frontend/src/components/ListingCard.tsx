import { Link } from 'react-router-dom'

import type { Listing } from '../api/types'
import { AiBadge, CategoryBadge, StatusBadge } from './ui'

export function ListingCard({ listing }: { listing: Listing }): JSX.Element {
  const photo = listing.photos[0]

  return (
    <Link
      to={`/listings/${listing.id}`}
      className="card group flex flex-col overflow-hidden transition hover:shadow-md"
    >
      <div className="aspect-[4/3] w-full overflow-hidden bg-slate-100">
        {photo === undefined ? (
          <div className="flex h-full items-center justify-center text-4xl text-slate-300" aria-hidden>
            📦
          </div>
        ) : (
          <img
            src={photo}
            alt={listing.title}
            loading="lazy"
            className="h-full w-full object-cover transition group-hover:scale-[1.02]"
          />
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-3">
        <h3 className="line-clamp-2 font-semibold leading-snug">{listing.title}</h3>
        <div className="flex flex-wrap gap-1">
          <CategoryBadge category={listing.category} />
          <StatusBadge status={listing.status} />
          {listing.ai_generated && <AiBadge />}
        </div>
        <p className="mt-auto truncate text-sm text-slate-500" title={listing.pickup_area}>
          📍 {listing.pickup_area}
        </p>
        {listing.flagged === true && (
          <p className="rounded bg-red-50 px-2 py-1 text-xs text-red-700">
            Hidden from others: {listing.flag_reason}
          </p>
        )}
      </div>
    </Link>
  )
}
