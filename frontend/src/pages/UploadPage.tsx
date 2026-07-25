import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  CheckCircle, AlertCircle, Loader2, RefreshCw, BookOpen, Upload as UploadIcon,
  ChevronDown, ChevronRight, ArrowRight, Trash2,
} from 'lucide-react'
import { useDropzone } from 'react-dropzone'
import UploadDropzone from '../components/UploadDropzone'
import api from '../services/api'
import { useActiveUploads } from '../hooks/useActiveUploads'
import type { Deck, Upload, ChapterBoundary } from '../types'

// ─── Stage labels ────────────────────────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued…',
  ocr: 'Reading pages…',
  generating: 'Generating cards…',
  tagging: 'Tagging…',
  complete: 'Complete',
  splitting: 'Detecting chapters…',
  awaiting_confirmation: 'Awaiting confirmation',
  dispatching: 'Dispatching chapters…',
}

// ─── Main page ────────────────────────────────────────────────────────────────

type Mode = 'single' | 'book'

export default function UploadPage() {
  const [mode, setMode] = useState<Mode>('single')
  const [selectedDeckId, setSelectedDeckId] = useState<number | ''>('')
  const [sessionUploadId, setSessionUploadId] = useState<number | null>(null)
  const [finalUpload, setFinalUpload] = useState<Upload | null>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const navigatedRef = useRef(false)
  const failedRef = useRef<Set<number>>(new Set())

  const { data: decks = [] } = useQuery<Deck[]>('decks', () =>
    api.get('/decks/').then((r) => r.data)
  )

  const { data: activeUploads = [] } = useActiveUploads()
  const activeSessionUpload = activeUploads.find((u) => u.id === sessionUploadId)

  // When the session upload disappears from the active list, fetch its final state
  useQuery<Upload>(
    ['upload', sessionUploadId],
    () => api.get(`/uploads/${sessionUploadId}`).then((r) => r.data),
    {
      enabled: sessionUploadId != null && activeSessionUpload == null && finalUpload == null,
      onSuccess: (data) => setFinalUpload(data),
    }
  )

  const displayUpload: Upload | undefined =
    activeSessionUpload ?? finalUpload ?? undefined

  // Navigate to deck on single/child completion
  useEffect(() => {
    if (!displayUpload || navigatedRef.current) return
    if (displayUpload.kind === 'single' && displayUpload.status === 'done' && displayUpload.deck_id) {
      const deckId = displayUpload.deck_id
      navigatedRef.current = true
      toast.success(`Done! ${displayUpload.cards_created} cards created`)
      setTimeout(() => navigate(`/decks/${deckId}`), 1500)
    }
  }, [displayUpload, navigate])

  useEffect(() => {
    if (!displayUpload) return
    if (displayUpload.status === 'failed' && !failedRef.current.has(displayUpload.id)) {
      failedRef.current.add(displayUpload.id)
      toast.error(`Upload failed: ${displayUpload.error_message ?? 'unknown error'}`)
    }
  }, [displayUpload])

  const uploadMutation = useMutation(
    async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      if (selectedDeckId) form.append('deck_id', String(selectedDeckId))
      const res = await api.post('/uploads/', form)
      return res.data as { id: number }
    },
    {
      onSuccess: (data) => {
        navigatedRef.current = false
        setFinalUpload(null)
        setSessionUploadId(data.id)
        toast.success('Upload received — processing…')
        qc.invalidateQueries('activeUploads')
      },
    }
  )

  const retryMutation = useMutation(
    (uploadId: number) => api.post(`/uploads/${uploadId}/retry`).then((r) => r.data),
    {
      onSuccess: () => {
        navigatedRef.current = false
        setFinalUpload(null)
        qc.invalidateQueries('activeUploads')
        qc.removeQueries(['upload', sessionUploadId])
        toast.success('Retrying upload…')
      },
    }
  )

  const isProcessing = displayUpload
    ? displayUpload.status === 'pending' || displayUpload.status === 'processing'
    : false

  const onBookSubmitted = (id: number) => {
    navigatedRef.current = false
    setFinalUpload(null)
    setSessionUploadId(id)
    qc.invalidateQueries('activeUploads')
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload Notes</h1>
        <p className="text-gray-500 mt-1">
          Upload Thai learning notes or import a whole book — cards are generated automatically.
        </p>
      </div>

      {/* Mode switcher */}
      <div className="flex gap-2">
        <button
          onClick={() => setMode('single')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
            mode === 'single'
              ? 'bg-brand-600 text-white border-brand-600'
              : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
          }`}
        >
          <UploadIcon size={15} />
          Single file
        </button>
        <button
          onClick={() => setMode('book')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
            mode === 'book'
              ? 'bg-brand-600 text-white border-brand-600'
              : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
          }`}
        >
          <BookOpen size={15} />
          Book import
        </button>
      </div>

      {/* Deck selector (shared) */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Add cards to deck
        </label>
        <select
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          value={selectedDeckId}
          onChange={(e) => setSelectedDeckId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">— No deck (import later) —</option>
          {decks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>

      {mode === 'single' ? (
        <>
          <UploadDropzone
            onFile={(file) => uploadMutation.mutate(file)}
            disabled={uploadMutation.isLoading || isProcessing}
          />

          {displayUpload && displayUpload.kind !== 'book_parent' && (
            <div className="card">
              <StatusDisplay
                upload={displayUpload}
                onRetry={() => retryMutation.mutate(displayUpload.id)}
                retrying={retryMutation.isLoading}
              />
            </div>
          )}
        </>
      ) : (
        <BookImportPanel
          selectedDeckId={selectedDeckId}
          onSubmitted={onBookSubmitted}
        />
      )}

      {/* Book parent progress (shown in either mode) */}
      {displayUpload && displayUpload.kind === 'book_parent' && (
        <div className="card">
          <BookParentStatus
            upload={displayUpload}
            onRetry={() => retryMutation.mutate(displayUpload.id)}
            retrying={retryMutation.isLoading}
          />
        </div>
      )}

      <MyBooks currentUploadId={sessionUploadId} />
    </div>
  )
}

// ─── Single-file status ───────────────────────────────────────────────────────

function StatusDisplay({
  upload,
  onRetry,
  retrying,
}: {
  upload: Upload
  onRetry: () => void
  retrying: boolean
}) {
  if (upload.status === 'done') {
    const hasPageWarning = upload.error_message?.match(/^\d+ page/)
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-3 text-green-700">
          <CheckCircle size={20} />
          <span>
            Complete — <strong>{upload.cards_created}</strong> cards created
            {upload.ocr_engine_used && (
              <span className="text-xs text-gray-400 ml-2">via {upload.ocr_engine_used}</span>
            )}
          </span>
        </div>
        {hasPageWarning && (
          <p className="text-xs text-amber-600 ml-8">{upload.error_message}</p>
        )}
      </div>
    )
  }

  if (upload.status === 'failed') {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3 text-red-600">
          <AlertCircle size={20} />
          <span>{upload.error_message || 'Upload failed'}</span>
        </div>
        <button
          onClick={onRetry}
          disabled={retrying}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
        >
          <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      </div>
    )
  }

  const stageLabel = STAGE_LABELS[upload.stage] ?? `${upload.stage}…`
  const showProgress =
    upload.stage === 'ocr' &&
    upload.total_pages != null &&
    upload.total_pages > 0

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-gray-600">
        <Loader2 size={20} className="animate-spin" />
        <span>{stageLabel}</span>
        {showProgress && (
          <span className="text-xs text-gray-400 ml-auto">
            {upload.pages_processed} / {upload.total_pages} pages
          </span>
        )}
      </div>
      {showProgress && (
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-brand-500 transition-all duration-500"
            style={{ width: `${(upload.pages_processed / upload.total_pages!) * 100}%` }}
          />
        </div>
      )}
    </div>
  )
}

