import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from 'react-query'
import { Check, Plus, X } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../../services/api'
import { STATUS_STYLE } from './KnownBar'
import SpeakButton from '../SpeakButton'
import type { ReadingSegment, WordLookup, WordStatus } from '../../types'

export interface Selected {
  thai: string
  status: WordStatus
  /** The line the word appeared on, used as the card's example sentence. */
  context: string
}

/** Render a line's segments; Thai words are tappable and coloured by status. */
export function SegmentLine({
  segments,
  selected,
  onSelect,
}: {
  segments: ReadingSegment[]
  selected: Selected | null
  onSelect: (s: Selected) => void
}) {
  const context = segments.map((s) => s.text).join('').trim()
  return (
    <>
      {segments.map((seg, j) => (
        <Segment
          key={j}
          seg={seg}
          active={selected?.thai === seg.text}
          onSelect={() => seg.status && onSelect({ thai: seg.text, status: seg.status, context })}
        />
      ))}
    </>
  )
}

export function Segment({ seg, active, onSelect }: { seg: ReadingSegment; active: boolean; onSelect: () => void }) {
  if (!seg.status) return <span>{seg.text}</span>
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect())}
      className={`cursor-pointer rounded px-0.5 transition-colors hover:ring-2 hover:ring-brand-200 ${
        STATUS_STYLE[seg.status].word
      } ${active ? 'ring-2 ring-brand-500' : ''}`}
    >
      {seg.text}
    </span>
  )
}

export function WordPanel({
  selected,
  uploadId,
  onClose,
  onStatus,
}: {
  selected: Selected
  /** Upload the word was read in; its deck gets the card. */
  uploadId?: number
  onClose: () => void
  onStatus: (status: WordStatus) => void
}) {
  const qc = useQueryClient()
  const { data: info, isLoading } = useQuery<WordLookup>(['reading-lookup', selected.thai], () =>
    api.get('/reading/lookup', { params: { thai: selected.thai } }).then((r) => r.data),
  )
  const [english, setEnglish] = useState('')
  useEffect(() => {
    if (info && !english) setEnglish(info.glosses[0]?.gloss ?? '')
  }, [info])

  function refresh() {
    qc.invalidateQueries('reading-page')
    qc.invalidateQueries('reading-uploads')
    qc.invalidateQueries(['reading-lookup', selected.thai])
    qc.invalidateQueries('due-summary')
  }

  const addCard = useMutation(
    () =>
      api.post('/reading/cards', {
        thai: selected.thai,
        english: english.trim(),
        upload_id: uploadId,
        example_thai: selected.context,
      }),
    {
      onSuccess: (r) => {
        toast.success(r.data.created ? 'Card added. It will come up first in your new cards.' : 'Already in that deck')
        if (selected.status === 'unknown') onStatus('new')
        refresh()
      },
    },
  )
  const markKnown = useMutation(
    (known: boolean) => api.post('/reading/known', { thai: selected.thai, known }),
    {
      onSuccess: (_, known) => {
        onStatus(known ? 'known' : 'unknown')
        refresh()
      },
    },
  )

  const status = selected.status
  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-1">
            <p className="text-3xl font-thai text-gray-900">{selected.thai}</p>
            <SpeakButton source={{ kind: 'text', text: selected.thai }} thai={selected.thai} showSlow />
          </div>
          {info?.romanization && <p className="text-sm text-gray-500 mt-0.5">{info.romanization}</p>}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1" aria-label="Close">
          <X size={16} />
        </button>
      </div>

      <span className="inline-flex items-center gap-1.5 text-xs text-gray-500">
        <span className={`inline-block h-2 w-2 rounded-full ${STATUS_STYLE[status].dot}`} />
        {STATUS_STYLE[status].label}
      </span>

      {isLoading && <p className="text-sm text-gray-400">Looking up…</p>}

      {info?.card ? (
        <div className="space-y-1">
          <p className="text-xs font-medium text-gray-500">Your card</p>
          <p className="text-gray-800">{info.card.english}</p>
        </div>
      ) : (
        info && (
          <div className="space-y-3">
            {info.glosses.length > 0 ? (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-gray-500">Meanings</p>
                <div className="flex flex-wrap gap-1.5">
                  {info.glosses.map((g) => (
                    <button
                      key={g.gloss}
                      onClick={() => setEnglish(g.gloss)}
                      className={`text-sm px-2 py-0.5 rounded-lg border transition-colors ${
                        english === g.gloss
                          ? 'border-brand-500 bg-brand-50 text-brand-700'
                          : 'border-gray-200 text-gray-700 hover:border-brand-200'
                      }`}
                    >
                      {g.gloss}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500">No dictionary entry. Type a meaning to add it.</p>
            )}

            <div className="space-y-1.5">
              <label htmlFor="mine-english" className="text-xs font-medium text-gray-500">
                Card meaning
              </label>
              <input
                id="mine-english"
                value={english}
                onChange={(e) => setEnglish(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && english.trim() && addCard.mutate()}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>

            <button
              onClick={() => addCard.mutate()}
              disabled={!english.trim() || addCard.isLoading}
              className="btn-primary w-full flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              <Plus size={15} /> Add as card
            </button>
            {selected.context !== selected.thai && (
              <p className="text-xs text-gray-400">This line is saved as the card&apos;s example.</p>
            )}
          </div>
        )
      )}

      {info && !info.card && (
        <button
          onClick={() => markKnown.mutate(!info.marked_known)}
          disabled={markKnown.isLoading}
          className="btn-secondary w-full text-sm flex items-center justify-center gap-1.5"
        >
          <Check size={14} />
          {info.marked_known ? 'Unmark as known' : 'I already know this'}
        </button>
      )}
    </div>
  )
}
