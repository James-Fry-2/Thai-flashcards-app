import { useState } from 'react'
import type { TriageTranslationItem } from '../../types'

interface Props {
  items: TriageTranslationItem[]
  onConfirm: (cardIds: number[]) => void
  onCancel: () => void
}

export default function KeepAllConfirmPanel({ items, onConfirm, onCancel }: Props) {
  const [unchecked, setUnchecked] = useState<Set<number>>(new Set())

  function toggle(cardId: number) {
    setUnchecked((prev) => {
      const next = new Set(prev)
      if (next.has(cardId)) next.delete(cardId)
      else next.add(cardId)
      return next
    })
  }

  const includedCount = items.length - unchecked.size

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onCancel}>
      <div
        className="bg-white rounded-xl shadow-xl border border-gray-200 p-5 w-[28rem] max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Keep all likely-OK translations</h3>
        <p className="text-xs text-gray-600 mb-3">Uncheck any card you don't want to keep.</p>
        <div className="overflow-y-auto flex-1 -mx-1 px-1 space-y-1">
          {items.map((item) => (
            <label
              key={item.card_id}
              className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-gray-50 text-sm cursor-pointer"
            >
              <input
                type="checkbox"
                checked={!unchecked.has(item.card_id)}
                onChange={() => toggle(item.card_id)}
                className="rounded border-gray-500 text-brand-700 focus:ring-brand-400"
              />
              <span className="thai">{item.thai}</span>
              <span className="text-gray-600">—</span>
              <span className="text-gray-600 truncate">{item.english}</span>
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-gray-100">
          <button onClick={onCancel} className="px-3 py-1.5 rounded text-sm text-gray-600 hover:bg-gray-100">
            Cancel
          </button>
          <button
            onClick={() => onConfirm(items.filter((i) => !unchecked.has(i.card_id)).map((i) => i.card_id))}
            disabled={includedCount === 0}
            className="px-3 py-1.5 rounded text-sm font-medium bg-brand-500 text-brand-950 hover:bg-brand-400 disabled:opacity-50"
          >
            Keep {includedCount} card{includedCount === 1 ? '' : 's'}
          </button>
        </div>
      </div>
    </div>
  )
}