// ─── Book import panel ────────────────────────────────────────────────────────

function BookImportPanel({
  selectedDeckId,
  onSubmitted,
}: {
  selectedDeckId: number | ''
  onSubmitted: (id: number) => void
}) {
  const [files, setFiles] = useState<File[]>([])
  const [sourceTitle, setSourceTitle] = useState('')

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: { 'application/pdf': ['.pdf'] },
    onDrop: (accepted) => setFiles((prev) => [...prev, ...accepted]),
  })

  const bookMutation = useMutation<{ id: number }>(
    async () => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      form.append('source_title', sourceTitle)
      if (selectedDeckId) form.append('deck_id', String(selectedDeckId))
      // Single PDF → pause for review; multiple → auto dispatch
      form.append('auto_dispatch', files.length > 1 ? 'true' : 'false')
      const res = await api.post('/uploads/book', form)
      return res.data as { id: number }
    },
    {
      onSuccess: (data) => {
        toast.success(
          files.length === 1
            ? 'Book received — detecting chapters…'
            : `${files.length} chapters queued for processing…`
        )
        setFiles([])
        setSourceTitle('')
        onSubmitted(data.id)
      },
      onError: () => { toast.error('Book import failed') },
    }
  )

  const removeFile = (i: number) => setFiles((prev) => prev.filter((_, j) => j !== i))

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Book / source title <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          placeholder="e.g. Thai for Beginners"
          value={sourceTitle}
          onChange={(e) => setSourceTitle(e.target.value)}
        />
      </div>

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
          isDragActive
            ? 'border-brand-500 bg-brand-50'
            : 'border-gray-300 hover:border-brand-400 hover:bg-gray-50'
        }`}
      >
        <input {...getInputProps()} />
        <BookOpen className="mx-auto mb-2 text-gray-400" size={32} />
        {isDragActive ? (
          <p className="text-brand-600 font-medium">Drop PDFs here…</p>
        ) : (
          <>
            <p className="font-medium text-gray-700">Drop PDF files here</p>
            <p className="text-sm text-gray-400 mt-1">
              One PDF → chapter detection &amp; review &nbsp;·&nbsp; Multiple PDFs → one chapter each
              &nbsp;·&nbsp; max {300} MB total
            </p>
          </>
        )}
      </div>

      {files.length > 0 && (
        <ul className="space-y-1 text-sm">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between px-3 py-1.5 bg-gray-50 rounded-lg">
              <span className="text-gray-700 truncate">{f.name}</span>
              <button
                onClick={() => removeFile(i)}
                className="ml-2 text-gray-400 hover:text-red-500 shrink-0"
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        onClick={() => bookMutation.mutate()}
        disabled={!files.length || !sourceTitle.trim() || bookMutation.isLoading}
        className="w-full py-2 rounded-lg bg-brand-600 text-white font-medium text-sm hover:bg-brand-700 disabled:opacity-50"
      >
        {bookMutation.isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <Loader2 size={15} className="animate-spin" /> Uploading…
          </span>
        ) : files.length === 1 ? (
          'Import book (detect chapters)'
        ) : (
          `Import ${files.length} chapters`
        )}
      </button>
    </div>
  )
}

// ─── Book parent status (splitting / awaiting_confirmation / dispatching / done) ──

function BookParentStatus({
  upload,
  onRetry,
  retrying,
}: {
  upload: Upload
  onRetry: () => void
  retrying: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const navigate = useNavigate()
  const sourceLabel = upload.source_title || upload.filename

  if (upload.status === 'failed') {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3 text-red-600">
          <AlertCircle size={20} />
          <span>{upload.error_message || 'Book import failed'}</span>
        </div>
        <button
          onClick={onRetry}
          disabled={retrying}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
        >
          <RefreshCw size={14} className={retrying ? 'animate-spin' : ''} />
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      </div>
    )
  }

  // Detection done — user needs to review the split
  if (upload.stage === 'awaiting_confirmation') {
    const boundaryCount = upload.chapter_map?.length ?? 0
    const includeCount = upload.chapter_map?.filter((b) => b.include !== false).length ?? boundaryCount
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-3">
          <BookOpen size={20} className="text-amber-500 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium text-gray-800">Chapters detected — review required</p>
            <p className="text-sm text-gray-500">
              <strong>{sourceLabel}</strong> · {boundaryCount} boundaries found
              {includeCount < boundaryCount && ` · ${includeCount} chapters to generate`}
            </p>
          </div>
        </div>
        <button
          onClick={() => navigate(`/uploads/${upload.id}/split-review`)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700"
        >
          Review &amp; confirm chapters
          <ArrowRight size={14} />
        </button>
      </div>
    )
  }

  const total = upload.chapters_total ?? 0
  const complete = upload.chapters_complete ?? 0
  const failed = upload.chapters_failed ?? 0

  if (upload.status === 'done' || upload.stage === 'complete') {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3 text-green-700">
          <CheckCircle size={20} />
          <span>
            <strong>{sourceLabel}</strong> — {upload.cards_created_total ?? upload.cards_created} cards created
            {total > 0 && <span className="text-xs text-gray-400 ml-2">({complete}/{total} chapters)</span>}
          </span>
        </div>
        <button
          onClick={() => navigate(`/uploads/${upload.id}/chapters`)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700"
        >
          Study a chapter
          <ArrowRight size={14} />
        </button>
      </div>
    )
  }

  const stageLabel = STAGE_LABELS[upload.stage] ?? `${upload.stage}…`

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 text-gray-600">
        <Loader2 size={20} className="animate-spin" />
        <span>
          <strong>{sourceLabel}</strong> — {stageLabel}
          {total > 0 && (
            <span className="text-xs text-gray-400 ml-2">
              {complete}/{total} chapters{failed > 0 ? `, ${failed} failed` : ''}
            </span>
          )}
        </span>
        {total > 1 && (
          <button
            className="ml-auto text-gray-400 hover:text-gray-600"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        )}
      </div>

      {total > 0 && (
        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-brand-500 transition-all duration-500"
            style={{ width: `${(complete / total) * 100}%` }}
          />
        </div>
      )}

      {expanded && upload.children && upload.children.length > 0 && (
        <ChapterList entries={upload.children} />
      )}
    </div>
  )
}

// ─── My Books history ─────────────────────────────────────────────────────────

function MyBooks({ currentUploadId }: { currentUploadId: number | null }) {
  const navigate = useNavigate()

  const { data: books = [] } = useQuery<Upload[]>(
    'bookUploads',
    () => api.get('/uploads/books').then((r) => r.data),
    { refetchInterval: 15_000 }
  )

  // Hide books that are already shown in the current session card above
  const otherBooks = books.filter((b) => b.id !== currentUploadId)
  if (otherBooks.length === 0) return null

  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">My Books</h2>
      <ul className="space-y-2">
        {otherBooks.map((book) => {
          const label = book.source_title || book.filename
          const isDone = book.status === 'done' || book.stage === 'complete'
          const isPending = book.status === 'pending' || book.status === 'processing'
          const total = book.chapters_total ?? 0
          const complete = book.chapters_complete ?? 0
          const cards = book.cards_created_total ?? book.cards_created ?? 0

          return (
            <li key={book.id} className="card flex items-center gap-3 py-3 px-4">
              <BookOpen size={18} className={isDone ? 'text-green-500' : isPending ? 'text-brand-400' : 'text-gray-400'} />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-800 truncate">{label}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {isDone
                    ? `${complete}/${total} chapters · ${cards} cards`
                    : isPending
                    ? `${complete}/${total} chapters processing…`
                    : book.stage === 'awaiting_confirmation'
                    ? 'Awaiting chapter review'
                    : `${complete}/${total} chapters`}
                </p>
              </div>
              {isDone && (
                <button
                  onClick={() => navigate(`/uploads/${book.id}/chapters`)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-50 text-brand-700 text-xs font-medium hover:bg-brand-100 shrink-0"
                >
                  Study a chapter
                  <ArrowRight size={12} />
                </button>
              )}
              {book.stage === 'awaiting_confirmation' && (
                <button
                  onClick={() => navigate(`/uploads/${book.id}/split-review`)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-50 text-amber-700 text-xs font-medium hover:bg-amber-100 shrink-0"
                >
                  Review chapters
                  <ArrowRight size={12} />
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}


// ─── Per-chapter progress list ────────────────────────────────────────────────

function ChapterList({ entries }: { entries: ChapterBoundary[] }) {
  const navigate = useNavigate()

  const statusIcon = (entry: ChapterBoundary) => {
    if (entry.status === 'done') return <CheckCircle size={14} className="text-green-600" />
    if (entry.status === 'failed') return <AlertCircle size={14} className="text-red-500" />
    if (entry.status === 'processing' || entry.status === 'pending')
      return <Loader2 size={14} className="text-brand-500 animate-spin" />
    return <span className="w-3.5 h-3.5 rounded-full border border-gray-300 inline-block" />
  }

  return (
    <ul className="mt-1 space-y-1">
      {entries.map((entry, i) => {
        const label = entry.title_en || entry.title_th || `Chapter ${i + 1}`
        const canStudy = entry.status === 'done' && entry.child_upload_id != null
        const dueCount = entry.due_count ?? 0
        return (
          <li key={i} className="flex items-center gap-2 text-sm text-gray-600 pl-2">
            {statusIcon(entry)}
            <span className="truncate">{label}</span>
            {entry.status === 'done' && entry.cards_created != null && (
              <span className="ml-auto text-xs text-gray-400 shrink-0">
                {entry.cards_created} cards
              </span>
            )}
            {entry.status === 'failed' && (
              <span className="ml-auto text-xs text-red-400 shrink-0">failed</span>
            )}
            {canStudy && (
              <button
                onClick={() =>
                  navigate(`/uploads/${entry.child_upload_id}/review`, {
                    state: { title: label, backTo: '/upload' },
                  })
                }
                className="ml-1 flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-brand-50 text-brand-700 hover:bg-brand-100 shrink-0"
              >
                Study
                {dueCount > 0 && (
                  <span className="bg-brand-600 text-white rounded-full px-1.5 py-px text-[10px] leading-none">
                    {dueCount}
                  </span>
                )}
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}
