import { useEffect, useRef, useState } from 'react'
import { Check, Sparkles, X as SkipIcon } from 'lucide-react'
import { clsx } from 'clsx'
import type { AiVerdict, TriageTranslationItem } from '../../types'

const VERDICT_STYLE: Record<AiVerdict, string> = {
  likely_error: 'bg-red-100 text-red-700',
  likely_ok: 'bg-green-100 text-green-700',
  unsure: 'bg-amber-100 text-amber-700',
}

const VERDICT_LABEL: Record<AiVerdict, string> = {
  likely_error: 'Likely error',
  likely_ok: 'Likely OK',
  unsure: 'Unsure',
}

interface Props {
  item: TriageTranslationItem
  focused: boolean
  checking: boolean
  correctOpen: boolean
  verdict?: { verdict: AiVerdict; reason: string | null }
  onKeep: () => void
  onCorrect: (english: string) => void
  onToggleCorrect: () => void
  onCheck: () => void
  onSkip: () => void
}

export default function TranslationRow({
  item, focused, checking, correctOpen, verdict,
  onKeep, onCorrect, onToggleCorrect, onCheck, onSkip,
}: Props) {
  const [draft, setDraft] = useState(item.english)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (correctOpen) {
      setDraft(item.english)
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [correctOpen, item.english])

  return (
    <div
      className={clsx(
        'px-4 py-3 border-b border-gray-100 flex flex-col gap-2',
        focused ? 'bg-brand-50/60 ring-1 ring-inset ring-brand-300' : 'hover:bg-gray-50'
      )}
    >
      <div className="flex items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="thai text-lg font-medium text-gray-900">{item.thai}</span>
            {item.romanization && <span className="text-xs text-gray-400">{item.romanization}</span>}
            {verdict && (
              <span className={clsx('px-1.5 py-0.5 rounded text-[11px] font-medium', VERDICT_STYLE[verdict.verdict])}>
                {VERDICT_LABEL[verdict.verdict]}
              </span>
            )}
          </div>
          <div className="text-sm text-gray-600 mt-0.5">{item.english}</div>
          {verdict?.reason && <div className="text-xs text-gray-400 mt-0.5 italic">{verdict.reason}</div>}
          {item.translation_candidates.length > 0 && !correctOpen && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {item.translation_candidates.map((c) => (
                <button
                  key={c}
                  onClick={() => onCorrect(c)}
                  className="px-2 py-0.5 rounded-full text-xs bg-gray-100 hover:bg-brand-100 hover:text-brand-700 text-gray-600"
                >
                  {c}
                </button>
              ))}
            </div>
          )}
          {(item.source_title || item.chapter_label) && (
            <div className="text-[11px] text-gray-400 mt-1">
              {[item.source_title, item.chapter_label].filter(Boolean).join(' · ')}
            </div>
          )}
          {correctOpen && (
            <div className="flex items-center gap-2 mt-2">
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && draft.trim()) onCorrect(draft.trim())
                  if (e.key === 'Escape') onToggleCorrect()
                }}
                className="flex-1 text-sm px-2 py-1 rounded border border-gray-300 focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
              <button
                onClick={() => draft.trim() && onCorrect(draft.trim())}
                className="px-2 py-1 rounded bg-brand-600 text-white text-xs font-medium hover:bg-brand-700"
              >
                Save
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={onKeep}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
          >
            <Check size={13} /> Keep
          </button>
          <button
            onClick={onToggleCorrect}
            className="px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
          >
            Correct
          </button>
          <button
            onClick={onCheck}
            disabled={checking}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-brand-600 hover:bg-brand-50 disabled:opacity-50"
          >
            <Sparkles size={13} /> {checking ? 'Checking…' : 'Check with AI'}
          </button>
          <button
            onClick={onSkip}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-400 hover:bg-gray-100"
          >
            <SkipIcon size={13} /> Skip
          </button>
        </div>
      </div>
    </div>
  )
}
