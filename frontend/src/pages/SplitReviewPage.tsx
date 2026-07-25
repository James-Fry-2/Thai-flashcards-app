/**
 * Split Review — dedicated page for reviewing and correcting chapter boundaries
 * detected by the ensemble detector before a book import is dispatched.
 *
 * Route: /uploads/:uploadId/split-review
 *
 * Workflow:
 *   1. Load split data via GET /uploads/{id}/split
 *   2. User views thumbnail filmstrip grouped by chapter
 *   3. User edits boundaries (add, remove, rename, include/skip)
 *   4. Teach-by-example: click a thumbnail → find all similar pages
 *   5. Confirm via POST /uploads/{id}/confirm-split → redirects to /upload
 */
import { useState, useCallback, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Check, ChevronDown, ChevronRight, Eye, EyeOff,
  Loader2, Plus, RefreshCw, Trash2, Wand2, X, AlertTriangle,
  BookOpen,
} from 'lucide-react'
import api from '../services/api'
import type { ChapterBoundary, SplitData, PageSignals } from '../types'
import { thumbnailUrl } from '../types'

// ---------------------------------------------------------------------------
// Signal badge colours
// ---------------------------------------------------------------------------
const SIGNAL_COLORS: Record<string, string> = {
  font_outlier:   'bg-purple-100 text-purple-700',
  sparse_page:    'bg-blue-100 text-blue-700',
  template_match: 'bg-amber-100 text-amber-700',
  header_change:  'bg-teal-100 text-teal-700',
  lexical_hit:    'bg-green-100 text-green-700',
  topic_shift:    'bg-pink-100 text-pink-700',
  recto_start:    'bg-gray-100 text-gray-500',
  outline:        'bg-indigo-100 text-indigo-700',
  toc_links:      'bg-indigo-100 text-indigo-700',
  page_labels:    'bg-indigo-100 text-indigo-700',
  printed_toc:    'bg-indigo-100 text-indigo-700',
  named_dests:    'bg-indigo-100 text-indigo-700',
}

