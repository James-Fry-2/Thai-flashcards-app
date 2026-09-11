import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { X, Plus, ArrowRight, ChevronLeft, Pencil, Check, Flag, RotateCcw, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import type {
  CardDetail,
  SimilarCard,
  Tag,
  Topic,
  CompoundPart,
  FlagListItem,
  TranslationCandidates,
  CompoundCandidates,
  EnrichBreakdownResponse,
  VerifyTranslationResponse,
} from '../types'
import CompoundBreakdown from './CompoundBreakdown'

interface Props {
  cardId: number | null
  deckId?: number
  onClose: () => void
}

export default function CardDetailDrawer({ cardId: initialCardId, deckId, onClose }: Props) {
  const qc = useQueryClient()
  // Internal navigation stack: [initialCardId, ...navigated]
  const [navStack, setNavStack] = useState<number[]>([])
  const cardId = navStack.length > 0 ? navStack[navStack.length - 1] : initialCardId

  // Reset stack when the external prop changes
  useEffect(() => {
    setNavStack([])
  }, [initialCardId])

  const navigateTo = (id: number) => setNavStack((s) => [...s, id])
  const navigateBack = () => setNavStack((s) => s.slice(0, -1))

  const [compoundCorrectionOpen, setCompoundCorrectionOpen] = useState(false)

  const { data: card, isLoading } = useQuery<CardDetail>(
    ['card', cardId],
    () => api.get(`/cards/${cardId}`).then((r) => r.data),
    { enabled: cardId !== null }
  )

  const invalidate = () => {
    qc.invalidateQueries(['card', cardId])
    qc.invalidateQueries(['open-flags', cardId])
    if (deckId !== undefined) qc.invalidateQueries(['cards', deckId])
  }

  const { data: similarCards = [] } = useQuery<SimilarCard[]>(
    ['similar-cards', cardId],
    () => api.get(`/cards/${cardId}/similar?limit=10`).then((r) => r.data),
    { enabled: cardId !== null }
  )

  // GET /flags has no card_id filter (single-user app, modest flag volume) —
  // fetch this user's open queue and narrow to this card client-side.
  const { data: openFlagItems = [] } = useQuery<FlagListItem[]>(
    ['open-flags', cardId],
    () =>
      api
        .get('/flags', { params: { status: 'open', limit: 200 } })
        .then((r) => (r.data.items as FlagListItem[]).filter((f) => f.card_id === cardId)),
    { enabled: cardId !== null && !!card?.has_open_flags }
  )

  const { data: translationCandidates } = useQuery<TranslationCandidates>(
    ['translation-candidates', cardId],
    () => api.get(`/cards/${cardId}/translation-candidates`).then((r) => r.data),
    { enabled: cardId !== null && card?.translation_status === 'flagged' }
  )

  const { data: compoundCandidates } = useQuery<CompoundCandidates>(
    ['compound-candidates', cardId],
    () => api.get(`/cards/${cardId}/compound-candidates`).then((r) => r.data),
    { enabled: cardId !== null && compoundCorrectionOpen }
  )

  const updateCard = useMutation(
    (patch: Record<string, unknown>) =>
      api.patch(`/cards/${cardId}`, patch).then((r) => r.data),
    { onSuccess: invalidate },
  )

  const resolveTranslation = useMutation(
    (payload: { action: 'keep' | 'correct'; english?: string }) =>
      api.post(`/cards/${cardId}/resolve-translation`, payload).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Translation resolved')
      },
    }
  )

  const verifyTranslation = useMutation<VerifyTranslationResponse>(() =>
    api.post(`/cards/${cardId}/verify-translation`).then((r) => r.data)
  )

  const enrichBreakdown = useMutation<EnrichBreakdownResponse>(
    () => api.post(`/cards/${cardId}/enrich-breakdown`).then((r) => r.data),
    {
      onSuccess: (result) => {
        if (result.status === 'no_gaps') {
          toast.success('Already fully glossed')
        } else if (result.status === 'enriched') {
          if (result.persisted && result.filled && result.filled.length > 0) {
            invalidate()
            toast.success('Breakdown updated')
          } else if (result.filled && result.filled.length > 0) {
            // Low-confidence fill — not written to compound_breakdown.
            // Rendered as an unsaved suggestion in BreakdownSection instead.
            toast('Low-confidence result — not saved automatically', { icon: '⚠️' })
          } else {
            toast('No gloss could be added for the missing part(s)', { icon: 'ℹ️' })
          }
        }
      },
    }
  )

  // Advisory results are per-card; drop them when navigating to another card
  // so a stale verdict/confidence from the previous card can't linger.
  useEffect(() => {
    verifyTranslation.reset()
    enrichBreakdown.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardId])

  // A low-confidence fill is never written to compound_breakdown — surface
  // it as an unsaved suggestion the user has to act on explicitly, rather
  // than silently discarding it after the toast disappears.
  const unsavedFill =
    enrichBreakdown.data?.status === 'enriched' &&
    !enrichBreakdown.data.persisted &&
    (enrichBreakdown.data.filled?.length ?? 0) > 0
      ? enrichBreakdown.data
      : undefined

  const deleteOverride = useMutation(
    (target: 'translation' | 'compound') => api.delete(`/cards/${cardId}/overrides/${target}`),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Reverted to dictionary')
      },
    }
  )

  const putCompoundOverride = useMutation(
    (payload: { suppressed?: boolean; parts?: CompoundPart[] }) =>
      api.put(`/cards/${cardId}/overrides/compound`, { payload }).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        setCompoundCorrectionOpen(false)
        toast.success('Breakdown updated')
      },
    }
  )

  const createFlag = useMutation(
    (payload: { target: string; note?: string }) =>
      api.post(`/cards/${cardId}/flags`, payload).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        setCompoundCorrectionOpen(false)
        toast.success('Flagged for review')
      },
    }
  )

  const resolveFlag = useMutation(
    ({ id, status }: { id: number; status: 'resolved' | 'dismissed' }) =>
      api.patch(`/flags/${id}`, { status }).then((r) => r.data),
    { onSuccess: invalidate }
  )

  const removeTag = useMutation(
    (tagId: number) => api.delete(`/cards/${cardId}/tags/${tagId}`),
    { onSuccess: invalidate }
  )

  const removeTopic = useMutation(
    (topicId: number) => api.delete(`/cards/${cardId}/topics/${topicId}`),
    { onSuccess: invalidate }
  )

  const addTag = useMutation(
    (payload: { tag_id?: number; tag_name?: string }) =>
      api.post(`/cards/${cardId}/tags`, payload).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Tag added')
      },
    }
  )

  const addTopic = useMutation(
    (payload: { topic_id?: number; topic_name?: string }) =>
      api.post(`/cards/${cardId}/topics`, payload).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Topic added')
      },
    }
  )

  if (cardId === null) return null

  return (
    <>
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
        aria-hidden={true}
      />
      <div className="fixed right-0 top-0 h-full w-[500px] bg-white shadow-xl z-50 flex flex-col">
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-start gap-2 flex-1 min-w-0">
            {navStack.length > 0 && (
              <button
                onClick={navigateBack}
                className="mt-1 p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 shrink-0"
                title="Back"
              >
                <ChevronLeft size={16} />
              </button>
            )}
            <div className="flex-1 min-w-0">
              {card ? (
                <>
                  <p className="thai text-2xl font-medium">{card.thai}</p>
                  <p className="text-sm text-gray-500 mt-0.5">{card.english}</p>
                  {card.romanization && (
                    <p className="text-xs text-gray-400 mt-0.5">{card.romanization}</p>
                  )}
                </>
              ) : (
                <div className="h-8 bg-gray-100 rounded animate-pulse w-48" />
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-4 p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {isLoading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-4 bg-gray-100 rounded animate-pulse" />
              ))}
            </div>
          )}

          {card && (
            <>
              {/* Open flags this user filed on this card */}
              {openFlagItems.length > 0 && (
                <OpenFlagsBanner
                  flags={openFlagItems}
                  onResolve={(id) => resolveFlag.mutate({ id, status: 'resolved' })}
                  onDismiss={(id) => resolveFlag.mutate({ id, status: 'dismissed' })}
                  isSaving={resolveFlag.isLoading}
                />
              )}

              {/* Translation flag */}
              {card.translation_status === 'flagged' && (
                <TranslationFlag
                  english={card.english}
                  candidates={translationCandidates?.candidates ?? []}
                  allowFreeText={translationCandidates?.allow_free_text ?? true}
                  onKeep={() => resolveTranslation.mutate({ action: 'keep' })}
                  onCorrect={(value) => resolveTranslation.mutate({ action: 'correct', english: value })}
                  isSaving={resolveTranslation.isLoading}
                  onCheckAI={() => verifyTranslation.mutate()}
                  isChecking={verifyTranslation.isLoading}
                  aiResult={verifyTranslation.data}
                />
              )}

              {/* Translation override note — visible even once translation_status
                  has moved past 'flagged' (e.g. right after a 'correct'). */}
              {card.english_source === 'user' && card.translation_status !== 'flagged' && (
                <div className="flex items-center justify-between bg-brand-50 border border-brand-100 rounded-xl px-4 py-2.5 text-xs">
                  <span className="text-brand-700">
                    Using your correction: <span className="font-medium">{card.english}</span>
                  </span>
                  <button
                    onClick={() => deleteOverride.mutate('translation')}
                    disabled={deleteOverride.isLoading}
                    className="flex items-center gap-1 text-brand-600 hover:text-brand-800 shrink-0 ml-3"
                  >
                    <RotateCcw size={11} /> Revert
                  </button>
                </div>
              )}

              {/* Tags section */}
              <section>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Tags
                </h3>
                <PillGroup
                  pills={card.tags}
                  colorClass="bg-gray-100 text-gray-600"
                  onRemove={(id) => removeTag.mutate(id)}
                />
                <TagCombobox
                  cardId={cardId}
                  existingIds={card.tags.map((t) => t.id)}
                  onAdd={(payload) => addTag.mutate(payload)}
                  isAdding={addTag.isLoading}
                />
              </section>

              {/* Topics section */}
              <section>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  Topics
                </h3>
                <PillGroup
                  pills={card.topics}
                  colorClass="bg-brand-100 text-brand-700"
                  onRemove={(id) => removeTopic.mutate(id)}
                />
                <TopicCombobox
                  existingIds={card.topics.map((t) => t.id)}
                  onAdd={(payload) => addTopic.mutate(payload)}
                  isAdding={addTopic.isLoading}
                />
              </section>

              {/* Card details */}
              {(card.example_thai || card.example_english) && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                    Example
                  </h3>
                  {card.example_thai && (
                    <p className="thai text-sm text-gray-700">{card.example_thai}</p>
                  )}
                  {card.example_english && (
                    <p className="text-sm text-gray-500 mt-0.5">{card.example_english}</p>
                  )}
                </section>
              )}

              {card.notes && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                    Notes
                  </h3>
                  <p className="text-sm text-gray-600">{card.notes}</p>
                </section>
              )}

              {/* Romanization schemes */}
              <RomanizationSection
                card={card}
                onSaveManual={(value) => updateCard.mutate({ romanization: value })}
                isSaving={updateCard.isLoading}
              />

              {/* Script analysis */}
              {card.script_analysis && card.script_analysis.length > 0 && (
                <ScriptAnalysisSection syllables={card.script_analysis} />
              )}

              {/* Compound breakdown */}
              {card.is_compound && (
                <BreakdownSection
                  parts={card.compound_breakdown ?? []}
                  suppressed={!!card.compound_suppressed}
                  sourceIsUser={card.compound_breakdown_source === 'user'}
                  hasOverride={card.compound_breakdown_source === 'user' || !!card.compound_suppressed}
                  correctionOpen={compoundCorrectionOpen}
                  onOpenCorrection={() => setCompoundCorrectionOpen((v) => !v)}
                  onRevert={() => deleteOverride.mutate('compound')}
                  isRevertSaving={deleteOverride.isLoading}
                  candidates={compoundCorrectionOpen ? compoundCandidates : undefined}
                  onSuppress={() => putCompoundOverride.mutate({ suppressed: true })}
                  onSaveParts={(parts) => putCompoundOverride.mutate({ parts })}
                  onFileFlag={(note) => createFlag.mutate({ target: 'compound', note })}
                  isSaving={putCompoundOverride.isLoading || createFlag.isLoading}
                  onFillGaps={() => enrichBreakdown.mutate()}
                  isFillingGaps={enrichBreakdown.isLoading}
                  unsavedFill={unsavedFill}
                  onDismissFill={() => enrichBreakdown.reset()}
                  onSuppressUnsavedFill={() => {
                    enrichBreakdown.reset()
                    putCompoundOverride.mutate({ suppressed: true })
                  }}
                />
              )}

              {/* Links */}
              {card.links && (
                <LinksSection links={card.links} />
              )}

              {/* Similar cards */}
              <SimilarCardsSection cards={similarCards} onNavigate={navigateTo} />
            </>
          )}
        </div>
      </div>
    </>
  )
}

