/**
 * Typed fetch wrapper.
 *
 * Owns the whole auth story: it injects the bearer token, and when the API answers
 * 401 it refreshes once and replays the original request. Concurrent 401s share a
 * single refresh promise, so ten parallel requests cannot trigger ten refreshes.
 */

import type {
  AuthResponse,
  Claim,
  ClaimWithPickup,
  DraftedListing,
  Listing,
  ListingFilters,
  ListingFormValues,
  NotificationList,
  Page,
  TokenPair,
  UserMe,
  WishlistItem,
} from './types'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const ACCESS_KEY = 'freecycle.access_token'
const REFRESH_KEY = 'freecycle.refresh_token'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Raised when the session is gone and the user must sign in again. */
export class SessionExpiredError extends ApiError {
  constructor() {
    super(401, 'Your session has expired. Please sign in again.')
    this.name = 'SessionExpiredError'
  }
}

// --------------------------------------------------------------------- tokens

export const tokenStore = {
  get access(): string | null {
    return localStorage.getItem(ACCESS_KEY)
  },
  get refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY)
  },
  save(tokens: Pick<TokenPair, 'access_token' | 'refresh_token'>): void {
    localStorage.setItem(ACCESS_KEY, tokens.access_token)
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
  },
  clear(): void {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
  get isAuthenticated(): boolean {
    return this.access !== null
  },
}

type Listener = () => void
const sessionEndedListeners = new Set<Listener>()

/** Notifies the app (AuthProvider) that the session is gone. */
export function onSessionEnded(listener: Listener): () => void {
  sessionEndedListeners.add(listener)
  return () => sessionEndedListeners.delete(listener)
}

function endSession(): void {
  tokenStore.clear()
  sessionEndedListeners.forEach((listener) => listener())
}

// --------------------------------------------------------------------- errors

interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

function readDetail(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      // FastAPI validation errors: "field: message".
      return (detail as ValidationErrorItem[])
        .map((item) => {
          const field = item.loc.filter((part) => part !== 'body').join('.')
          return field ? `${field}: ${item.msg}` : item.msg
        })
        .join('; ')
    }
  }
  return `Request failed (${status}).`
}

async function toError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // A non-JSON error body is fine; the status still tells us enough.
  }
  return new ApiError(response.status, readDetail(body, response.status))
}

// --------------------------------------------------------------------- refresh

