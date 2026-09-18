/** Types mirroring the FastAPI schemas in backend/app/schemas. */

export const CATEGORIES = [
  'furniture',
  'books',
  'electronics',
  'kitchen',
  'clothing',
  'other',
] as const
export type Category = (typeof CATEGORIES)[number]

export const CONDITIONS = ['like_new', 'good', 'fair', 'worn'] as const
export type Condition = (typeof CONDITIONS)[number]

export type ListingStatus = 'available' | 'claimed' | 'completed' | 'removed'
export type ClaimStatus = 'pending' | 'accepted' | 'declined' | 'completed'
export type NotificationType = 'wishlist_match' | 'claim_received' | 'claim_accepted'

export const CATEGORY_LABELS: Record<Category, string> = {
  furniture: 'Furniture',
  books: 'Books',
  electronics: 'Electronics',
  kitchen: 'Kitchen',
  clothing: 'Clothing',
  other: 'Other',
}

export const CONDITION_LABELS: Record<Condition, string> = {
  like_new: 'Like new',
  good: 'Good',
  fair: 'Fair',
  worn: 'Worn',
}

export interface UserPublic {
  id: number
  display_name: string
}

export interface UserMe {
  id: number
  email: string
  display_name: string
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface AuthResponse {
  user: UserMe
  tokens: TokenPair
}

export interface Listing {
  id: number
  owner: UserPublic
  title: string
  description: string
  category: Category
  condition: Condition
  photos: string[]
  pickup_area: string
  status: ListingStatus
  ai_generated: boolean
  created_at: string
  updated_at: string
  claim_count: number
  /** Owner-only; null for everyone else. */
  flagged: boolean | null
  flag_reason: string | null
  is_owner: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Claim {
  id: number
  listing_id: number
  claimer: UserPublic
  message: string
  status: ClaimStatus
  created_at: string
  /** AI-drafted pickup message, present once the claim is accepted. */
  drafted_message: string | null
}

export interface PickupDetails {
  owner_display_name: string
  owner_email: string
  claimer_display_name: string
  pickup_area: string
  /** Null when the agent layer could not draft one. */
  drafted_message: string | null
}

export interface ClaimWithPickup {
  claim: Claim
  pickup: PickupDetails | null
}

export interface WishlistItem {
  id: number
  keywords: string
  category: Category | null
  created_at: string
}

export interface Notification {
  id: number
  type: NotificationType
  payload: Record<string, unknown>
  read: boolean
  created_at: string
}

export interface NotificationList {
  items: Notification[]
  unread_count: number
}

export interface DraftedListing {
  title: string
  description: string
  category: Category
  condition: Condition
  confidence: number
  photo_key: string
  flagged: boolean
  flag_reason: string | null
  summary: string
  tools_used: string[]
}

export interface ListingFormValues {
  title: string
  description: string
  category: Category
  condition: Condition
  pickup_area: string
}

export interface ListingFilters {
  category?: Category
  status?: ListingStatus
  search?: string
  mine?: boolean
  limit?: number
  offset?: number
}