function PillGroup({
  pills,
  colorClass,
  onRemove,
}: {
  pills: { id: number; name: string }[]
  colorClass: string
  onRemove: (id: number) => void
}) {
  if (pills.length === 0) {
    return <p className="text-xs text-gray-400 mb-2">None</p>
  }
  return (
    <div className="flex flex-wrap gap-1.5 mb-2">
      {pills.map((p) => (
        <span
          key={p.id}
          className={`group inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium ${colorClass}`}
        >
          {p.name}
          <button
            onClick={() => onRemove(p.id)}
            className="opacity-0 group-hover:opacity-100 transition-opacity ml-0.5 hover:text-red-500"
            title={`Remove ${p.name}`}
          >
            <X size={11} />
          </button>
        </span>
      ))}
    </div>
  )
}

function TagCombobox({
  cardId,
  existingIds,
  onAdd,
  isAdding,
}: {
  cardId: number
  existingIds: number[]
  onAdd: (payload: { tag_id?: number; tag_name?: string }) => void
  isAdding: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: suggestions = [] } = useQuery<Tag[]>(
    ['tags', 'search', query],
    () => api.get(`/tags?search=${encodeURIComponent(query)}`).then((r) => r.data),
    { enabled: open, keepPreviousData: true }
  )

  const filtered = suggestions.filter((t) => !existingIds.includes(t.id))
  const showCreate = query.trim().length > 0 && !filtered.some(
    (t) => t.name.toLowerCase() === query.trim().toLowerCase()
  )

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const select = (tag: Tag) => {
    onAdd({ tag_id: tag.id })
    setQuery('')
    setOpen(false)
  }

  const create = () => {
    onAdd({ tag_name: query.trim() })
    setQuery('')
    setOpen(false)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-brand-600 transition-colors"
      >
        <Plus size={12} /> Add tag
      </button>
    )
  }

  return (
    <div className="relative mt-1">
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { setOpen(false); setQuery('') }
          if (e.key === 'Enter' && showCreate) create()
        }}
        placeholder="Search or create tag…"
        className="w-full text-xs border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
        disabled={isAdding}
      />
      {(filtered.length > 0 || showCreate) && (
        <ul className="absolute z-10 top-full mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.slice(0, 8).map((tag) => (
            <li key={tag.id}>
              <button
                className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center justify-between"
                onClick={() => select(tag)}
              >
                <span>{tag.name}</span>
                <span className="text-gray-400">{tag.card_count} cards</span>
              </button>
            </li>
          ))}
          {showCreate && (
            <li>
              <button
                className="w-full text-left px-3 py-2 text-xs text-brand-600 hover:bg-brand-50 font-medium"
                onClick={create}
              >
                Create new tag: "{query.trim()}"
              </button>
            </li>
          )}
        </ul>
      )}
      <button
        onClick={() => { setOpen(false); setQuery('') }}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
      >
        <X size={12} />
      </button>
    </div>
  )
}

