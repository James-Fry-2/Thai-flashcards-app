import type { ReadingStats, WordStatus } from '../../types'

export const STATUS_STYLE: Record<WordStatus, { label: string; bar: string; word: string; dot: string }> = {
  known: { label: 'Known', bar: 'bg-green-500', word: 'text-gray-900', dot: 'bg-green-500' },
  learning: { label: 'Learning', bar: 'bg-amber-400', word: 'bg-amber-100 text-amber-900', dot: 'bg-amber-400' },
  new: { label: 'In deck, not studied', bar: 'bg-sky-400', word: 'bg-sky-100 text-sky-900', dot: 'bg-sky-400' },
  unknown: {
    label: 'Not in your cards',
    bar: 'bg-gray-300',
    word: 'underline decoration-dotted decoration-brand-500 decoration-2 underline-offset-4 text-gray-900',
    dot: 'bg-gray-300',
  },
}

const ORDER: WordStatus[] = ['known', 'learning', 'new', 'unknown']

/** Stacked bar of known / learning / new / unknown word share. */
export default function KnownBar({ stats, showLegend = false }: { stats: ReadingStats; showLegend?: boolean }) {
  const total = stats.thai_words || 1
  return (
    <div className="space-y-1.5">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-gray-100" role="img"
        aria-label={`${stats.known_pct ?? 0}% of words known`}>
        {ORDER.map((s) =>
          stats.counts[s] > 0 ? (
            <div key={s} className={STATUS_STYLE[s].bar} style={{ width: `${(stats.counts[s] / total) * 100}%` }} />
          ) : null,
        )}
      </div>
      {showLegend && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
          {ORDER.map((s) => (
            <span key={s} className="flex items-center gap-1.5">
              <span className={`inline-block h-2 w-2 rounded-full ${STATUS_STYLE[s].dot}`} />
              {STATUS_STYLE[s].label} {stats.counts[s]}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
