import { useState } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from 'react-query'
import { BookOpen, Save, X, Tag, Layers } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import CardDetailDrawer from '../components/CardDetailDrawer'
import type { Deck, SearchStudyResult, SearchGroupingItem } from '../types'

function toTitleCase(s: string) {
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

function MatchBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    exact: 'bg-green-100 text-green-700',
    prefix: 'bg-blue-100 text-blue-700',
    substring: 'bg-gray-100 text-gray-600',
    semantic: 'bg-purple-100 text-purple-700',
  }
  const labels: Record<string, string> = {
    exact: 'exact',
    prefix: 'prefix',
    substring: 'match',
    semantic: 'related',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${styles[type] ?? styles.substring}`}>
      {labels[type] ?? type}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Save-as-topic modal
// ---------------------------------------------------------------------------

interface SaveModalProps {
  query: string
  cardIds: number[]
  onClose: () => void
}

function SaveModal({ query, cardIds, onClose }: SaveModalProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [name, setName] = useState(toTitleCase(query))
  const [desc, setDesc] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{
    topic_id: number
    name: string
    created: boolean
    cards_assigned: number
  } | null>(null)

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    try {
      const res = await api.post('/search/save-as-topic', {
        name: name.trim(),
        card_ids: cardIds,
        description: desc.trim() || undefined,
      })
      setResult(res.data)
      qc.invalidateQueries('topics')
    } catch {
      toast.error('Failed to save topic')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {result ? 'Topic saved' : 'Save as topic'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        {result ? (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              {result.created
                ? `Created topic "${result.name}" with ${result.cards_assigned} card${result.cards_assigned !== 1 ? 's' : ''}.`
                : `Added ${result.cards_assigned} card${result.cards_assigned !== 1 ? 's' : ''} to existing topic "${result.name}".`}
            </p>
            <div className="flex gap-2 justify-end">
              <button className="btn-secondary text-sm" onClick={onClose}>
                Close
              </button>
              <button
                className="btn-primary text-sm flex items-center gap-1.5"
                onClick={() => navigate(`/topics/${result.topic_id}/review`)}
              >
                <BookOpen size={14} /> Study topic
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Topic name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                autoFocus
                onKeyDown={(e) => e.key === 'Enter' && handleSave()}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Description <span className="font-normal text-gray-400">(optional)</span>
              </label>
              <input
                type="text"
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <p className="text-xs text-gray-400">
              {cardIds.length} card{cardIds.length !== 1 ? 's' : ''} will be added.
              If a topic with this name already exists, cards will be merged into it.
            </p>
            <div className="flex gap-2 justify-end pt-1">
              <button className="btn-secondary text-sm" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn-primary text-sm flex items-center gap-1.5 disabled:opacity-40"
                onClick={handleSave}
                disabled={saving || !name.trim()}
              >
                <Save size={14} />
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Grouping row
// ---------------------------------------------------------------------------

interface GroupingRowProps {
  item: SearchGroupingItem
  kind: 'topic' | 'tag'
  onStudy: () => void
  studyLoading: boolean
}

function GroupingRow({ item, kind, onStudy, studyLoading }: GroupingRowProps) {
  return (
    <div className="flex items-center justify-between py-2.5 px-4 hover:bg-gray-50 rounded-lg transition-colors">
      <div className="flex items-center gap-2 min-w-0">
        {kind === 'topic' ? (
          <Link
            to={`/topics/${item.id}`}
            className="font-medium text-gray-800 hover:text-brand-600 truncate"
          >
            {item.name}
          </Link>
        ) : (
          <span className="font-medium text-gray-800 truncate">{item.name}</span>
        )}
        <MatchBadge type={item.match_type === 'semantic' ? 'semantic' : 'match'} />
        <span className="text-xs text-gray-400">{item.card_count} cards</span>
      </div>
      <button
        onClick={onStudy}
        disabled={studyLoading || item.card_count === 0}
        className="btn-primary text-xs flex items-center gap-1 py-1 px-3 shrink-0 disabled:opacity-40 disabled:cursor-not-allowed ml-4"
      >
        <BookOpen size={12} />
        {studyLoading ? 'Starting…' : 'Study'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SearchPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const q = searchParams.get('q') ?? ''
  const deckIdParam = searchParams.get('deck_id')
  const cardTypeParam = searchParams.get('card_type')

  const [deckFilter, setDeckFilter] = useState<string>(deckIdParam ?? '')
  const [typeFilter, setTypeFilter] = useState<string>(cardTypeParam ?? '')
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null)
  const [showSaveModal, setShowSaveModal] = useState(false)
  const [studyingId, setStudyingId] = useState<number | null>(null)
  const [studyingAdhoc, setStudyingAdhoc] = useState(false)

  const { data: decks } = useQuery<Deck[]>('decks', () =>
    api.get('/decks').then((r: { data: Deck[] }) => r.data)
  )

  const searchKey = ['study-search', q, deckFilter, typeFilter]
  const { data, isLoading } = useQuery<SearchStudyResult>(
    searchKey,
    () => {
      const params = new URLSearchParams({ q })
      if (deckFilter) params.set('deck_id', deckFilter)
      if (typeFilter) params.set('card_type', typeFilter)
      return api.get(`/search/study?${params}`).then((r: { data: SearchStudyResult }) => r.data)
    },
    { enabled: q.trim().length > 0, keepPreviousData: true }
  )

  // Navigate to /search with updated filter params without resetting the q
  function applyFilter(key: string, value: string) {
    const params = new URLSearchParams(searchParams)
    if (value) params.set(key, value)
    else params.delete(key)
    navigate(`/search?${params}`)
  }

  // Study a topic: navigate to topic review route; ReviewPage starts the session
  function handleStudyTopic(topicId: number) {
    navigate(`/topics/${topicId}/review`)
  }

  // Study a tag: fetch cards, POST from-cards session, navigate to search/review
  async function handleStudyTag(tag: SearchGroupingItem) {
    setStudyingId(tag.id)
    try {
      const cardsRes = await api.get(`/tags/${tag.id}/cards?limit=200`)
      const cardIds = (cardsRes.data as { id: number }[]).map((c) => c.id)
      if (!cardIds.length) {
        toast.error('No cards found for this tag')
        return
      }
      const res = await api.post('/review/session/from-cards', {
        card_ids: cardIds,
        direction: 'th_to_en',
      })
      if (!res.data.cards?.length) {
        toast.error('No studiable cards found — cards may not have schedules yet.')
        return
      }
      navigate('/search/review', {
        state: {
          sessionId: res.data.session_id,
          cards: res.data.cards,
          title: `Tag: ${tag.name}`,
          backTo: `/search?q=${encodeURIComponent(q)}`,
          backLabel: 'Back to search',
          backShortLabel: 'Search',
        },
      })
    } catch {
      toast.error('Failed to start session')
    } finally {
      setStudyingId(null)
    }
  }

  // Study ad-hoc set: POST from-cards session, navigate to search/review
  async function handleStudyAdhoc() {
    if (!data || !data.ad_hoc.card_ids.length) return
    setStudyingAdhoc(true)
    try {
      const res = await api.post('/review/session/from-cards', {
        card_ids: data.ad_hoc.card_ids,
        direction: 'th_to_en',
      })
      if (!res.data.cards?.length) {
        toast.error('No studiable cards found — cards may not have schedules yet.')
        return
      }
      navigate('/search/review', {
        state: {
          sessionId: res.data.session_id,
          cards: res.data.cards,
          title: `"${q}" — ${data.ad_hoc.total} cards`,
          backTo: `/search?q=${encodeURIComponent(q)}`,
          backLabel: 'Back to search',
          backShortLabel: 'Search',
        },
      })
    } catch {
      toast.error('Failed to start session')
    } finally {
      setStudyingAdhoc(false)
    }
  }

  const hasGroupings =
    (data?.groupings.topics.length ?? 0) + (data?.groupings.tags.length ?? 0) > 0
  const hasAdhoc = (data?.ad_hoc.total ?? 0) > 0
  const hasCards = (data?.cards.length ?? 0) > 0

  return (
    <div className="space-y-8">
      {/* Filter row */}
      <div className="flex flex-wrap gap-3 items-center">
        <h1 className="text-xl font-bold text-gray-800 mr-2">
          {q ? `"${q}"` : 'Search'}
        </h1>
        <select
          value={deckFilter}
          onChange={(e) => {
            setDeckFilter(e.target.value)
            applyFilter('deck_id', e.target.value)
          }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">All decks</option>
          {decks?.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter(e.target.value)
            applyFilter('card_type', e.target.value)
          }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          <option value="">All types</option>
          <option value="vocab">Vocab</option>
          <option value="phrase">Phrase</option>
          <option value="grammar">Grammar</option>
        </select>
      </div>

      {/* Empty / loading / no-query states */}
      {!q.trim() && (
        <div className="card text-center py-16 text-gray-400 space-y-2">
          <p className="text-lg font-medium text-gray-600">Find something to study</p>
          <p className="text-sm">Search topics, tags, or browse matching cards to start a session.</p>
        </div>
      )}

      {q.trim() && isLoading && !data && (
        <div className="text-center py-16 text-gray-400">Searching…</div>
      )}

      {q.trim() && !isLoading && data && !hasGroupings && !hasAdhoc && (
        <div className="card text-center py-16 text-gray-400">
          Nothing matches <span className="font-medium text-gray-600">"{q}"</span> yet.
        </div>
      )}

      {/* GROUPINGS */}
      {hasGroupings && (
        <section className="space-y-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Topics &amp; Tags
          </h2>

          {(data?.groupings.topics.length ?? 0) > 0 && (
            <div className="card p-3 space-y-0.5">
              <div className="flex items-center gap-1.5 px-1 mb-1 text-xs font-medium text-gray-500">
                <Layers size={12} /> Topics
              </div>
              {data!.groupings.topics.map((item) => (
                <GroupingRow
                  key={item.id}
                  item={item}
                  kind="topic"
                  onStudy={() => handleStudyTopic(item.id)}
                  studyLoading={false}
                />
              ))}
            </div>
          )}

          {(data?.groupings.tags.length ?? 0) > 0 && (
            <div className="card p-3 space-y-0.5">
              <div className="flex items-center gap-1.5 px-1 mb-1 text-xs font-medium text-gray-500">
                <Tag size={12} /> Tags
              </div>
              {data!.groupings.tags.map((item) => (
                <GroupingRow
                  key={item.id}
                  item={item}
                  kind="tag"
                  onStudy={() => handleStudyTag(item)}
                  studyLoading={studyingId === item.id}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {/* AD-HOC SET */}
      {hasAdhoc && (
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">
            Ad-hoc set
          </h2>
          <div className="card space-y-4">
            <div>
              <p className="text-lg font-semibold text-gray-800">
                {data!.ad_hoc.total} card{data!.ad_hoc.total !== 1 ? 's' : ''} match &ldquo;{q}&rdquo;
              </p>
              {data!.ad_hoc.truncated && (
                <p className="text-xs text-amber-600 mt-0.5">
                  Showing the top {data!.ad_hoc.total} matches (more cards matched but were capped).
                </p>
              )}
              <div className="flex flex-wrap gap-1.5 mt-2">
                {data!.ad_hoc.topic_spread.map((t) => (
                  <span
                    key={t.topic_id}
                    className="text-xs bg-brand-100 text-brand-700 px-2 py-0.5 rounded-full"
                  >
                    {t.topic_name} {t.count}
                  </span>
                ))}
                {data!.ad_hoc.untagged_count > 0 && (
                  <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                    untagged {data!.ad_hoc.untagged_count}
                  </span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleStudyAdhoc}
                disabled={studyingAdhoc}
                className="btn-primary flex items-center gap-1.5 disabled:opacity-40"
              >
                <BookOpen size={15} />
                {studyingAdhoc ? 'Starting…' : `Study these ${data!.ad_hoc.total} cards`}
              </button>
              <button
                onClick={() => setShowSaveModal(true)}
                className="btn-secondary flex items-center gap-1.5"
              >
                <Save size={15} />
                Save as topic…
              </button>
            </div>
          </div>
        </section>
      )}

      {/* CARDS BROWSE */}
      {hasCards && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Cards
            </h2>
            {data!.ad_hoc.truncated && (
              <span className="text-xs text-gray-400">
                {data!.cards.length} shown
              </span>
            )}
          </div>
          <div className="overflow-hidden rounded-xl border border-gray-100">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Thai</th>
                  <th className="px-4 py-3 text-left">Romanization</th>
                  <th className="px-4 py-3 text-left">English</th>
                  <th className="px-4 py-3 text-left">Type / Topics</th>
                  <th className="px-4 py-3 text-left">Match</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data!.cards.map((card) => (
                  <tr
                    key={card.id}
                    onClick={() => setSelectedCardId(card.id)}
                    className="bg-white hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-4 py-3 thai font-medium text-base">{card.thai}</td>
                    <td className="px-4 py-3 text-gray-400">{card.romanization}</td>
                    <td className="px-4 py-3 text-gray-700">{card.english}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                          {card.card_type}
                        </span>
                        {card.topics?.map((t) => (
                          <span key={t.id} className="text-xs bg-brand-100 text-brand-700 px-2 py-0.5 rounded-full">
                            {t.name}
                          </span>
                        ))}
                        {card.tags?.map((t) => (
                          <span key={t.id} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                            {t.name}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <MatchBadge type={card.match_type} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Modals / Drawers */}
      {showSaveModal && data && (
        <SaveModal
          query={q}
          cardIds={data.ad_hoc.card_ids}
          onClose={() => setShowSaveModal(false)}
        />
      )}

      <CardDetailDrawer
        cardId={selectedCardId}
        onClose={() => setSelectedCardId(null)}
      />
    </div>
  )
}
