import { useEffect, useRef, useState } from 'react'
import { Sparkles, Ban, SplitSquareHorizontal, X as SkipIcon } from 'lucide-react'
import { clsx } from 'clsx'
import type { TriageCompoundGapItem } from '../../types'

interface Props {
  item: TriageCompoundGapItem
  focused: boolean
  filling: boolean
  editingPart: string | null
  onFillWithAi: () => void
  onStartEditGloss: (thai: string) => void
  onSaveGloss: (thai: string, gloss: string) => void
  onCancelEditGloss: () => void
  onSuppress: () => void
  onWrongSplit: () => void
  onSkip: () => void
}

export default function CompoundGapRow({
  item, focused, filling, editingPart,
  onFillWithAi, onStartEditGloss, onSaveGloss, onCancelEditGloss, onSuppress, onWrongSplit, onSkip,
}: Props) {
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const missing = new Set(item.missing_parts)

  useEffect(() => {
    if (editingPart) {
      setDraft('')
      inputRef.current?.focus()
    }
  }, [editingPart])

  return (
    <div
      className={clsx(
        'px-4 py-3 border-b border-gray-100 flex items-start gap-4',
        focused ? 'bg-brand-50/60 ring-1 ring-inset ring-brand-300' : 'hover:bg-gray-50'
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="thai text-lg font-medium text-gray-900">{item.thai}</span>
          <span className="text-sm text-gray-600">{item.english}</span>
        </div>
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {item.parts.map((p) => {
            const isMissing = missing.has(p.thai)
            const editing = editingPart === p.thai
            return (
              <div
                key={p.thai}
                className={clsx(
                  'rounded-lg px-2 py-1 text-xs border',
                  isMissing ? 'border-amber-300 bg-amber-50' : 'border-gray-200 bg-gray-50'
                )}
              >
                <div className="thai text-sm text-gray-800">{p.thai}</div>
                {editing ? (
                  <input
                    ref={inputRef}
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && draft.trim()) onSaveGloss(p.thai, draft.trim())
                      if (e.key === 'Escape') onCancelEditGloss()
                    }}
                    placeholder="gloss…"
                    className="mt-0.5 w-24 text-xs px-1 py-0.5 rounded border border-gray-500 focus:outline-none focus:ring-1 focus:ring-brand-400"
                  />
                ) : (
                  <button
                    onClick={() => onStartEditGloss(p.thai)}
                    className={clsx('mt-0.5 block', isMissing ? 'text-amber-700 font-medium' : 'text-gray-600')}
                  >
                    {p.gloss || '— add gloss —'}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={onFillWithAi}
          disabled={filling}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-brand-700 hover:bg-brand-50 disabled:opacity-50"
        >
          <Sparkles size={13} /> {filling ? 'Filling…' : 'Fill with AI'}
        </button>
        <button
          onClick={onSuppress}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
        >
          <Ban size={13} /> Not a compound
        </button>
        <button
          onClick={onWrongSplit}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
        >
          <SplitSquareHorizontal size={13} /> Wrong split
        </button>
        <button
          onClick={onSkip}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
        >
          <SkipIcon size={13} /> Skip
        </button>
      </div>
    </div>
  )
}
