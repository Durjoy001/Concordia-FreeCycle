import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError, api } from '../api/client'
import { CATEGORIES, CATEGORY_LABELS, CONDITIONS, CONDITION_LABELS } from '../api/types'
import type { Category, Condition, DraftedListing, ListingFormValues } from '../api/types'
import { AiBadge, ErrorNote, InfoNote } from '../components/ui'

const EMPTY: ListingFormValues = {
  title: '',
  description: '',
  category: 'other',
  condition: 'good',
  pickup_area: '',
}

export function CreateListing(): JSX.Element {
  const navigate = useNavigate()
  const [values, setValues] = useState<ListingFormValues>(EMPTY)
  const [photo, setPhoto] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [drafted, setDrafted] = useState<DraftedListing | null>(null)
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof ListingFormValues>(key: K, value: ListingFormValues[K]): void => {
    setValues((current) => ({ ...current, [key]: value }))
  }

  const onPickPhoto = (file: File | null): void => {
    setPhoto(file)
    setDrafted(null)
    setDraftError(null)
    setPreviewUrl((old) => {
      if (old !== null) URL.revokeObjectURL(old)
      return file === null ? null : URL.createObjectURL(file)
    })
  }

  /** Path (a): ask the agent to fill the form in from the photo. */
  const autoFill = async (): Promise<void> => {
    if (photo === null) return
    setDrafting(true)
    setDraftError(null)
    try {
      const result = await api.agent.draftListing(photo)
      setDrafted(result)
      setValues((current) => ({
        ...current,
        title: result.title,
        description: result.description,
        category: result.category,
        condition: result.condition,
      }))
    } catch (caught) {
      // Degradation: the manual form below still works exactly as before.
      const message =
        caught instanceof ApiError && caught.status === 503
          ? 'The AI assistant is unavailable right now — fill the form in manually below.'
          : caught instanceof Error
            ? caught.message
            : 'Auto-fill failed.'
      setDraftError(message)
    } finally {
      setDrafting(false)
    }
  }

  const onSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      // If the agent drafted from this photo, reuse the stored upload rather than
      // sending the same bytes a second time.
      const listing =
        drafted === null
          ? await api.listings.create(values, {
              ...(photo === null ? {} : { photos: [photo] }),
            })
          : await api.listings.create(values, {
              draftPhotoKeys: [drafted.photo_key],
              aiGenerated: true,
            })
      navigate(`/listings/${listing.id}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not create the listing.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Give something away</h1>
        <p className="text-sm text-slate-500">
          Upload a photo and let the assistant draft it, or just fill the form in yourself.
        </p>
      </div>

      <section className="card space-y-3 p-5">
        <h2 className="font-semibold">1. Photo (optional)</h2>
        <input
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          aria-label="Item photo"
          className="field"
          onChange={(event) => onPickPhoto(event.target.files?.[0] ?? null)}
        />

        {previewUrl !== null && (
          <img
            src={previewUrl}
            alt="Selected item"
            className="max-h-64 w-full rounded-lg object-contain"
          />
        )}

        <button
          type="button"
          className="btn-primary w-full sm:w-auto"
          disabled={photo === null || drafting}
          onClick={() => void autoFill()}
        >
          {drafting ? 'Looking at your photo…' : '✨ Auto-fill from photo'}
        </button>

        {draftError !== null && <ErrorNote message={draftError} />}

        {drafted !== null && (
          <div className="space-y-2 rounded-lg bg-violet-50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <AiBadge confidence={drafted.confidence} />
              <span className="text-xs text-slate-600">Edit anything below before publishing.</span>
            </div>
            {drafted.summary !== '' && (
              <p className="text-xs text-slate-600">{drafted.summary}</p>
            )}
            {drafted.confidence < 0.5 && (
              <p className="text-xs text-amber-800">
                The assistant was not confident about this photo — please check the fields
                carefully.
              </p>
            )}
            {drafted.flagged && (
              <InfoNote>
                <strong>This item may not be allowed.</strong>{' '}
                {drafted.flag_reason ?? 'It looks like it breaks the prohibited-items rules.'} If
                you publish it, it will be hidden from other students.
              </InfoNote>
            )}
          </div>
        )}
      </section>

      <form onSubmit={(event) => void onSubmit(event)} className="card space-y-4 p-5">
        <h2 className="font-semibold">2. Details</h2>
        {error !== null && <ErrorNote message={error} />}

        <div>
          <label className="label" htmlFor="title">
            Title
          </label>
          <input
            id="title"
            className="field"
            required
            minLength={3}
            maxLength={140}
            value={values.title}
            onChange={(event) => set('title', event.target.value)}
          />
        </div>

        <div>
          <label className="label" htmlFor="description">
            Description
          </label>
          <textarea
            id="description"
            className="field min-h-24"
            maxLength={4000}
            value={values.description}
            onChange={(event) => set('description', event.target.value)}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="category">
              Category
            </label>
            <select
              id="category"
              className="field"
              value={values.category}
              onChange={(event) => set('category', event.target.value as Category)}
            >
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {CATEGORY_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="condition">
              Condition
            </label>
            <select
              id="condition"
              className="field"
              value={values.condition}
              onChange={(event) => set('condition', event.target.value as Condition)}
            >
              {CONDITIONS.map((value) => (
                <option key={value} value={value}>
                  {CONDITION_LABELS[value]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="label" htmlFor="pickup_area">
            Pickup area
          </label>
          <input
            id="pickup_area"
            className="field"
            required
            maxLength={160}
            placeholder="e.g. Guy-Concordia metro"
            value={values.pickup_area}
            onChange={(event) => set('pickup_area', event.target.value)}
          />
        </div>

        <button type="submit" className="btn-primary w-full" disabled={submitting}>
          {submitting ? 'Publishing…' : 'Publish listing'}
        </button>
      </form>
    </div>
  )
}
