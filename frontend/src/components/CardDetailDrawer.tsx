import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { X, Plus, ArrowRight, ChevronLeft } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import type { CardDetail, SimilarCard, Tag, Topic } from '../types'

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

  const { data: card, isLoading } = useQuery<CardDetail>(
    ['card', cardId],
    () => api.get(`/cards/${cardId}`).then((r) => r.data),
    { enabled: cardId !== null }
  )

  const invalidate = () => {
    qc.invalidateQueries(['card', cardId])
    if (deckId !== undefined) qc.invalidateQueries(['cards', deckId])
  }

  const { data: similarCards = [] } = useQuery<SimilarCard[]>(
    ['similar-cards', cardId],
    () => api.get(`/cards/${cardId}/similar?limit=10`).then((r) => r.data),
    { enabled: cardId !== null }
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

              {/* Script analysis */}
              {card.script_analysis && card.script_analysis.length > 0 && (
                <ScriptAnalysisSection syllables={card.script_analysis} />
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

function LinksSection({ links }: { links: { outgoing: { link_id: number; link_type: string; card: { id: number; thai: string; english: string } }[]; incoming: { link_id: number; link_type: string; card: { id: number; thai: string; english: string } }[] } }) {
  const all = [
    ...links.outgoing.map((l) => ({ ...l, direction: 'outgoing' as const })),
    ...links.incoming.map((l) => ({ ...l, direction: 'incoming' as const })),
  ]

  if (all.length === 0) return null

  return (
    <section>
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Links
      </h3>
      <ul className="space-y-1.5">
        {all.map((l) => (
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
  )
}
