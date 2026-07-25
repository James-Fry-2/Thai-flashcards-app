import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from 'react-query'
import {
  ArrowLeft, BookOpen, CheckCircle, AlertCircle,
  Loader2, PlayCircle, Clock,
} from 'lucide-react'
import api from '../services/api'
import type { Upload, ChapterBoundary } from '../types'

export default function BookChaptersPage() {
  const { uploadId } = useParams<{ uploadId: string }>()
  const navigate = useNavigate()

  const { data: upload, isLoading, isError } = useQuery<Upload>(
    ['upload', Number(uploadId)],
    () => api.get(`/uploads/${uploadId}`).then((r) => r.data),
    { refetchInterval: (data) => {
        if (!data) return 4000
        const allDone = data.children?.every(
          (c) => c.status === 'done' || c.status === 'failed'
        )
        return allDone ? false : 4000
      },
    }
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400 gap-2">
        <Loader2 size={18} className="animate-spin" /> Loading…
      </div>
    )
  }

  if (isError || !upload) {
    return (
      <div className="max-w-2xl mx-auto py-10 text-center text-red-500">
        Could not load book.{' '}
        <Link to="/upload" className="underline text-brand-600">Go back</Link>
      </div>
    )
  }

  const title = upload.source_title || upload.filename
  const chapters = (upload.children ?? []).filter((c) => c.include !== false)

  const doneCount = chapters.filter((c) => c.status === 'done').length
  const totalDue = chapters.reduce((sum, c) => sum + (c.due_count ?? 0), 0)

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <button
          onClick={() => navigate('/upload')}
          className="mt-1 text-gray-400 hover:text-gray-600"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-sm text-gray-400 mb-1">
            <BookOpen size={14} />
            <span>Book import</span>
          </div>
          <h1 className="text-xl font-bold text-gray-900 truncate">{title}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {doneCount} of {chapters.length} chapters ready
            {totalDue > 0 && (
              <span className="ml-2 text-brand-600 font-medium">{totalDue} cards due</span>
            )}
          </p>
        </div>
      </div>

      {/* Chapter list */}
      {chapters.length === 0 ? (
        <div className="card text-center text-gray-400 py-10">
          No chapters found. The book may still be processing.
        </div>
      ) : (
        <ul className="space-y-2">
          {chapters.map((chapter, i) => (
            <ChapterRow
              key={chapter.idx ?? i}
              chapter={chapter}
              index={i}
              uploadId={Number(uploadId)}
              bookTitle={title}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function ChapterRow({
  chapter,
  index,
  uploadId,
  bookTitle,
}: {
  chapter: ChapterBoundary
  index: number
  uploadId: number
  bookTitle: string
}) {
  const navigate = useNavigate()
  const label = chapter.title_en || chapter.title_th || `Chapter ${index + 1}`
  const isDone = chapter.status === 'done'
  const isFailed = chapter.status === 'failed'
  const isProcessing = chapter.status === 'processing' || chapter.status === 'pending'
  const dueCount = chapter.due_count ?? 0
  const cardCount = chapter.card_count ?? chapter.cards_created ?? 0

  const handleStudy = () => {
    if (!chapter.child_upload_id) return
    navigate(`/uploads/${chapter.child_upload_id}/review`, {
      state: {
        title: label,
        backTo: `/uploads/${uploadId}/chapters`,
      },
    })
  }

  return (
    <li className="card flex items-center gap-3 py-3 px-4">
      {/* Status icon */}
      <div className="shrink-0">
        {isDone && <CheckCircle size={18} className="text-green-500" />}
        {isFailed && <AlertCircle size={18} className="text-red-400" />}
        {isProcessing && <Loader2 size={18} className="text-brand-400 animate-spin" />}
        {!isDone && !isFailed && !isProcessing && (
          <span className="block w-4.5 h-4.5 rounded-full border-2 border-gray-200" />
        )}
      </div>

      {/* Title + meta */}
      <div className="flex-1 min-w-0">
        <p className="font-medium text-gray-800 truncate">{label}</p>
        {chapter.title_th && chapter.title_en && (
          <p className="text-xs text-gray-400 truncate">{chapter.title_th}</p>
        )}
        {isDone && cardCount > 0 && (
          <p className="text-xs text-gray-400 mt-0.5">{cardCount} cards</p>
        )}
        {isFailed && (
          <p className="text-xs text-red-400 mt-0.5">Processing failed</p>
        )}
        {isProcessing && (
          <p className="text-xs text-gray-400 mt-0.5">
            {chapter.stage ? `${chapter.stage}…` : 'Processing…'}
          </p>
        )}
      </div>

      {/* Due badge + study button */}
      {isDone && chapter.child_upload_id && (
        <div className="flex items-center gap-2 shrink-0">
          {dueCount > 0 && (
            <span className="flex items-center gap-1 text-xs text-brand-600 font-medium bg-brand-50 rounded-full px-2 py-0.5">
              <Clock size={11} />
              {dueCount} due
            </span>
          )}
          <button
            onClick={handleStudy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-600 text-white text-xs font-medium hover:bg-brand-700 transition-colors"
          >
            <PlayCircle size={13} />
            Study
          </button>
        </div>
      )}
    </li>
  )
}
