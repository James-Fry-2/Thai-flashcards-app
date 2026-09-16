import { X as DismissIcon, ExternalLink } from 'lucide-react'
import { clsx } from 'clsx'
import type { TriageOpenFlagItem } from '../../types'

interface Props {
  item: TriageOpenFlagItem
  focused: boolean
  onDismiss: () => void
  onOpenDrawer: () => void
}

export default function OpenFlagRow({ item, focused, onDismiss, onOpenDrawer }: Props) {
  return (
    <div
      className={clsx(
        'px-4 py-3 border-b border-gray-100 flex items-start gap-4',
        focused ? 'bg-brand-50/60 ring-1 ring-inset ring-brand-300' : 'hover:bg-gray-50'
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          {item.card && <span className="thai text-lg font-medium text-gray-900">{item.card.thai}</span>}
          <span className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-gray-100 text-gray-600 uppercase tracking-wide">
            {item.target}
          </span>
        </div>
        {item.card && <div className="text-sm text-gray-500 mt-0.5">{item.card.english}</div>}
        {item.note && <div className="text-xs text-gray-500 mt-1">{item.note}</div>}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={onDismiss}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-gray-600 hover:bg-gray-100"
        >
          <DismissIcon size={13} /> Dismiss
        </button>
        <button
          onClick={onOpenDrawer}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-brand-600 hover:bg-brand-50"
        >
          <ExternalLink size={13} /> Open in drawer
        </button>
      </div>
    </div>
  )
}
