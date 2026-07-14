import { useState, type MouseEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { Link } from 'react-router-dom'
import { Plus, BookOpen, Zap, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import type { Deck } from '../types'

export default function DecksPage() {
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const qc = useQueryClient()

  const { data: decks = [], isLoading } = useQuery<Deck[]>('decks', () =>
    api.get('/decks/').then((r) => r.data)
  )

  const createDeck = useMutation(
    (name: string) => api.post('/decks/', { name }).then((r) => r.data),
    {
      onSuccess: () => {
        qc.invalidateQueries('decks')
        setShowNew(false)
        setNewName('')
        toast.success('Deck created')
      },
    }
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Decks</h1>
        <button className="btn-primary" onClick={() => setShowNew(true)}>
          <Plus size={16} /> New Deck
        </button>
      </div>

      {showNew && (
        <form
          className="card flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (newName.trim()) createDeck.mutate(newName.trim())
          }}
        >
          <input
            autoFocus
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
            placeholder="Deck name…"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button className="btn-primary" type="submit" disabled={createDeck.isLoading}>
            Create
          </button>
          <button className="btn-secondary" type="button" onClick={() => setShowNew(false)}>
            Cancel
          </button>
        </form>
      )}

      {isLoading ? (
        <p className="text-gray-400">Loading…</p>
      ) : decks.length === 0 ? (
        <div className="card text-center py-16 text-gray-400">
          <BookOpen size={40} className="mx-auto mb-3 opacity-30" />
          <p>No decks yet. Upload some notes or create a deck to start.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {decks.map((deck) => (
            <DeckCard key={deck.id} deck={deck} />
          ))}
        </div>
      )}
    </div>
  )
}

function DeckCard({ deck }: { deck: Deck }) {
  const [confirming, setConfirming] = useState(false)
  const qc = useQueryClient()

  const deleteDeck = useMutation(
    () => api.delete(`/decks/${deck.id}`),
    {
      onSuccess: () => {
        qc.invalidateQueries('decks')
        toast.success(`"${deck.name}" deleted`)
      },
      onError: () => { toast.error('Failed to delete deck') },
    }
  )

  const handleDeleteClick = (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (confirming) {
      deleteDeck.mutate()
    } else {
      setConfirming(true)
    }
  }

  return (
    <Link
      to={`/decks/${deck.id}`}
      className="card hover:shadow-md transition-shadow block"
      onMouseLeave={() => setConfirming(false)}
    >
      <div className="flex justify-between items-start">
        <div>
          <h2 className="font-semibold text-lg">{deck.name}</h2>
          {deck.description && (
            <p className="text-sm text-gray-500 mt-0.5">{deck.description}</p>
          )}
          <p className="text-xs text-gray-400 mt-2">{deck.card_count} cards</p>
        </div>
        <div className="flex items-center gap-2">
          {deck.due_count > 0 && (
            <Link
              to={`/decks/${deck.id}/review`}
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 bg-brand-600 text-white text-xs px-3 py-1.5 rounded-lg hover:bg-brand-700 transition-colors"
            >
              <Zap size={12} />
              {deck.due_count} due
            </Link>
          )}
          <button
            onClick={handleDeleteClick}
            disabled={deleteDeck.isLoading}
            className={`flex items-center gap-1 text-xs px-2 py-1.5 rounded-lg border transition-colors ${
              confirming
                ? 'border-red-300 bg-red-50 text-red-600 hover:bg-red-100'
                : 'border-gray-200 text-gray-400 hover:border-red-300 hover:text-red-500'
            }`}
            title={confirming ? 'Click again to confirm' : 'Delete deck'}
          >
            <Trash2 size={13} />
            {confirming && <span className="ml-1">Confirm?</span>}
          </button>
        </div>
      </div>
    </Link>
  )
}