let refreshInFlight: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const refresh = tokenStore.refresh
  if (refresh === null) return false

  const response = await fetch(`${BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })
  if (!response.ok) return false

  tokenStore.save((await response.json()) as TokenPair)
  return true
}

function refreshOnce(): Promise<boolean> {
  // One shared promise, so parallel 401s cause exactly one refresh round-trip.
  refreshInFlight ??= refreshTokens().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

// --------------------------------------------------------------------- request

interface RequestOptions {
  method?: string
  body?: unknown
  /** Multipart body; set instead of `body`. Content-Type is left to the browser. */
  form?: FormData
  auth?: boolean
  query?: Record<string, string | number | boolean | undefined>
}

function buildUrl(path: string, query: RequestOptions['query']): string {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
  const headers: Record<string, string> = {}
  if (token !== null) headers.Authorization = `Bearer ${token}`

  let body: BodyInit | undefined
  if (options.form !== undefined) {
    body = options.form
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  return fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    ...(body === undefined ? {} : { body }),
  })
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const needsAuth = options.auth ?? true
  let response = await send(path, options, needsAuth ? tokenStore.access : null)

  if (response.status === 401 && needsAuth) {
    if (await refreshOnce()) {
      response = await send(path, options, tokenStore.access)
    } else {
      endSession()
      throw new SessionExpiredError()
    }
    if (response.status === 401) {
      endSession()
      throw new SessionExpiredError()
    }
  }

  if (!response.ok) throw await toError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

// --------------------------------------------------------------------- endpoints

export const api = {
  auth: {
    async register(displayName: string, email: string, password: string): Promise<AuthResponse> {
      const result = await request<AuthResponse>('/auth/register', {
        method: 'POST',
        auth: false,
        body: { display_name: displayName, email, password },
      })
      tokenStore.save(result.tokens)
      return result
    },
    async login(email: string, password: string): Promise<AuthResponse> {
      const result = await request<AuthResponse>('/auth/login', {
        method: 'POST',
        auth: false,
        body: { email, password },
      })
      tokenStore.save(result.tokens)
      return result
    },
    me(): Promise<UserMe> {
      return request<UserMe>('/auth/me')
    },
    logout(): void {
      tokenStore.clear()
    },
  },

  listings: {
    browse(filters: ListingFilters = {}): Promise<Page<Listing>> {
      return request<Page<Listing>>('/listings', {
        auth: tokenStore.isAuthenticated,
        query: {
          category: filters.category,
          status: filters.status,
          search: filters.search,
          mine: filters.mine,
          limit: filters.limit ?? 24,
          offset: filters.offset ?? 0,
        },
      })
    },
    get(id: number): Promise<Listing> {
      return request<Listing>(`/listings/${id}`, { auth: tokenStore.isAuthenticated })
    },
    create(
      values: ListingFormValues,
      options: { photos?: File[]; draftPhotoKeys?: string[]; aiGenerated?: boolean } = {},
    ): Promise<Listing> {
      const form = new FormData()
      form.set('title', values.title)
      form.set('description', values.description)
      form.set('category', values.category)
      form.set('condition', values.condition)
      form.set('pickup_area', values.pickup_area)
      form.set('ai_generated', String(options.aiGenerated ?? false))
      for (const photo of options.photos ?? []) form.append('photos', photo)
      for (const key of options.draftPhotoKeys ?? []) form.append('draft_photo_keys', key)
      return request<Listing>('/listings', { method: 'POST', form })
    },
    update(id: number, changes: Partial<ListingFormValues & { status: string }>): Promise<Listing> {
      return request<Listing>(`/listings/${id}`, { method: 'PATCH', body: changes })
    },
    remove(id: number): Promise<void> {
      return request<void>(`/listings/${id}`, { method: 'DELETE' })
    },
  },

  claims: {
    create(listingId: number, message: string): Promise<Claim> {
      return request<Claim>(`/listings/${listingId}/claims`, { method: 'POST', body: { message } })
    },
    forListing(listingId: number): Promise<Claim[]> {
      return request<Claim[]>(`/listings/${listingId}/claims`)
    },
    mine(): Promise<ClaimWithPickup[]> {
      return request<ClaimWithPickup[]>('/claims/mine')
    },
    act(
      claimId: number,
      action: 'accept' | 'decline' | 'cancel' | 'complete',
    ): Promise<ClaimWithPickup> {
      return request<ClaimWithPickup>(`/claims/${claimId}`, { method: 'PATCH', body: { action } })
    },
  },

  wishlist: {
    list(): Promise<WishlistItem[]> {
      return request<WishlistItem[]>('/wishlist')
    },
    add(keywords: string, category: string | null): Promise<WishlistItem> {
      return request<WishlistItem>('/wishlist', {
        method: 'POST',
        body: { keywords, category },
      })
    },
    remove(id: number): Promise<void> {
      return request<void>(`/wishlist/${id}`, { method: 'DELETE' })
    },
  },

  notifications: {
    list(): Promise<NotificationList> {
      return request<NotificationList>('/notifications', { query: { limit: 30 } })
    },
    markRead(id: number): Promise<Notification> {
      return request<Notification>(`/notifications/${id}/read`, { method: 'PATCH' })
    },
  },

  agent: {
    draftListing(photo: File): Promise<DraftedListing> {
      const form = new FormData()
      form.set('photo', photo)
      return request<DraftedListing>('/agent/draft-listing', { method: 'POST', form })
    },
  },
}

export type { Notification } from './types'
