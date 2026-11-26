import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from 'react-query'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import api from '../services/api'
import KnownBar from '../components/reading/KnownBar'
import { SegmentLine, WordPanel, type Selected } from '../components/reading/WordTools'
import type { ReadingPage } from '../types'

export default function ReaderPage() {
  const { uploadId, pageIndex } = useParams<{ uploadId: string; pageIndex: string }>()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<Selected | null>(null)

  const pageKey = ['reading-page', uploadId, pageIndex]
  const { data: page, isLoading, isError } = useQuery<ReadingPage>(
    pageKey,
    () => api.get(`/reading/uploads/${uploadId}/pages/${pageIndex}`).then((r) => r.data),
    { keepPreviousData: true },
  )

  function goTo(idx: number | null | undefined) {
    if (idx == null) return
    setSelected(null)
    navigate(`/read/${uploadId}/${idx}`)
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.key === 'ArrowLeft') goTo(page?.prev_page)
      if (e.key === 'ArrowRight') goTo(page?.next_page)
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [page])

  if (isLoading) return <div className="text-center py-20 text-gray-600">Loading page…</div>
  if (isError || !page) {
    return (
      <div className="text-center py-20 space-y-3">
        <p className="text-gray-600">This page isn&apos;t available.</p>
        <Link to="/read" className="btn-secondary">Back to reading list</Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 text-sm">
        <Link to="/read" className="flex items-center gap-1 text-gray-600 hover:text-gray-600">
          <ArrowLeft size={14} /> Read
        </Link>
        <div className="text-center min-w-0">
          <span className="block font-medium text-gray-700 truncate">{page.title}</span>
          {page.book_title && <span className="block text-xs text-gray-600 truncate">{page.book_title}</span>}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => goTo(page.prev_page)}
            disabled={page.prev_page == null}
            className="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30"
            aria-label="Previous page"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-gray-600 tabular-nums">
            {page.page_number} / {page.page_count}
          </span>
          <button
            onClick={() => goTo(page.next_page)}
            disabled={page.next_page == null}
            className="p-1.5 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30"
            aria-label="Next page"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] items-start">
        <div className="space-y-4">
          <div className="card space-y-3">
            <p className="text-sm text-gray-700">
              {page.stats.thai_words === 0 ? (
                'No Thai text on this page.'
              ) : (
                <>
                  You know <span className="font-semibold text-gray-900">{page.stats.known_pct}%</span> of the words on
                  this page
                  {page.stats.unknown_unique > 0 && (
                    <> · {page.stats.unknown_unique} not in your cards yet</>
                  )}
                </>
              )}
            </p>
            {page.stats.thai_words > 0 && <KnownBar stats={page.stats} showLegend />}
          </div>

          <div className="card">
            <div className="text-xl leading-loose text-gray-800 font-thai">
              {page.lines.map((line, i) =>
                line.length === 0 || line.every((s) => !s.text.trim()) ? (
                  <div key={i} className="h-3" />
                ) : (
                  <p key={i} className="whitespace-pre-wrap break-words">
                    <SegmentLine segments={line} selected={selected} onSelect={setSelected} />
                  </p>
                ),
              )}
            </div>
          </div>

          {page.next_page != null && (
            <div className="flex justify-end">
              <button onClick={() => goTo(page.next_page)} className="btn-secondary flex items-center gap-1">
                Next page <ChevronRight size={15} />
              </button>
            </div>
          )}
        </div>

        <div className="lg:sticky lg:top-4">
          {selected ? (
            <WordPanel
              key={selected.thai}
              selected={selected}
              uploadId={Number(uploadId)}
              onClose={() => setSelected(null)}
              onStatus={(status) => setSelected((s) => (s ? { ...s, status } : s))}
            />
          ) : (
            <div className="card text-sm text-gray-600 hidden lg:block">
              Tap a Thai word to look it up. Underlined words aren&apos;t in your cards yet.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
