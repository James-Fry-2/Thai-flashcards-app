import { useState, useRef, useEffect, type ReactNode } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import {
  Pencil,
  Trash2,
  GitMerge,
  X,
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import CardDetailDrawer from '../components/CardDetailDrawer'
import type { Topic, Tag, TopicDuplicatePair, TagDuplicatePair, TopicTreeNode, TopicSummary, Card } from '../types'

type TabId = 'topics' | 'tags'
type Mode = 'browse' | 'curation'

const PAGE_SIZE = 50

interface CardsPage {
  items: Card[]
  total: number
  offset: number
  limit: number
}

export default function TopicsPage() {
  const { topicId } = useParams<{ topicId?: string }>()
  const selectedTopicId = topicId ? Number(topicId) : null
  const [mode, setMode] = useState<Mode>('browse')

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Topics</h1>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          <ModeButton active={mode === 'browse'} onClick={() => setMode('browse')}>
            Browse
          </ModeButton>
          <ModeButton active={mode === 'curation'} onClick={() => setMode('curation')}>
            Curation
          </ModeButton>
        </div>
      </div>

      {mode === 'browse' ? (
        <BrowseView selectedTopicId={selectedTopicId} />
      ) : (
        <CurationView />
      )}
    </div>
  )
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
        active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
      }`}
    >
      {children}
    </button>
  )
}

// ─── Browse view ─────────────────────────────────────────────────────────────

function BrowseView({ selectedTopicId }: { selectedTopicId: number | null }) {
  return (
    <div className="grid grid-cols-3 gap-6 items-start">
      <div className="col-span-1">
        <TopicTree selectedId={selectedTopicId} />
      </div>
      <div className="col-span-2">
        {selectedTopicId ? (
          <TopicDetailPanel topicId={selectedTopicId} />
        ) : (
          <div className="card text-center py-16 text-gray-400 text-sm">
            Select a topic from the tree to browse its cards.
          </div>
        )}
      </div>
    </div>
  )
}

function TopicTree({ selectedId }: { selectedId: number | null }) {
  const { data: tree = [] } = useQuery<TopicTreeNode[]>('topic-tree', () =>
    api.get('/topics/tree').then((r) => r.data)
  )

  return (
    <div className="card p-2 space-y-0.5">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-2 py-1.5">
        Topic tree
      </p>
      {tree.length === 0 ? (
        <p className="text-sm text-gray-400 px-2 py-3">No topics yet.</p>
      ) : (
        tree.map((node) => (
          <TopicTreeNode key={node.id} node={node} selectedId={selectedId} depth={0} />
        ))
      )}
    </div>
  )
}

function TopicTreeNode({
  node,
  selectedId,
  depth,
}: {
  node: TopicTreeNode
  selectedId: number | null
  depth: number
}) {
  const navigate = useNavigate()
  const hasChildren = node.children && node.children.length > 0
  const [expanded, setExpanded] = useState(true)
  const isSelected = node.id === selectedId

  return (
    <div>
      <div
        className={`flex items-center gap-1 rounded-lg px-2 py-1.5 cursor-pointer group transition-colors ${
          isSelected
            ? 'bg-brand-100 text-brand-700'
            : 'hover:bg-gray-100 text-gray-700'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          className={`shrink-0 w-4 h-4 flex items-center justify-center text-gray-400 ${
            !hasChildren ? 'invisible' : ''
          }`}
          onClick={(e) => {
            e.stopPropagation()
            setExpanded((v) => !v)
          }}
        >
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <button
          className="flex-1 text-left text-sm font-medium truncate"
          onClick={() => navigate(`/topics/${node.id}`)}
        >
          {node.name}
        </button>
        <span className="shrink-0 text-xs text-gray-400">{node.card_count}</span>
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TopicTreeNode key={child.id} node={child} selectedId={selectedId} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function TopicDetailPanel({ topicId }: { topicId: number }) {
  const navigate = useNavigate()
  const [page, setPage] = useState(0)
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null)

  const { data: summary } = useQuery<TopicSummary>(
    ['topic-summary', topicId],
    () => api.get(`/topics/${topicId}/summary`).then((r) => r.data)
  )

  const { data: cardsPage, isLoading: cardsLoading } = useQuery<CardsPage>(
    ['topic-cards', topicId, page],
    () =>
      api
        .get(`/topics/${topicId}/cards?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`)
        .then((r) => r.data),
    { keepPreviousData: true }
  )

  // Reset page and card selection when topic changes
  useEffect(() => {
    setPage(0)
    setSelectedCardId(null)
  }, [topicId])

  const cards = cardsPage?.items ?? []
  const total = cardsPage?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const canStudy = ((summary?.due_count ?? 0) + (summary?.new_count ?? 0)) > 0

  const handleStudy = () => {
    navigate(`/topics/${topicId}/review`)
  }

  return (
    <div className="space-y-5">
      {summary ? (
        <>
          {/* Header */}
          <div>
            <h2 className="text-xl font-bold">{summary.name}</h2>
            {summary.description && (
              <p className="text-gray-500 text-sm mt-1">{summary.description}</p>
            )}
          </div>

          {/* Summary row */}
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-gray-600">{summary.card_count} cards</span>
            {summary.due_count > 0 && (
              <span className="font-medium text-brand-600 bg-brand-50 px-2 py-0.5 rounded-full">
                {summary.due_count} due
              </span>
            )}
            <span className="text-gray-500">{summary.new_count} new</span>
            {Object.entries(summary.card_type_breakdown).map(([type, count]) => (
              <span
                key={type}
                className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full"
              >
                {type} {count}
              </span>
            ))}
          </div>

          {/* Decks represented */}
          {summary.decks_represented.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {summary.decks_represented.map((d) => (
                <Link
                  key={d.deck_id}
                  to={`/decks/${d.deck_id}`}
                  className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-2.5 py-1 rounded-lg transition-colors"
                >
                  {d.deck_name} <span className="text-gray-400">({d.card_count})</span>
                </Link>
              ))}
            </div>
          )}

          {/* Study button */}
          <div>
            <button
              className="btn-primary text-sm"
              disabled={!canStudy}
              onClick={handleStudy}
            >
              <Zap size={14} /> Study this topic
            </button>
          </div>
        </>
      ) : (
        <div className="space-y-3">
          <div className="h-6 bg-gray-100 rounded animate-pulse w-48" />
          <div className="h-4 bg-gray-100 rounded animate-pulse w-64" />
        </div>
      )}

      {/* Cards table */}
      <div className="space-y-2">
        {total > 0 && (
          <p className="text-sm text-gray-500">{total} cards</p>
        )}
        {cardsLoading && !cardsPage ? (
          <p className="text-gray-400 text-sm">Loading cards…</p>
        ) : cards.length === 0 ? (
          <div className="card text-center py-8 text-gray-400 text-sm">
            No cards in this topic yet.
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-xl border border-gray-100">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3 text-left">Thai</th>
                    <th className="px-4 py-3 text-left">English</th>
                    <th className="px-4 py-3 text-left">Tags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {cards.map((card) => (
                    <tr
                      key={card.id}
                      className="bg-white hover:bg-gray-50 cursor-pointer"
                      onClick={() => setSelectedCardId(card.id)}
                    >
                      <td className="px-4 py-3 thai font-medium text-base">{card.thai}</td>
                      <td className="px-4 py-3 text-gray-700">{card.english}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                            {card.card_type}
                          </span>
                          {card.tags?.map((t) => (
                            <span
                              key={t.id}
                              className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full"
                            >
                              {t.name}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 pt-2">
                <button
                  className="btn-secondary text-sm flex items-center gap-1 disabled:opacity-40"
                  onClick={() => setPage((p) => p - 1)}
                  disabled={page === 0}
                >
                  Prev
                </button>
                <div className="flex gap-1">
                  {Array.from({ length: totalPages }, (_, i) => (
                    <button
                      key={i}
                      className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${
                        i === page
                          ? 'bg-brand-600 text-white'
                          : 'text-gray-500 hover:bg-gray-100'
                      }`}
                      onClick={() => setPage(i)}
                    >
                      {i + 1}
                    </button>
                  ))}
                </div>
                <button
                  className="btn-secondary text-sm flex items-center gap-1 disabled:opacity-40"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={page >= totalPages - 1}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <CardDetailDrawer
        cardId={selectedCardId}
        onClose={() => setSelectedCardId(null)}
      />
    </div>
  )
}

// ─── Curation view (existing taxonomy management UI) ─────────────────────────

function CurationView() {
  const [activeTab, setActiveTab] = useState<TabId>('topics')

  return (
    <div className="space-y-6">
      <div className="flex border-b border-gray-200">
        <TabButton active={activeTab === 'topics'} onClick={() => setActiveTab('topics')}>
          Topics
        </TabButton>
        <TabButton active={activeTab === 'tags'} onClick={() => setActiveTab('tags')}>
          Tags
        </TabButton>
      </div>
      {activeTab === 'topics' ? <TopicsTab /> : <TagsTab />}
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-brand-600 text-brand-700'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

// ─── Topics tab ──────────────────────────────────────────────────────────────

function TopicsTab() {
  const qc = useQueryClient()

  const { data: topics = [], isLoading } = useQuery<Topic[]>('topics', () =>
    api.get('/topics').then((r) => r.data)
  )

  const { data: duplicates = [] } = useQuery<TopicDuplicatePair[]>(
    'topic-duplicates',
    () => api.get('/topics/duplicates').then((r) => r.data)
  )

  const [mergeSource, setMergeSource] = useState<Topic | null>(null)

  const invalidate = () => {
    qc.invalidateQueries('topics')
    qc.invalidateQueries('topic-duplicates')
    qc.invalidateQueries('topic-tree')
  }

  const renameTopic = useMutation(
    ({ id, name }: { id: number; name: string }) =>
      api.patch(`/topics/${id}`, { name }).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Topic renamed')
      },
    }
  )

  const deleteTopic = useMutation(
    (id: number) => api.delete(`/topics/${id}`),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Topic deleted')
      },
    }
  )

  const mergeTopic = useMutation(
    ({ sourceId, targetId }: { sourceId: number; targetId: number }) =>
      api.post(`/topics/${sourceId}/merge`, { target_id: targetId }).then((r) => r.data),
    {
      onSuccess: (data) => {
        invalidate()
        setMergeSource(null)
        toast.success(
          `Merged: ${data.cards_moved} cards moved, ${data.cards_already_present} already in target`
        )
      },
    }
  )

  return (
    <div className="space-y-8">
      {duplicates.length > 0 && (
        <section>
          <SectionHeader icon count={duplicates.length}>
            Potential duplicates
          </SectionHeader>
          <div className="card p-0 divide-y divide-gray-50">
            {duplicates.map((pair) => (
              <DuplicateRow
                key={`${pair.topic_a.id}-${pair.topic_b.id}`}
                nameA={pair.topic_a.name}
                countA={pair.topic_a.card_count}
                nameB={pair.topic_b.name}
                countB={pair.topic_b.card_count}
                reason={pair.reason}
                onMerge={() => {
                  const t = topics.find((t) => t.id === pair.topic_a.id)
                  if (t) setMergeSource(t)
                }}
              />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">All topics</h2>
        {isLoading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : topics.length === 0 ? (
          <div className="card text-center py-12 text-gray-400 text-sm">
            No topics yet. Topics are created automatically during card tagging.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-100">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-right">Cards</th>
                  <th className="px-4 py-3 text-right">Avg difficulty</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {topics.map((topic) => (
                  <TopicRow
                    key={topic.id}
                    topic={topic}
                    onRename={(name) => renameTopic.mutate({ id: topic.id, name })}
                    onMerge={() => setMergeSource(topic)}
                    onDelete={(id) => deleteTopic.mutate(id)}
                    isDeleting={deleteTopic.isLoading}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {mergeSource && (
        <MergeModal
          title={`Merge "${mergeSource.name}" into another topic`}
          sourceCardCount={mergeSource.card_count}
          sourceName={mergeSource.name}
          items={topics
            .filter((t) => t.id !== mergeSource.id)
            .map((t) => ({ id: t.id, name: t.name, card_count: t.card_count }))}
          searchPlaceholder="Search topics…"
          entityLabel="topic"
          onClose={() => setMergeSource(null)}
          onConfirm={(targetId) =>
            mergeTopic.mutate({ sourceId: mergeSource.id, targetId })
          }
          isMerging={mergeTopic.isLoading}
        />
      )}
    </div>
  )
}

function TopicRow({
  topic,
  onRename,
  onMerge,
  onDelete,
  isDeleting,
}: {
  topic: Topic
  onRename: (name: string) => void
  onMerge: () => void
  onDelete: (id: number) => void
  isDeleting: boolean
}) {
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(topic.name)
  const [confirming, setConfirming] = useState(false)

  const submitRename = () => {
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === topic.name) {
      setRenaming(false)
      setRenameValue(topic.name)
      return
    }
    onRename(trimmed)
    setRenaming(false)
  }

  return (
    <tr
      className="bg-white hover:bg-gray-50 group"
      onMouseLeave={() => setConfirming(false)}
    >
      <td className="px-4 py-3">
        {renaming ? (
          <InlineRename
            value={renameValue}
            onChange={setRenameValue}
            onSubmit={submitRename}
            onCancel={() => {
              setRenaming(false)
              setRenameValue(topic.name)
            }}
          />
        ) : (
          <>
            <span className="font-medium">{topic.name}</span>
            {topic.description && (
              <p className="text-xs text-gray-400 mt-0.5">{topic.description}</p>
            )}
          </>
        )}
      </td>
      <td className="px-4 py-3 text-right text-gray-600">{topic.card_count}</td>
      <td className="px-4 py-3 text-right text-gray-400">
        {topic.avg_fsrs_difficulty != null
          ? topic.avg_fsrs_difficulty.toFixed(2)
          : '—'}
      </td>
      <td className="px-4 py-3">
        <RowActions
          onRename={() => {
            setRenameValue(topic.name)
            setRenaming(true)
          }}
          onMerge={onMerge}
          confirming={confirming}
          onDeleteClick={() => {
            if (confirming) onDelete(topic.id)
            else setConfirming(true)
          }}
          isDeleting={isDeleting}
          cardCount={topic.card_count}
        />
      </td>
    </tr>
  )
}

// ─── Tags tab ─────────────────────────────────────────────────────────────────

function TagsTab() {
  const qc = useQueryClient()

  const { data: tags = [], isLoading } = useQuery<Tag[]>('tags', () =>
    api.get('/tags').then((r) => r.data)
  )

  const { data: duplicates = [] } = useQuery<TagDuplicatePair[]>(
    'tag-duplicates',
    () => api.get('/tags/duplicates').then((r) => r.data)
  )

  const [mergeSource, setMergeSource] = useState<Tag | null>(null)

  const invalidate = () => {
    qc.invalidateQueries('tags')
    qc.invalidateQueries('tag-duplicates')
  }

  const renameTag = useMutation(
    ({ id, name }: { id: number; name: string }) =>
      api.patch(`/tags/${id}`, { name }).then((r) => r.data),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Tag renamed')
      },
    }
  )

  const deleteTag = useMutation(
    (id: number) => api.delete(`/tags/${id}`),
    {
      onSuccess: () => {
        invalidate()
        toast.success('Tag deleted')
      },
    }
  )

  const mergeTag = useMutation(
    ({ sourceId, targetId }: { sourceId: number; targetId: number }) =>
      api.post(`/tags/${sourceId}/merge`, { target_id: targetId }).then((r) => r.data),
    {
      onSuccess: (data) => {
        invalidate()
        setMergeSource(null)
        toast.success(
          `Merged: ${data.cards_moved} cards moved, ${data.cards_already_present} already in target`
        )
      },
    }
  )

  return (
    <div className="space-y-8">
      {duplicates.length > 0 && (
        <section>
          <SectionHeader icon count={duplicates.length}>
            Potential duplicates
          </SectionHeader>
          <div className="card p-0 divide-y divide-gray-50">
            {duplicates.map((pair) => (
              <DuplicateRow
                key={`${pair.tag_a.id}-${pair.tag_b.id}`}
                nameA={pair.tag_a.name}
                countA={pair.tag_a.card_count}
                nameB={pair.tag_b.name}
                countB={pair.tag_b.card_count}
                reason={pair.reason}
                onMerge={() => {
                  const t = tags.find((t) => t.id === pair.tag_a.id)
                  if (t) setMergeSource(t)
                }}
              />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">All tags</h2>
        {isLoading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : tags.length === 0 ? (
          <div className="card text-center py-12 text-gray-400 text-sm">
            No tags yet. Tags are created automatically during card tagging.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-100">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-right">Cards</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {tags.map((tag) => (
                  <TagRow
                    key={tag.id}
                    tag={tag}
                    onRename={(name) => renameTag.mutate({ id: tag.id, name })}
                    onMerge={() => setMergeSource(tag)}
                    onDelete={(id) => deleteTag.mutate(id)}
                    isDeleting={deleteTag.isLoading}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {mergeSource && (
        <MergeModal
          title={`Merge "${mergeSource.name}" into another tag`}
          sourceCardCount={mergeSource.card_count}
          sourceName={mergeSource.name}
          items={tags
            .filter((t) => t.id !== mergeSource.id)
            .map((t) => ({ id: t.id, name: t.name, card_count: t.card_count }))}
          searchPlaceholder="Search tags…"
          entityLabel="tag"
          onClose={() => setMergeSource(null)}
          onConfirm={(targetId) =>
            mergeTag.mutate({ sourceId: mergeSource.id, targetId })
          }
          isMerging={mergeTag.isLoading}
        />
      )}
    </div>
  )
}

function TagRow({
  tag,
  onRename,
  onMerge,
  onDelete,
  isDeleting,
}: {
  tag: Tag
  onRename: (name: string) => void
  onMerge: () => void
  onDelete: (id: number) => void
  isDeleting: boolean
}) {
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState(tag.name)
  const [confirming, setConfirming] = useState(false)

  const submitRename = () => {
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === tag.name) {
      setRenaming(false)
      setRenameValue(tag.name)
      return
    }
    onRename(trimmed)
    setRenaming(false)
  }

  return (
    <tr
      className="bg-white hover:bg-gray-50 group"
      onMouseLeave={() => setConfirming(false)}
    >
      <td className="px-4 py-3">
        {renaming ? (
          <InlineRename
            value={renameValue}
            onChange={setRenameValue}
            onSubmit={submitRename}
            onCancel={() => {
              setRenaming(false)
              setRenameValue(tag.name)
            }}
          />
        ) : (
          <span className="font-medium">{tag.name}</span>
        )}
      </td>
      <td className="px-4 py-3 text-right text-gray-600">{tag.card_count}</td>
      <td className="px-4 py-3">
        <RowActions
          onRename={() => {
            setRenameValue(tag.name)
            setRenaming(true)
          }}
          onMerge={onMerge}
          confirming={confirming}
          onDeleteClick={() => {
            if (confirming) onDelete(tag.id)
            else setConfirming(true)
          }}
          isDeleting={isDeleting}
          cardCount={tag.card_count}
        />
      </td>
    </tr>
  )
}

// ─── Shared components ────────────────────────────────────────────────────────

function SectionHeader({
  icon,
  count,
  children,
}: {
  icon?: boolean
  count?: number
  children: ReactNode
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      {icon && <AlertTriangle size={16} className="text-amber-500" />}
      <h2 className="text-sm font-semibold text-gray-700">
        {children}
        {count !== undefined && (
          <span className="ml-1.5 text-gray-400 font-normal">({count})</span>
        )}
      </h2>
    </div>
  )
}

function DuplicateRow({
  nameA,
  countA,
  nameB,
  countB,
  reason,
  onMerge,
}: {
  nameA: string
  countA: number
  nameB: string
  countB: number
  reason: string
  onMerge: () => void
}) {
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <div className="flex-1 flex items-center gap-2 min-w-0 text-sm">
        <span className="font-medium truncate">{nameA}</span>
        <span className="text-gray-400 text-xs shrink-0">{countA} cards</span>
        <span className="text-gray-300 shrink-0">·</span>
        <span className="font-medium truncate">{nameB}</span>
        <span className="text-gray-400 text-xs shrink-0">{countB} cards</span>
      </div>
      <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full shrink-0">
        {reason}
      </span>
      <button
        onClick={onMerge}
        className="shrink-0 text-xs text-brand-600 border border-brand-200 hover:bg-brand-50 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1"
      >
        <GitMerge size={12} /> Merge…
      </button>
    </div>
  )
}

function InlineRename({
  value,
  onChange,
  onSubmit,
  onCancel,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  onCancel: () => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      <input
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSubmit()
          if (e.key === 'Escape') onCancel()
        }}
        className="border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 w-48"
      />
      <button onClick={onSubmit} className="text-green-600 hover:text-green-700">
        <Check size={14} />
      </button>
      <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
        <X size={14} />
      </button>
    </div>
  )
}

function RowActions({
  onRename,
  onMerge,
  confirming,
  onDeleteClick,
  isDeleting,
  cardCount,
}: {
  onRename: () => void
  onMerge: () => void
  confirming: boolean
  onDeleteClick: () => void
  isDeleting: boolean
  cardCount: number
}) {
  return (
    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onClick={onRename}
        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg"
        title="Rename"
      >
        <Pencil size={13} />
      </button>
      <button
        onClick={onMerge}
        className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg"
        title="Merge into…"
      >
        <GitMerge size={13} />
      </button>
      <button
        onClick={onDeleteClick}
        disabled={isDeleting}
        className={`flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors ${
          confirming
            ? 'border-red-300 bg-red-50 text-red-600 hover:bg-red-100'
            : 'border-transparent text-gray-400 hover:border-red-300 hover:text-red-500'
        }`}
        title={confirming ? 'Click again to confirm' : 'Delete'}
      >
        <Trash2 size={13} />
        {confirming && (
          <span>{cardCount} cards will be unassigned · Confirm?</span>
        )}
      </button>
    </div>
  )
}

function MergeModal({
  title,
  sourceCardCount,
  sourceName,
  items,
  searchPlaceholder,
  entityLabel,
  onClose,
  onConfirm,
  isMerging,
}: {
  title: string
  sourceCardCount: number
  sourceName: string
  items: Array<{ id: number; name: string; card_count: number }>
  searchPlaceholder: string
  entityLabel: string
  onClose: () => void
  onConfirm: (targetId: number) => void
  isMerging: boolean
}) {
  const [query, setQuery] = useState('')
  const [target, setTarget] = useState<{ id: number; name: string; card_count: number } | null>(
    null
  )
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const choices = items.filter(
    (t) =>
      query.trim() === '' || t.name.toLowerCase().includes(query.toLowerCase())
  )

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} aria-hidden={true} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="bg-white rounded-xl shadow-2xl w-full max-w-md"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900 text-sm">{title}</h2>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
            >
              <X size={16} />
            </button>
          </div>

          <div className="px-6 py-5 space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1.5">
                Merge into
              </label>
              <div className="relative">
                <input
                  ref={inputRef}
                  value={target ? target.name : query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setTarget(null)
                    setDropdownOpen(true)
                  }}
                  onFocus={() => setDropdownOpen(true)}
                  placeholder={searchPlaceholder}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                {target && (
                  <button
                    onClick={() => {
                      setTarget(null)
                      setQuery('')
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X size={14} />
                  </button>
                )}
                {dropdownOpen && !target && choices.length > 0 && (
                  <ul className="absolute z-10 top-full mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                    {choices.slice(0, 10).map((t) => (
                      <li key={t.id}>
                        <button
                          className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center justify-between"
                          onClick={() => {
                            setTarget(t)
                            setDropdownOpen(false)
                          }}
                        >
                          <span>{t.name}</span>
                          <span className="text-xs text-gray-400">{t.card_count} cards</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {target && (
              <div className="bg-gray-50 rounded-lg p-3 space-y-1.5 text-sm text-gray-600">
                <p>
                  Will move up to{' '}
                  <span className="font-medium">{sourceCardCount} cards</span> into "
                  {target.name}". Cards already assigned to the target will be skipped.
                </p>
                <p className="text-xs text-gray-400">
                  Description and parent will only be copied to the target if the target
                  doesn't already have them.
                </p>
                <p className="text-xs text-red-500 font-medium">
                  "{sourceName}" will be deleted.
                </p>
              </div>
            )}
          </div>

          <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
            <button className="btn-secondary text-sm" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn-primary text-sm"
              disabled={!target || isMerging}
              onClick={() => target && onConfirm(target.id)}
            >
              {isMerging ? 'Merging…' : `Merge ${entityLabel}`}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