function TopicCombobox({
  existingIds,
  onAdd,
  isAdding,
}: {
  existingIds: number[]
  onAdd: (payload: { topic_id?: number; topic_name?: string }) => void
  isAdding: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: allTopics = [] } = useQuery<Topic[]>(
    'topics',
    () => api.get('/topics').then((r) => r.data),
    { staleTime: 30_000 }
  )

  const filtered = allTopics.filter(
    (t) =>
      !existingIds.includes(t.id) &&
      (query.trim() === '' || t.name.toLowerCase().includes(query.toLowerCase()))
  )
  const showCreate =
    query.trim().length > 0 &&
    !filtered.some((t) => t.name.toLowerCase() === query.trim().toLowerCase())

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const select = (topic: Topic) => {
    onAdd({ topic_id: topic.id })
    setQuery('')
    setOpen(false)
  }

  const create = () => {
    onAdd({ topic_name: query.trim() })
    setQuery('')
    setOpen(false)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-brand-600 transition-colors"
      >
        <Plus size={12} /> Add topic
      </button>
    )
  }

  return (
    <div className="relative mt-1">
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { setOpen(false); setQuery('') }
          if (e.key === 'Enter' && showCreate) create()
        }}
        placeholder="Search or create topic…"
        className="w-full text-xs border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
        disabled={isAdding}
      />
      {(filtered.length > 0 || showCreate) && (
        <ul className="absolute z-10 top-full mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.slice(0, 8).map((topic) => (
            <li key={topic.id}>
              <button
                className="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center justify-between"
                onClick={() => select(topic)}
              >
                <span>{topic.name}</span>
                <span className="text-gray-400">{topic.card_count} cards</span>
              </button>
            </li>
          ))}
          {showCreate && (
            <li>
              <button
                className="w-full text-left px-3 py-2 text-xs text-brand-600 hover:bg-brand-50 font-medium"
                onClick={create}
              >
                Create new topic: "{query.trim()}"
              </button>
            </li>
          )}
        </ul>
      )}
      <button
        onClick={() => { setOpen(false); setQuery('') }}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
      >
        <X size={12} />
      </button>
    </div>
  )
}

