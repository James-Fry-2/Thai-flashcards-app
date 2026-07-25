import { useNavigate } from 'react-router-dom'
import { useQuery } from 'react-query'
import { BookOpen, ArrowRight, CheckCircle, Loader2, AlertCircle } from 'lucide-react'
import api from '../services/api'
import type { Upload } from '../types'

export default function BooksPage() {
  const navigate = useNavigate()

  const { data: books = [], isLoading } = useQuery<Upload[]>(
    'bookUploads',
    () => api.get('/uploads/books').then((r) => r.data),
    { refetchInterval: 10_000 }
  )

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Books</h1>
        <p className="text-gray-500 mt-1">Select a book to study its chapters.</p>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 text-gray-400">
          <Loader2 size={16} className="animate-spin" /> Loading…
        </div>
      )}

      {!isLoading && books.length === 0 && (
        <div className="card text-center py-12 text-gray-400">
          <BookOpen size={32} className="mx-auto mb-3 opacity-40" />
          <p className="font-medium">No books imported yet.</p>
          <button
            onClick={() => navigate('/upload')}
            className="mt-4 px-4 py-2 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700"
          >
            Import a book
          </button>
        </div>
      )}

      {books.length > 0 && (
        <ul className="space-y-3">
          {books.map((book) => <BookRow key={book.id} book={book} />)}
        </ul>
      )}
    </div>
  )
}

function BookRow({ book }: { book: Upload }) {
  const navigate = useNavigate()
  const label = book.source_title || book.filename
  const total = book.chapters_total ?? 0
  const complete = book.chapters_complete ?? 0
  const cards = book.cards_created_total ?? book.cards_created ?? 0
  const isDone = book.status === 'done' || book.stage === 'complete'
  const isProcessing = book.status === 'pending' || book.status === 'processing'
  const awaitingReview = book.stage === 'awaiting_confirmation'

  return (
    <li className="card flex items-center gap-4 py-4 px-5">
      {/* Icon */}
      <div className="shrink-0">
        {isDone
          ? <CheckCircle size={22} className="text-green-500" />
          : isProcessing
          ? <Loader2 size={22} className="text-brand-400 animate-spin" />
          : book.status === 'failed'
          ? <AlertCircle size={22} className="text-red-400" />
          : <BookOpen size={22} className="text-amber-400" />}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-gray-900 truncate">{label}</p>
        <p className="text-sm text-gray-400 mt-0.5">
          {isDone
            ? `${complete} of ${total} chapters · ${cards} cards`
            : isProcessing
            ? `${complete}/${total} chapters processing…`
            : awaitingReview
            ? 'Awaiting chapter review'
            : `${complete}/${total} chapters`}
        </p>
      </div>

      {/* Action */}
      {isDone && (
        <button
          onClick={() => navigate(`/uploads/${book.id}/chapters`)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 shrink-0"
        >
          Select chapter
          <ArrowRight size={14} />
        </button>
      )}
      {awaitingReview && (
        <button
          onClick={() => navigate(`/uploads/${book.id}/split-review`)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500 text-white text-sm font-medium hover:bg-amber-600 shrink-0"
        >
          Review chapters
          <ArrowRight size={14} />
        </button>
      )}
    </li>
  )
}