function SignalBadge({ signal }: { signal: string }) {
  const cls = SIGNAL_COLORS[signal] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${cls}`}>
      {signal.replace(/_/g, ' ')}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Confidence badge
// ---------------------------------------------------------------------------
function ConfidenceBadge({ score, source }: { score: number; source: string }) {
  if (source === 'structure') {
    return <span className="text-xs font-semibold text-indigo-600">structure</span>
  }
  if (source === 'user') {
    return <span className="text-xs text-gray-400">manual</span>
  }
  if (source === 'example_match') {
    return <span className="text-xs font-semibold text-amber-600">example</span>
  }
  const pct = Math.round(score * 100)
  const cls =
    pct >= 70 ? 'text-green-600' :
    pct >= 40 ? 'text-amber-600' :
               'text-red-500'
  return <span className={`text-xs font-medium ${cls}`}>{pct}%</span>
}

// ---------------------------------------------------------------------------
// Single page thumbnail
// ---------------------------------------------------------------------------
interface ThumbnailProps {
  uploadId: number
  page: number
  isStart: boolean           // this page is a chapter start
  isMuted: boolean           // belongs to a skip span
  onAddBefore: () => void    // add a boundary before this page
  onExampleClick: () => void // teach-by-example: "find pages like this"
  signals?: PageSignals
  selected?: boolean
}

function PageThumb({
  uploadId, page, isStart, isMuted, onAddBefore, onExampleClick, signals, selected,
}: ThumbnailProps) {
  const [hovered, setHovered] = useState(false)

  const score = signals?.heuristic_score ?? 0
  const borderCls =
    selected ? 'ring-2 ring-brand-500' :
    isStart  ? 'ring-2 ring-amber-400' :
               'ring-1 ring-gray-200'

  return (
    <div
      className="relative group"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Add-boundary button — appears on hover, sits above the thumbnail */}
      {!isStart && (
        <button
          onClick={onAddBefore}
          title={`Add chapter start at page ${page}`}
          className={`absolute -top-2 left-1/2 -translate-x-1/2 z-10 w-5 h-5 rounded-full
            bg-brand-600 text-white flex items-center justify-center shadow
            transition-opacity ${hovered ? 'opacity-100' : 'opacity-0'}`}
        >
          <Plus size={10} />
        </button>
      )}

      <div className={`relative rounded overflow-hidden ${borderCls} ${isMuted ? 'opacity-40' : ''}`}>
        <img
          loading="lazy"
          src={thumbnailUrl(uploadId, page)}
          alt={`Page ${page}`}
          className="w-12 h-16 object-cover bg-gray-100"
        />
        {/* Page number */}
        <div className="absolute bottom-0 left-0 right-0 bg-black/40 text-white text-[9px] text-center leading-tight py-0.5">
          {page}
        </div>
        {/* High-score indicator dot */}
        {score >= 0.45 && (
          <div className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-amber-400" />
        )}
      </div>

      {/* Example-match button (bottom on hover) */}
      {hovered && (
        <button
          onClick={onExampleClick}
          title="Find pages like this"
          className="absolute -bottom-5 left-1/2 -translate-x-1/2 z-10 whitespace-nowrap
            text-[9px] bg-gray-700 text-white px-1.5 py-0.5 rounded shadow"
        >
          <Wand2 size={8} className="inline mr-0.5" />find similar
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chapter section in the filmstrip
// ---------------------------------------------------------------------------
interface FilmstripChapterProps {
  uploadId: number
  boundary: ChapterBoundary
  nextStart: number | null    // page_start of the next boundary (null = last)
  pageCount: number
  allSignals: Record<string, PageSignals>
  onAddBoundary: (page: number) => void
  onExampleClick: (page: number) => void
  isSelected: boolean
  onClick: () => void
}

function FilmstripChapter({
  uploadId, boundary, nextStart, pageCount, allSignals,
  onAddBoundary, onExampleClick, isSelected, onClick,
}: FilmstripChapterProps) {
  const start = boundary.page_start
  const end = nextStart ? nextStart - 1 : pageCount
  const pages = Array.from({ length: end - start + 1 }, (_, i) => start + i)

  const sectionCls = boundary.include
    ? isSelected ? 'border-brand-400 bg-brand-50' : 'border-gray-200 bg-white'
    : 'border-gray-200 bg-gray-50 opacity-70'

  const label = boundary.title_en || boundary.title_th ||
    `Chapter ${boundary.idx + 1}`

  return (
    <div
      className={`border rounded-lg p-2 cursor-pointer transition-colors ${sectionCls}`}
      onClick={onClick}
    >
      {/* Section header */}
      <div className="flex items-center gap-1.5 mb-2 text-xs">
        {boundary.include
          ? <BookOpen size={12} className="text-brand-500 shrink-0" />
          : <EyeOff size={12} className="text-gray-400 shrink-0" />}
        <span className={`font-medium truncate max-w-[140px] ${boundary.include ? '' : 'text-gray-400'}`}>
          {label}
        </span>
        <span className="text-gray-400 shrink-0">pp {start}–{end}</span>
        <ConfidenceBadge score={boundary.confidence} source={boundary.source} />
      </div>

      {/* Thumbnails */}
      <div className="flex flex-wrap gap-2 mt-1">
        {pages.map((p) => (
          <PageThumb
            key={p}
            uploadId={uploadId}
            page={p}
            isStart={p === start}
            isMuted={!boundary.include}
            onAddBefore={() => onAddBoundary(p)}
            onExampleClick={() => onExampleClick(p)}
            signals={allSignals[String(p)]}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Boundary editor row
// ---------------------------------------------------------------------------
interface BoundaryRowProps {
  boundary: ChapterBoundary
  pageCount: number
  isSelected: boolean
  onSelect: () => void
  onChange: (patch: Partial<ChapterBoundary>) => void
  onDelete: () => void
}

function BoundaryRow({ boundary, pageCount, isSelected, onSelect, onChange, onDelete }: BoundaryRowProps) {
  const rowCls = isSelected
    ? 'bg-brand-50 border-brand-200'
    : boundary.include
      ? 'bg-white border-gray-100'
      : 'bg-gray-50 border-gray-100 opacity-60'

  return (
    <div
      className={`grid items-center gap-2 px-3 py-2 border-b cursor-pointer transition-colors ${rowCls}`}
      style={{ gridTemplateColumns: '28px 70px 1fr 1fr 80px auto 28px' }}
      onClick={onSelect}
    >
      {/* Include toggle */}
      <button
        onClick={(e) => { e.stopPropagation(); onChange({ include: !boundary.include }) }}
        title={boundary.include ? 'Skip this span' : 'Include as chapter'}
        className="flex items-center justify-center"
      >
        {boundary.include
          ? <Eye size={15} className="text-brand-500" />
          : <EyeOff size={15} className="text-gray-400" />}
      </button>

      {/* Page start input */}
      <input
        type="number"
        min={1}
        max={pageCount || undefined}
        value={boundary.page_start}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onChange({ page_start: Number(e.target.value) })}
        className="border border-gray-200 rounded px-1.5 py-1 text-xs w-full"
      />

      {/* English title */}
      <input
        type="text"
        placeholder="English title"
        value={boundary.title_en ?? ''}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onChange({ title_en: e.target.value || null })}
        className="border border-gray-200 rounded px-1.5 py-1 text-xs w-full"
      />

      {/* Thai title */}
      <input
        type="text"
        placeholder="Thai title"
        value={boundary.title_th ?? ''}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onChange({ title_th: e.target.value || null })}
        className="border border-gray-200 rounded px-1.5 py-1 text-xs w-full thai"
      />

      {/* Confidence + signals */}
      <div className="flex flex-wrap gap-0.5">
        <ConfidenceBadge score={boundary.confidence} source={boundary.source} />
        {boundary.signals.slice(0, 2).map((s) => (
          <SignalBadge key={s} signal={s} />
        ))}
        {boundary.signals.length > 2 && (
          <span className="text-[10px] text-gray-400">+{boundary.signals.length - 2}</span>
        )}
      </div>

      {/* Source tag */}
      <span className="text-[10px] text-gray-400 truncate">
        {boundary.source}
      </span>

      {/* Delete (only non-first entries) */}
      {boundary.page_start !== 1
        ? (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            className="text-gray-300 hover:text-red-500 transition-colors"
          >
            <Trash2 size={13} />
          </button>
        )
        : <span />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Teach-by-example proposal panel
// ---------------------------------------------------------------------------
interface ExampleProposal {
  page: number
  score: number
  signals: string[]
}

interface ExamplePanelProps {
  uploadId: number
  examplePage: number
  proposals: ExampleProposal[]
  currentBoundaries: ChapterBoundary[]
  onAccept: (pages: number[], replace: boolean) => void
  onClose: () => void
}

function ExamplePanel({ uploadId, examplePage, proposals, currentBoundaries, onAccept, onClose }: ExamplePanelProps) {
  const [selected, setSelected] = useState<Set<number>>(new Set(proposals.map((p) => p.page)))
  const toggle = (page: number) =>
    setSelected((prev) => { const s = new Set(prev); s.has(page) ? s.delete(page) : s.add(page); return s })

  return (
    <div className="border border-amber-300 bg-amber-50 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-amber-800">
          <Wand2 size={14} className="inline mr-1" />
          Pages similar to page {examplePage} — {proposals.length} found
        </p>
        <button onClick={onClose}><X size={15} className="text-gray-400 hover:text-gray-600" /></button>
      </div>

      <div className="flex flex-wrap gap-2">
        {proposals.map((m) => {
          const isSel = selected.has(m.page)
          const alreadyBoundary = currentBoundaries.some((b) => b.page_start === m.page)
          return (
            <div
              key={m.page}
              onClick={() => toggle(m.page)}
              className={`relative cursor-pointer rounded border-2 transition-colors ${
                isSel ? 'border-amber-400' : 'border-gray-200'
              } ${alreadyBoundary ? 'opacity-40' : ''}`}
            >
              <img
                loading="lazy"
                src={thumbnailUrl(uploadId, m.page)}
                alt={`Page ${m.page}`}
                className="w-12 h-16 object-cover bg-gray-100"
              />
              <div className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[9px] text-center py-0.5">
                p{m.page} · {Math.round(m.score * 100)}%
              </div>
              {isSel && !alreadyBoundary && (
                <div className="absolute top-0.5 right-0.5 w-3 h-3 rounded-full bg-amber-400 flex items-center justify-center">
                  <Check size={8} className="text-white" />
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onAccept(Array.from(selected), false)}
          disabled={selected.size === 0}
          className="px-3 py-1.5 text-xs rounded-lg bg-amber-500 text-white font-medium hover:bg-amber-600 disabled:opacity-50"
        >
          Add selected as boundaries ({selected.size})
        </button>
        <button
          onClick={() => onAccept(Array.from(selected), true)}
          disabled={selected.size === 0}
          className="px-3 py-1.5 text-xs rounded-lg border border-amber-400 text-amber-700 hover:bg-amber-100 disabled:opacity-50"
        >
          Replace auto-boundaries with selected
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cost preview
// ---------------------------------------------------------------------------
function CostPreview({ boundaries }: { boundaries: ChapterBoundary[] }) {
  const included = boundaries.filter((b) => b.include)
  const skipped = boundaries.filter((b) => !b.include)
  return (
    <div className="text-sm text-gray-500 bg-gray-50 rounded-lg px-4 py-2.5 flex items-center gap-2">
      <BookOpen size={14} className="shrink-0" />
      <span>
        <strong className="text-gray-700">{included.length}</strong>{' '}
        {included.length === 1 ? 'chapter' : 'chapters'} → {included.length} generation{' '}
        {included.length === 1 ? 'call' : 'calls'}
        {skipped.length > 0 && (
          <span className="ml-2 text-gray-400">
            · {skipped.length} span{skipped.length > 1 ? 's' : ''} skipped (no LLM cost)
          </span>
        )}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function SplitReviewPage() {
  const { uploadId } = useParams<{ uploadId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const id = Number(uploadId)

  const { data: splitData, isLoading, isError } = useQuery<SplitData>(
    ['split', id],
    () => api.get(`/uploads/${id}/split`).then((r) => r.data),
    { retry: 1, refetchOnWindowFocus: false },
  )

  // Local boundaries state (user's working copy)
  const [boundaries, setBoundaries] = useState<ChapterBoundary[]>([])
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  const initialised = useRef(false)

  useEffect(() => {
    if (splitData && !initialised.current) {
      setBoundaries(splitData.boundaries.map((b) => ({ ...b })))
      initialised.current = true
    }
  }, [splitData])

  // Teach-by-example state
  const [examplePage, setExamplePage] = useState<number | null>(null)
  const [exampleProposals, setExampleProposals] = useState<ExampleProposal[]>([])

  // ----- mutations -----

  const saveMutation = useMutation(
    (bs: ChapterBoundary[]) =>
      api.put(`/uploads/${id}/split`, { boundaries: bs }).then((r) => r.data),
    {
      onSuccess: (data) => {
        setBoundaries(data.boundaries)
        setDirty(false)
        toast.success('Saved')
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.detail ?? 'Save failed')
      },
    },
  )

  const confirmMutation = useMutation(
    (bs: ChapterBoundary[]) =>
      api.post(`/uploads/${id}/confirm-split`, { boundaries: bs }).then((r) => r.data),
    {
      onSuccess: () => {
        toast.success('Chapters confirmed — generating cards…')
        qc.invalidateQueries('activeUploads')
        navigate('/upload')
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.detail ?? 'Confirmation failed')
      },
    },
  )

  const exampleMutation = useMutation(
    (page: number) =>
      api.post(`/uploads/${id}/match-example`, { page }).then((r) => r.data),
    {
      onSuccess: (data, page) => {
        setExamplePage(page)
        setExampleProposals(data.matches ?? [])
        if ((data.matches ?? []).length === 0) {
          toast('No similar pages found above threshold', { icon: '🔍' })
        }
      },
      onError: (err: any) => {
        toast.error(err?.response?.data?.detail ?? 'Match failed')
      },
    },
  )

  // ----- boundary mutation helpers -----

  const updateBoundary = useCallback((idx: number, patch: Partial<ChapterBoundary>) => {
    setBoundaries((prev) => {
      const next = prev.map((b, i) =>
        i === idx ? ({ ...b, ...patch, source: 'user' as const }) : b
      )
      return next
    })
    setDirty(true)
  }, [])

  const deleteBoundary = useCallback((idx: number) => {
    setBoundaries((prev) => {
      const next = prev.filter((_, i) => i !== idx)
        .map((b, i) => ({ ...b, idx: i }))
      return next
    })
    setDirty(true)
    setSelectedIdx(null)
  }, [])

  const addBoundary = useCallback((page: number) => {
    setBoundaries((prev) => {
      if (prev.some((b) => b.page_start === page)) return prev
      const next = [
        ...prev,
        {
          idx: 0,
          page_start: page,
          title_en: null,
          title_th: null,
          include: true,
          confidence: 0,
          signals: [],
          source: 'user' as const,
          child_upload_id: null,
        },
      ]
        .sort((a, b) => a.page_start - b.page_start)
        .map((b, i) => ({ ...b, idx: i }))
      return next
    })
    setDirty(true)
  }, [])

  const acceptExampleProposals = useCallback((pages: number[], replace: boolean) => {
    setBoundaries((prev) => {
      const autoOnly = replace
        ? prev.filter((b) => b.source === 'user' || b.page_start === 1)
        : [...prev]

      const existing = new Set(autoOnly.map((b) => b.page_start))
      for (const page of pages) {
        if (!existing.has(page)) {
          autoOnly.push({
            idx: 0,
            page_start: page,
            title_en: null,
            title_th: null,
            include: true,
            confidence: 0,
            signals: [],
            source: 'example_match' as const,
            child_upload_id: null,
          })
        }
      }
      return autoOnly
        .sort((a, b) => a.page_start - b.page_start)
        .map((b, i) => ({ ...b, idx: i }))
    })
    setDirty(true)
    setExamplePage(null)
    setExampleProposals([])
  }, [])

  const reRunDetection = useCallback(async () => {
    const userEdited = boundaries.some((b) => b.source === 'user' || b.source === 'example_match')
    if (userEdited) {
      if (!window.confirm(
        'Re-running detection will discard your manual edits. Continue?'
      )) return
    }
    try {
      // Reset the split by re-saving with auto boundaries from the original split data
      if (!splitData) return
      const data = await api.put(`/uploads/${id}/split`, {
        boundaries: splitData.boundaries,
        warn_overwrite: false,
      }).then((r) => r.data)
      setBoundaries(data.boundaries)
      setDirty(false)
      toast.success('Detection re-applied')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? 'Re-run failed')
    }
  }, [boundaries, splitData, id])

  // ----- render -----

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-brand-500" />
      </div>
    )
  }

  if (isError || !splitData) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-gray-500">
        <AlertTriangle size={32} className="text-red-400" />
        <p>Failed to load split data.</p>
        <button
          onClick={() => navigate('/upload')}
          className="text-sm text-brand-600 hover:underline"
        >
          Back to uploads
        </button>
      </div>
    )
  }

  const pageCount = splitData.page_count
  const pageSignals = splitData.page_signals ?? {}
  const includedCount = boundaries.filter((b) => b.include).length
  const skippedCount = boundaries.filter((b) => !b.include).length

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/upload')}
          className="text-gray-400 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <div>
          <h1 className="text-xl font-bold">Review chapter split</h1>
          <p className="text-sm text-gray-500">
            {splitData.source_title ?? `Upload #${id}`} · {pageCount} pages
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {dirty && (
            <button
              onClick={() => saveMutation.mutate(boundaries)}
              disabled={saveMutation.isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
            >
              {saveMutation.isLoading
                ? <Loader2 size={13} className="animate-spin" />
                : null}
              Save
            </button>
          )}
          <button
            onClick={reRunDetection}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50"
          >
            <RefreshCw size={13} />
            Re-detect
          </button>
        </div>
      </div>

      {/* Filmstrip — chapters as grouped thumbnail sections */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Page filmstrip</h2>
        <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
          {boundaries.map((b, i) => (
            <FilmstripChapter
              key={`${b.page_start}-${i}`}
              uploadId={id}
              boundary={b}
              nextStart={boundaries[i + 1]?.page_start ?? null}
              pageCount={pageCount}
              allSignals={pageSignals}
              onAddBoundary={addBoundary}
              onExampleClick={(page) => exampleMutation.mutate(page)}
              isSelected={selectedIdx === i}
              onClick={() => setSelectedIdx(selectedIdx === i ? null : i)}
            />
          ))}
        </div>
      </div>

      {/* Teach-by-example proposal panel */}
      {examplePage !== null && exampleProposals.length > 0 && (
        <ExamplePanel
          uploadId={id}
          examplePage={examplePage}
          proposals={exampleProposals}
          currentBoundaries={boundaries}
          onAccept={acceptExampleProposals}
          onClose={() => { setExamplePage(null); setExampleProposals([]) }}
        />
      )}

      {/* Boundary editor table */}
      <div className="card overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Chapter boundaries</h2>
          <button
            onClick={() => {
              // Add a boundary at the first page that isn't already a start
              const starts = new Set(boundaries.map((b) => b.page_start))
              for (let p = 2; p <= pageCount; p++) {
                if (!starts.has(p)) { addBoundary(p); break }
              }
            }}
            className="flex items-center gap-1 text-xs text-brand-600 hover:text-brand-700"
          >
            <Plus size={12} /> Add boundary
          </button>
        </div>

        {/* Column headers */}
        <div
          className="grid px-3 py-1.5 bg-gray-50 border-b border-gray-100 text-[10px] font-semibold uppercase tracking-wide text-gray-400"
          style={{ gridTemplateColumns: '28px 70px 1fr 1fr 80px auto 28px' }}
        >
          <span title="Include / Skip">Inc</span>
          <span>Start pg</span>
          <span>Title (EN)</span>
          <span>Title (TH)</span>
          <span>Confidence</span>
          <span>Source</span>
          <span />
        </div>

        {boundaries.map((b, i) => (
          <BoundaryRow
            key={`row-${b.page_start}-${i}`}
            boundary={b}
            pageCount={pageCount}
            isSelected={selectedIdx === i}
            onSelect={() => setSelectedIdx(selectedIdx === i ? null : i)}
            onChange={(patch) => updateBoundary(i, patch)}
            onDelete={() => deleteBoundary(i)}
          />
        ))}

        {/* Bulk controls */}
        <div className="px-3 py-2 border-t border-gray-100 flex gap-3 text-xs">
          <button
            onClick={() => {
              setBoundaries((prev) => prev.map((b) => ({ ...b, include: true })))
              setDirty(true)
            }}
            className="text-brand-600 hover:underline"
          >
            Include all
          </button>
          <button
            onClick={() => {
              setBoundaries((prev) =>
                prev.map((b, i) => i === 0 ? b : { ...b, include: false })
              )
              setDirty(true)
            }}
            className="text-gray-500 hover:underline"
          >
            Skip all but first
          </button>
          <button
            onClick={() => {
              if (!window.confirm('Remove all boundaries except page 1?')) return
              setBoundaries([{
                idx: 0,
                page_start: 1,
                title_en: 'Full book',
                title_th: null,
                include: true,
                confidence: 0,
                signals: [],
                source: 'user',
                child_upload_id: null,
              }])
              setDirty(true)
            }}
            className="text-red-400 hover:underline"
          >
            Clear all
          </button>
        </div>
      </div>

      {/* Cost preview */}
      <CostPreview boundaries={boundaries} />

      {/* Confirm button */}
      <div className="flex justify-end">
        <button
          onClick={() => confirmMutation.mutate(boundaries)}
          disabled={confirmMutation.isLoading || includedCount === 0}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-brand-600 text-white font-medium hover:bg-brand-700 disabled:opacity-50"
        >
          {confirmMutation.isLoading
            ? <Loader2 size={16} className="animate-spin" />
            : <Check size={16} />}
          Confirm &amp; generate
          {includedCount > 0 && (
            <span className="ml-1 text-brand-200 text-sm">
              ({includedCount} chapter{includedCount !== 1 ? 's' : ''})
            </span>
          )}
        </button>
      </div>
    </div>
  )
}
