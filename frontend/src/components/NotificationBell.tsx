import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { Notification } from '../api/types'
import { formatDate } from './ui'

const POLL_INTERVAL_MS = 30_000

function describe(notification: Notification): { text: string; listingId: number | null } {
  const payload = notification.payload
  const title = typeof payload.listing_title === 'string' ? payload.listing_title : 'a listing'
  const listingId = typeof payload.listing_id === 'number' ? payload.listing_id : null

  switch (notification.type) {
    case 'wishlist_match': {
      const rationale = typeof payload.rationale === 'string' ? payload.rationale : ''
      const score = typeof payload.score === 'number' ? Math.round(payload.score * 100) : null
      return {
        text: `“${title}” matches your wishlist${score === null ? '' : ` (${score}%)`}. ${rationale}`,
        listingId,
      }
    }
    case 'claim_received': {
      const who = typeof payload.claimer_display_name === 'string' ? payload.claimer_display_name : 'Someone'
      return { text: `${who} wants “${title}”.`, listingId }
    }
    case 'claim_accepted': {
      const who = typeof payload.owner_display_name === 'string' ? payload.owner_display_name : 'The owner'
      const area = typeof payload.pickup_area === 'string' ? payload.pickup_area : ''
      return { text: `${who} accepted your claim on “${title}”. Pickup: ${area}`, listingId }
    }
    default:
      return { text: 'You have a new notification.', listingId }
  }
}

export function NotificationBell(): JSX.Element {
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      const result = await api.notifications.list()
      setItems(result.items)
      setUnread(result.unread_count)
    } catch {
      // A failed poll is not worth interrupting the page for; the next tick retries.
    }
  }, [])

  // Polling every 30s, as specified - no websockets in v1.
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => {
    if (!open) return
    const onClickOutside = (event: MouseEvent): void => {
      if (containerRef.current !== null && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  const markRead = async (id: number): Promise<void> => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, read: true } : item)),
    )
    setUnread((count) => Math.max(0, count - 1))
    try {
      await api.notifications.markRead(id)
    } catch {
      void load() // put the real state back if the write failed
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        className="btn-secondary relative"
        aria-label={`Notifications${unread > 0 ? `, ${unread} unread` : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden>🔔</span>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-maroon px-1 text-xs font-semibold text-white">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 max-h-96 w-80 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 shadow-lg sm:w-96">
          {items.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-slate-500">Nothing yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {items.map((notification) => {
                const { text, listingId } = describe(notification)
                return (
                  <li
                    key={notification.id}
                    className={`p-2 text-sm ${notification.read ? 'opacity-60' : ''}`}
                  >
                    <p className="text-slate-700">{text}</p>
                    <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                      <span>{formatDate(notification.created_at)}</span>
                      {listingId !== null && (
                        <Link
                          to={`/listings/${listingId}`}
                          className="text-maroon hover:underline"
                          onClick={() => setOpen(false)}
                        >
                          View
                        </Link>
                      )}
                      {!notification.read && (
                        <button
                          type="button"
                          className="hover:underline"
                          onClick={() => void markRead(notification.id)}
                        >
                          Mark read
                        </button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
