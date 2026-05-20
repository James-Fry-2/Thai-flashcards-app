interface Props {
  streak: number
  longest?: number
}

export default function StreakBadge({ streak, longest }: Props) {
  return (
    <div className="flex items-center gap-2 bg-orange-50 border border-orange-200 rounded-xl px-4 py-2">
      <span className="text-2xl">🔥</span>
      <div>
        <p className="text-xl font-bold text-orange-600">{streak}</p>
        <p className="text-xs text-orange-400">day streak{longest ? ` · best ${longest}` : ''}</p>
      </div>
    </div>
  )
}
