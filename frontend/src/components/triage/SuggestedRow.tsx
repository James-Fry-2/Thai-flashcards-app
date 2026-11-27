import { Check, X as IgnoreIcon } from 'lucide-react'
import { clsx } from 'clsx'
import type { TriageSuggestedItem } from '../../types'

function describe(item: TriageSuggestedItem): string {
  const from = item.from_value as Record<string, unknown> | null
  const to = item.to_value as Record<string, unknown> | null

  if (item.target === 'translation') {
    const fromEnglish = (from?.english as string) ?? '?'
    const toEnglish = (to?.english as string) ?? fromEnglish
    return `You changed ${item.card.thai} from "${fromEnglish}" to "${toEnglish}" on another card. This card shows the same.`
  }
  return `You corrected the compound breakdown for ${item.card.thai} on another card. This card shows the same value.`
}

interface Props {
  item: TriageSuggestedItem
  focused: boolean
  siblingCount: number
  onApply: () => void
  onIgnore: () => void
  onApplyAllForEvent: () => void
}

export default function SuggestedRow({ item, focused, siblingCount, onApply, onIgnore, onApplyAllForEvent }: Props) {
  return (
    <div
      className={clsx(
        'px-4 py-3 border-b border-gray-100 flex items-start gap-4',
        focused ? 'bg-brand-50/60 ring-1 ring-inset ring-brand-300' : 'hover:bg-gray-50'
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="text-sm text-gray-700">{describe(item)}</div>
        <div className="text-xs text-gray-600 mt-0.5">{item.card.english}</div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={onApply}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-brand-700 hover:bg-brand-50"
        >
          <Check size={13} /> Apply
        </button>
        {siblingCount > 1 && (
          <button onClick={onApplyAllForEvent} className="px-2 py-1 rounded text-xs font-medium text-brand-700 hover:bg-brand-50">
            Apply all from this correction ({siblingCount})
          </button>
        )}
        <button
          onClick={onIgnore}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
        >
          <IgnoreIcon size={13} /> Not here
        </button>
      </div>
    </div>
  )
}