function RomanizationSection({
  card,
  onSaveManual,
  isSaving,
}: {
  card: CardDetail
  onSaveManual: (value: string) => void
  isSaving: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const schemes: { label: string; value?: string; isManual?: boolean }[] = [
    { label: 'Source', value: card.romanization_source },
    { label: 'Paiboon+', value: card.romanization_paiboon },
    { label: 'RTGS', value: card.romanization_rtgs },
    { label: 'IPA', value: card.romanization_ipa },
    { label: 'Manual override', value: card.romanization_manual, isManual: true },
  ]

  const hasAny = schemes.some((s) => s.value)

  function startEdit() {
    setDraft(card.romanization_manual ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  function commit() {
    onSaveManual(draft)
    setEditing(false)
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Romanization
        </h3>
        <button
          onClick={startEdit}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-brand-600 transition-colors"
          title="Set manual override"
        >
          <Pencil size={11} />
          Override
        </button>
      </div>

      {editing ? (
        <div className="flex gap-2 mb-3">
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') setEditing(false)
            }}
            placeholder="Manual romanization…"
            disabled={isSaving}
            className="flex-1 text-xs border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <button
            onClick={commit}
            disabled={isSaving}
            className="p-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
            title="Save"
          >
            <Check size={13} />
          </button>
          <button
            onClick={() => setEditing(false)}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100"
            title="Cancel"
          >
            <X size={13} />
          </button>
        </div>
      ) : null}

      {hasAny ? (
        <dl className="space-y-1">
          {schemes.map((s) =>
            s.value ? (
              <div key={s.label} className="flex items-baseline gap-2">
                <dt className="text-[10px] font-medium text-gray-400 w-24 shrink-0">{s.label}</dt>
                <dd
                  className={`text-xs ${
                    s.isManual ? 'text-brand-700 font-medium' : 'text-gray-700'
                  }`}
                >
                  {s.value}
                </dd>
              </div>
            ) : null
          )}
        </dl>
      ) : (
        <p className="text-xs text-gray-400">No romanization stored yet.</p>
      )}
    </section>
  )
}

function ScriptAnalysisSection({ syllables }: { syllables: { syllable?: string; tone?: string; [key: string]: unknown }[] }) {
  return (
    <section>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Script Analysis
      </h3>
      <div className="flex flex-wrap gap-2">
        {syllables.map((s, i) => (
          <div
            key={i}
            className="bg-gray-50 border border-gray-100 rounded-lg px-2.5 py-1.5 text-center"
          >
            <p className="thai text-base">{String(s.syllable ?? '')}</p>
            {s.tone && (
              <p className="text-xs text-gray-400 mt-0.5">{String(s.tone)}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function TranslationFlag({
  english,
  candidates,
  allowFreeText,
  onKeep,
  onCorrect,
  isSaving,
  onCheckAI,
  isChecking,
  aiResult,
}: {
  english: string
  candidates: string[]
  allowFreeText: boolean
  onKeep: () => void
  onCorrect: (value: string) => void
  isSaving: boolean
  onCheckAI: () => void
  isChecking: boolean
  aiResult?: VerifyTranslationResponse
}) {
  const [draft, setDraft] = useState('')

  const chosen = draft.trim()
  const canCorrect = chosen.length > 0 && chosen !== english
  // Candidates are always the primary affordance; free text is the
  // fallback shown only when there's genuinely nothing to pick from.
  const showFreeText = allowFreeText && candidates.length === 0

  return (
    <section className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-3.5">
      <h3 className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-1">
        Possible mistranslation
      </h3>
      <p className="text-xs text-amber-700/80 mb-3">
        The dictionary suggests a different translation. This is only a suggestion — your
        materials are the default and win unless you correct it.
      </p>

      <div className="mb-3">
        <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1">
          From your materials
        </p>
        <p className="text-sm font-medium text-gray-800">{english}</p>
      </div>

      {candidates.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mb-1">
            Dictionary suggests
          </p>
          <div className="flex flex-wrap gap-1.5">
            {candidates.map((c) => (
              <button
                key={c}
                onClick={() => setDraft(c)}
                disabled={isSaving}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  draft.trim() === c
                    ? 'bg-amber-600 text-white border-amber-600'
                    : 'bg-white text-amber-700 border-amber-200 hover:bg-amber-100'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
        </div>
      )}

      {showFreeText && (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Type a correction…"
          disabled={isSaving}
          className="w-full text-xs border border-amber-200 rounded-lg px-3 py-2 mb-3 focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
        />
      )}

      {aiResult?.status === 'checked' && (
        <p
          className={`text-xs mb-3 rounded-lg px-2.5 py-1.5 ${
            aiResult.verdict === 'likely_error'
              ? 'bg-red-50 text-red-700'
              : aiResult.verdict === 'likely_ok'
                ? 'bg-green-50 text-green-700'
                : 'bg-gray-100 text-gray-600'
          }`}
        >
          <span className="font-medium">
            AI:{' '}
            {aiResult.verdict === 'likely_error'
              ? 'likely a real mistranslation'
              : aiResult.verdict === 'likely_ok'
                ? 'likely a false flag'
                : "not sure"}
          </span>
          {aiResult.reason && <span> — {aiResult.reason}</span>}
        </p>
      )}

      <div className="flex gap-2">
        <button
          onClick={onKeep}
          disabled={isSaving}
          className="btn-secondary text-xs flex-1"
        >
          Keep
        </button>
        <button
          onClick={() => onCorrect(chosen)}
          disabled={isSaving || !canCorrect}
          className="text-xs flex-1 rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1.5 font-medium transition-colors"
        >
          Use correction
        </button>
      </div>
      <button
        onClick={onCheckAI}
        disabled={isSaving || isChecking}
        className="mt-2 w-full flex items-center justify-center gap-1 text-xs text-amber-700 hover:text-amber-900 font-medium disabled:opacity-50"
      >
        <Sparkles size={11} /> {isChecking ? 'Checking…' : 'Check with AI'}
      </button>
    </section>
  )
}

function OpenFlagsBanner({
  flags,
  onResolve,
  onDismiss,
  isSaving,
}: {
  flags: FlagListItem[]
  onResolve: (id: number) => void
  onDismiss: (id: number) => void
  isSaving: boolean
}) {
  return (
    <section className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3.5 space-y-2.5">
      <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1.5">
        <Flag size={12} className="text-amber-500" /> Your open flags
      </h3>
      {flags.map((f) => (
        <div key={f.id} className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <span className="text-xs font-medium text-gray-700 capitalize">{f.target}</span>
            {f.note && <p className="text-xs text-gray-500 mt-0.5">{f.note}</p>}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => onDismiss(f.id)}
              disabled={isSaving}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Dismiss
            </button>
            <button
              onClick={() => onResolve(f.id)}
              disabled={isSaving}
              className="text-xs text-brand-600 hover:text-brand-800 font-medium"
            >
              Resolve
            </button>
          </div>
        </div>
      ))}
    </section>
  )
}

function BreakdownSection({
  parts,
  suppressed,
  sourceIsUser,
  hasOverride,
  correctionOpen,
  onOpenCorrection,
  onRevert,
  isRevertSaving,
  candidates,
  onSuppress,
  onSaveParts,
  onFileFlag,
  isSaving,
  onFillGaps,
  isFillingGaps,
  unsavedFill,
  onDismissFill,
  onSuppressUnsavedFill,
}: {
  parts: CompoundPart[]
  suppressed: boolean
  sourceIsUser: boolean
  hasOverride: boolean
  correctionOpen: boolean
  onOpenCorrection: () => void
  onRevert: () => void
  isRevertSaving: boolean
  candidates: CompoundCandidates | undefined
  onSuppress: () => void
  onSaveParts: (parts: CompoundPart[]) => void
  onFileFlag: (note: string) => void
  isSaving: boolean
  onFillGaps: () => void
  isFillingGaps: boolean
  unsavedFill?: EnrichBreakdownResponse
  onDismissFill: () => void
  onSuppressUnsavedFill: () => void
}) {
  // Available on every compound card, not just ones with a stored gap — a
  // card whose breakdown never surfaced (compound_surface_min_gloss_ratio
  // held it back) still has no chips here, and the backend recomputes the
  // segmentation for those on demand. A suppressed card is excluded: the
  // user has already said it isn't a compound, so there's nothing to fill.
  const showFillGaps = !suppressed

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Breakdown
        </h3>
        <div className="flex items-center gap-2">
          {hasOverride && (
            <button
              onClick={onRevert}
              disabled={isRevertSaving}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-brand-600 transition-colors"
              title="Revert to dictionary breakdown"
            >
              <RotateCcw size={11} /> Revert
            </button>
          )}
          <button
            onClick={onOpenCorrection}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-brand-600 transition-colors"
            title="Correct this breakdown"
          >
            <Pencil size={11} /> Correct
          </button>
        </div>
      </div>

      {suppressed ? (
        <p className="text-xs text-gray-400">You marked this as not a compound.</p>
      ) : parts.length > 0 ? (
        <CompoundBreakdown parts={parts} sourceIsUser={sourceIsUser} />
      ) : (
        <p className="text-xs text-gray-400">
          This word decomposes, but not every part has a clear gloss, so the breakdown isn't
          shown by default.
        </p>
      )}

      {showFillGaps && !unsavedFill && (
        <button
          onClick={onFillGaps}
          disabled={isFillingGaps}
          className="mt-2 flex items-center gap-1 text-xs text-amber-700 hover:text-amber-900 font-medium disabled:opacity-50"
        >
          <Sparkles size={11} /> {isFillingGaps ? 'Filling…' : 'Fill gaps with AI'}
        </button>
      )}

      {unsavedFill && (
        <div className="mt-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5">
          <p className="text-[10px] font-semibold text-amber-700 uppercase tracking-wide mb-1.5">
            ⚠️ Low confidence — not saved
          </p>
          <div className="space-y-1 mb-2">
            {unsavedFill.filled?.map((thai) => {
              const part = unsavedFill.parts?.find((p) => p.thai === thai)
              return (
                <p key={thai} className="text-xs text-amber-800">
                  <span className="thai font-medium">{thai}</span>
                  {' → '}
                  <span className="italic">{part?.gloss ?? '?'}</span>
                  <span className="text-amber-500">?</span>
                </p>
              )
            })}
          </div>
          <p className="text-[11px] text-amber-700/80 mb-2">
            This word may be a loanword or false split rather than a real compound — the AI
            wasn't confident enough to save this automatically.
          </p>
          <div className="flex gap-2">
            <button
              onClick={onDismissFill}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg text-amber-700 hover:bg-amber-100 transition-colors"
            >
              Dismiss
            </button>
            <button
              onClick={onSuppressUnsavedFill}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700 transition-colors"
            >
              Suppress as not-a-compound
            </button>
          </div>
        </div>
      )}

      {correctionOpen && candidates && (
        <CompoundCorrectionPanel
          candidates={candidates}
          onSuppress={onSuppress}
          onSave={onSaveParts}
          onFileFlag={onFileFlag}
          onClose={onOpenCorrection}
          isSaving={isSaving}
        />
      )}
      {correctionOpen && !candidates && (
        <p className="text-xs text-gray-400 mt-2">Loading candidates…</p>
      )}
    </section>
  )
}

function CompoundCorrectionPanel({
  candidates,
  onSuppress,
  onSave,
  onFileFlag,
  onClose,
  isSaving,
}: {
  candidates: CompoundCandidates
  onSuppress: () => void
  onSave: (parts: CompoundPart[]) => void
  onFileFlag: (note: string) => void
  onClose: () => void
  isSaving: boolean
}) {
  const currentThaiSeq = candidates.current.map((p) => p.thai)
  const initialSeg =
    candidates.segmentations.find((s) => s.is_current)?.parts ??
    (currentThaiSeq.length ? currentThaiSeq : candidates.segmentations[0]?.parts ?? [])

  const [segThai, setSegThai] = useState<string[]>(initialSeg)
  const [noneOfThese, setNoneOfThese] = useState(false)
  const [flagNote, setFlagNote] = useState('')
  const [glossChoice, setGlossChoice] = useState<Record<string, { gloss: string; source: string }>>({})
  const [freeTextOpen, setFreeTextOpen] = useState<Record<string, boolean>>({})

  function currentGlossFor(thai: string): { gloss: string; source: string } | null {
    if (glossChoice[thai]) return glossChoice[thai]
    const options = candidates.part_glosses[thai] ?? []
    const current = options.find((o) => o.is_current)
    if (current) return { gloss: current.gloss, source: current.source }
    return options[0] ? { gloss: options[0].gloss, source: options[0].source } : null
  }

  function buildParts(): CompoundPart[] {
    return segThai.map((thai) => {
      const chosen = currentGlossFor(thai)
      const existing = candidates.current.find((p) => p.thai === thai)
      return {
        thai,
        romanization: existing?.romanization ?? null,
        gloss: chosen?.gloss ?? null,
        gloss_source: (chosen?.source as CompoundPart['gloss_source']) ?? null,
      }
    })
  }

  return (
    <div className="mt-3 border border-gray-200 rounded-xl p-3 space-y-3 bg-gray-50">
      <button
        onClick={onSuppress}
        disabled={isSaving}
        className="w-full text-xs px-3 py-2 rounded-lg border border-gray-200 bg-white hover:bg-gray-100 text-left transition-colors"
      >
        Not a compound — stop showing a breakdown
      </button>

      <div>
        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
          Different split
        </p>
        <div className="space-y-1.5">
          {candidates.segmentations.map((seg, i) => (
            <label key={i} className="flex items-center gap-2 text-xs cursor-pointer">
              <input
                type="radio"
                checked={!noneOfThese && seg.parts.join('|') === segThai.join('|')}
                onChange={() => {
                  setNoneOfThese(false)
                  setSegThai(seg.parts)
                  setGlossChoice({})
                }}
              />
              <span className="thai">{seg.parts.join(' + ')}</span>
              {seg.is_current && <span className="text-[10px] text-gray-400">(current)</span>}
            </label>
          ))}
          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input type="radio" checked={noneOfThese} onChange={() => setNoneOfThese(true)} />
            <span className="text-gray-600">None of these is right</span>
          </label>
        </div>
      </div>

      {noneOfThese ? (
        <div>
          <textarea
            value={flagNote}
            onChange={(e) => setFlagNote(e.target.value)}
            placeholder="What's wrong with the segmentation?"
            rows={2}
            disabled={isSaving}
            className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <div className="flex gap-2 mt-2">
            <button
              onClick={onClose}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={() => onFileFlag(flagNote)}
              disabled={isSaving}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition-colors"
            >
              File flag
            </button>
          </div>
        </div>
      ) : (
        <>
          <div>
            <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Meaning per part
            </p>
            <div className="space-y-2">
              {segThai.map((thai) => {
                const options = candidates.part_glosses[thai] ?? []
                const chosen = currentGlossFor(thai)
                return (
                  <div key={thai}>
                    <p className="thai text-xs text-gray-600 mb-1">{thai}</p>
                    <div className="flex flex-wrap gap-1 items-center">
                      {options.map((opt) => (
                        <button
                          key={opt.gloss}
                          onClick={() =>
                            setGlossChoice((s) => ({ ...s, [thai]: { gloss: opt.gloss, source: opt.source } }))
                          }
                          disabled={isSaving}
                          className={`text-[11px] px-2 py-1 rounded-full border transition-colors ${
                            chosen?.gloss === opt.gloss
                              ? 'bg-amber-600 text-white border-amber-600'
                              : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          {opt.gloss}
                        </button>
                      ))}
                      <button
                        onClick={() => setFreeTextOpen((s) => ({ ...s, [thai]: !s[thai] }))}
                        className="text-[11px] px-2 py-1 rounded-full border border-dashed border-gray-300 text-gray-400 hover:text-gray-600"
                      >
                        other…
                      </button>
                    </div>
                    {freeTextOpen[thai] && (
                      <input
                        onChange={(e) =>
                          setGlossChoice((s) => ({ ...s, [thai]: { gloss: e.target.value, source: 'user' } }))
                        }
                        placeholder="English meaning…"
                        disabled={isSaving}
                        className="mt-1 w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400"
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              onClick={() => onSave(buildParts())}
              disabled={isSaving || segThai.length === 0}
              className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-40 transition-colors"
            >
              Save
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function SimilarCardsSection({
  cards,
  onNavigate,
}: {
  cards: SimilarCard[]
  onNavigate: (id: number) => void
}) {
  return (
    <section>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Similar Cards
      </h3>
      {cards.length === 0 ? (
        <p className="text-xs text-gray-400">No similar cards yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {cards.map((c) => (
            <li key={c.card_id}>
              <button
                onClick={() => onNavigate(c.card_id)}
                className="w-full text-left flex items-center gap-2 group hover:bg-gray-50 rounded-lg px-2 py-1.5 transition-colors"
              >
                <span className="thai text-sm font-medium text-gray-800 group-hover:text-brand-700 truncate flex-1">
                  {c.thai}
                </span>
                <span className="text-xs text-gray-400 truncate hidden sm:block">{c.english}</span>
                <span
                  className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded"
                  style={{
                    background: `hsl(${Math.round(c.similarity * 120)}, 60%, 90%)`,
                    color: `hsl(${Math.round(c.similarity * 120)}, 50%, 35%)`,
                  }}
                >
                  {c.similarity.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Maps raw detection-reason tokens (from CardLink.note, "+"-joined) to human copy. */
function friendlyConfusableReason(note?: string | null): string | null {
  if (!note) return null
  const labels = new Set<string>()
  for (const token of note.split('+')) {
    if (token === 'phonetic' || token === 'tone') labels.add('sounds alike')
    else if (token === 'orthographic') labels.add('looks alike')
  }
  return labels.size > 0 ? Array.from(labels).join(', ') : null
}

function LinksSection({ links }: { links: { outgoing: { link_id: number; link_type: string; note?: string | null; card: { id: number; thai: string; english: string } }[]; incoming: { link_id: number; link_type: string; note?: string | null; card: { id: number; thai: string; english: string } }[] } }) {
  const all = [
    ...links.outgoing.map((l) => ({ ...l, direction: 'outgoing' as const })),
    ...links.incoming.map((l) => ({ ...l, direction: 'incoming' as const })),
  ]

  const confusable = all.filter((l) => l.link_type === 'confusable')
  const other = all.filter((l) => l.link_type !== 'confusable')

  if (all.length === 0) return null

  return (
    <>
      {other.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Links
          </h3>
          <ul className="space-y-1.5">
            {other.map((l) => (
              <li
                key={`${l.direction}-${l.link_id}`}
                className="flex items-center gap-2 text-xs text-gray-600"
              >
                <span className="bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded text-[10px] font-medium">
                  {l.link_type}
                </span>
                {l.direction === 'incoming' && (
                  <ArrowRight size={12} className="text-gray-300 rotate-180 shrink-0" />
                )}
                <span className="thai font-medium">{l.card.thai}</span>
                <span className="text-gray-400">— {l.card.english}</span>
                {l.direction === 'outgoing' && (
                  <ArrowRight size={12} className="text-gray-300 shrink-0" />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {confusable.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">
            Easily confused with
          </h3>
          <ul className="space-y-1.5">
            {confusable.map((l) => (
              <li
                key={`${l.direction}-${l.link_id}`}
                className="flex items-center gap-2 text-xs text-gray-600"
              >
                <span className="thai font-medium">{l.card.thai}</span>
                <span className="text-gray-400">— {l.card.english}</span>
                {friendlyConfusableReason(l.note) && (
                  <span className="text-[10px] text-gray-400 italic ml-auto shrink-0">
                    {friendlyConfusableReason(l.note)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
