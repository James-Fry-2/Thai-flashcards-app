import { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { Download, Zap, Trash2, ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import CardDetailDrawer from '../components/CardDetailDrawer'
import type { Deck, Card } from '../types'

const PAGE_SIZE = 50

interface CardsPage {
  items: Card[]
  total: number
  offset: number
  limit: number
}

export default function DeckDetailPage() {
  const { deckId } = useParams<{ deckId: string }>()
  const id = Number(deckId)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [page, setPage] = useState(0)
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null)

  const offset = page * PAGE_SIZE

  const { data: deck } = useQuery<Deck>(['deck', id], () =>
    api.get(`/decks/${id}`).then((r: { data: Deck }) => r.data)
  )

  const { data, isLoading } = useQuery<CardsPage>(
    ['cards', id, page],
    () =>
      api
        .get(`/decks/${id}/cards?offset=${offset}&limit=${PAGE_SIZE}`)
        .then((r: { data: CardsPage }) => r.data),
    { keepPreviousData: true }
  )

  const cards = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const deleteCard = useMutation(
    (cardId: number) => api.delete(`/cards/${cardId}`),
    {
      onSuccess: () => {
        qc.invalidateQueries(['cards', id])
        qc.invalidateQueries(['deck', id])
        toast.success('Card deleted')
      },
    }
  )

  const deleteDeck = useMutation(
    () => api.delete(`/decks/${id}`),
    {
      onSuccess: () => {
        qc.invalidateQueries('decks')
        toast.success('Deck deleted')
        navigate('/decks')
      },
      onError: () => {
        toast.error('Failed to delete deck')
      },
    }
  )

  const handleExport = () => {
    window.open(`/api/export/decks/${id}/anki`, '_blank')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/decks" className="text-gray-400 hover:text-gray-600">
          <ArrowLeft size={20} />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">{deck?.name}</h1>
          {deck?.description && (
            <p className="text-gray-500 text-sm">{deck.description}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary text-sm" onClick={handleExport}>
            <Download size={14} /> Export Anki
          </button>
          {deck && deck.due_count > 0 && (
            <Link to={`/decks/${id}/review`} className="btn-primary text-sm">
              <Zap size={14} /> Study ({deck.due_count})
            </Link>
          )}
          {confirmingDelete ? (
            <>
              <button
                className="text-sm px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
                onClick={() => deleteDeck.mutate()}
                disabled={deleteDeck.isLoading}
              >
                Confirm delete
              </button>
              <button
                className="btn-secondary text-sm"
                onClick={() => setConfirmingDelete(false)}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              className="btn-secondary text-sm text-gray-400 hover:text-red-500"
              onClick={() => setConfirmingDelete(true)}
              title="Delete deck"
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      {isLoading && !data ? (
        <p className="text-gray-400">Loading cards…</p>
      ) : cards.length === 0 && total === 0 ? (
        <div className="card text-center py-12 text-gray-400">
          No cards yet. Upload notes to generate cards.
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">{total} cards</p>
            {totalPages > 1 && (
              <p className="text-sm text-gray-400">
                Page {page + 1} of {totalPages}
              </p>
            )}
          </div>
          <div className="overflow-hidden rounded-xl border border-gray-100">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Thai</th>
                  <th className="px-4 py-3 text-left">Romanization</th>
                  <th className="px-4 py-3 text-left">English</th>
                  <th className="px-4 py-3 text-left">Tags / Topics</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {cards.map((card) => (
                  <tr
                    key={card.id}
                    className="bg-white hover:bg-gray-50 cursor-pointer"
                    onClick={() => setSelectedCardId(card.id)}
                  >
                    <td className="px-4 py-3 thai font-medium text-base">
                      {card.thai}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{card.romanization}</td>
                    <td className="px-4 py-3">{card.english}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                          {card.card_type}
                        </span>
                        {card.topics?.map((t) => (
                          <span
                            key={t.id}
                            className="text-xs bg-brand-100 text-brand-700 px-2 py-0.5 rounded-full"
                          >
                            {t.name}
                          </span>
                        ))}
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
                    <td className="px-4 py-3 text-right">
                      <button
                        className="text-gray-300 hover:text-red-500 transition-colors"
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteCard.mutate(card.id)
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
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
                <ChevronLeft size={14} /> Prev
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
                Next <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
      )}

      <CardDetailDrawer
        cardId={selectedCardId}
        deckId={id}
        onClose={() => setSelectedCardId(null)}
      />
    </div>
  )
}
