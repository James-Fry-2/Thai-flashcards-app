import { CompoundPart } from '../types'

// Single choke-point for chip background. Today every part gets the same
// neutral amber tone; a future familiarity feature will key this off the
// constituent card's FSRS retrievability (gloss_source === 'card' already
// marks a part that is an own card).
function chipTone(_part: CompoundPart): string {
  return 'bg-amber-50 border-amber-100'
}

interface Props {
  parts: CompoundPart[]
  compact?: boolean
}

export default function CompoundBreakdown({ parts, compact = false }: Props) {
  return (
    <div
      className={
        compact
          ? 'flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1'
          : 'flex flex-wrap items-center gap-x-2 gap-y-1.5'
      }
    >
      {parts.map((part, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-gray-300 text-xs">+</span>}
          <span
            className={
              `inline-flex flex-col items-center rounded-lg border text-center ${chipTone(part)} ` +
              (compact ? 'px-2 py-1 min-w-[40px]' : 'px-2.5 py-1.5 min-w-[48px]')
            }
          >
            <span className={`thai text-gray-700 ${compact ? 'text-xs' : 'text-sm'}`}>
              {part.thai}
            </span>
            {part.romanization && (
              <span className="text-[10px] text-gray-400 mt-0.5">{part.romanization}</span>
            )}
            <span
              className={
                part.gloss
                  ? `font-medium text-amber-700 mt-0.5 ${compact ? 'text-[10px]' : 'text-[10px]'}`
                  : 'text-[10px] text-gray-300 mt-0.5'
              }
            >
              {part.gloss || '—'}
            </span>
          </span>
        </span>
      ))}
    </div>
  )
}
