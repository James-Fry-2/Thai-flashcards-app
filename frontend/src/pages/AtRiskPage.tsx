import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, BookOpen } from 'lucide-react'
import toast from 'react-hot-toast'
import CardDetailDrawer from '../components/CardDetailDrawer'
import api from '../services/api'
import type { AtRiskCard } from '../types'

function formatRelative(isoStr: string | null): string {
  if (!isoStr) return '—'
  const diffMs = Date.now() - new Date(isoStr).getTime()
  const days = Math.floor(diffMs / 86_400_000)
  if (days === 0) return 'today'
  if (days === 1) return '1d ago'
  return `${days}d ago`
}

function DifficultyBar({ value }: { value: number }) {
  const pct = Math.min(100, ((value - 1) / 9) * 100)
  const color = value >= 8 ? 'bg-red-500' : value >= 6.5 ? 'bg-amber-500' : 'bg-yellow-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 bg-gray-200 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums">{value.toFixed(1)}</span>
    </div>
  )
}

export default function AtRiskPage() {
  const navigate = useNavigate()

  const [difficultyThreshold, setDifficultyThreshold] = useState(7.0)
  const [overdueDays, setOverdueDays] = useState(14)
  const [cards, setCards] = useState<AtRiskCard[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedCardId, setSelectedCardId] = useState<number | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await api.get(
          `/analytics/at-risk?difficulty_threshold=${difficultyThreshold}&overdue_days=${overdueDays}&limit=100`
        )
        setCards(res.data)
      } catch {
        toast.error('Failed to load at-risk cards')
      } finally {
        setLoading(false)
      }
    }, 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [difficultyThreshold, overdueDays])

  async function handleReviewThese() {
    if (cards.length === 0) return
    const cardIds = cards.map((c) => c.id)
    try {
      const res = await api.post('/review/session/from-cards', {
        card_ids: cardIds,
        direction: 'th_to_en',
      })
      navigate('/at-risk/review', { state: { sessionId: res.data.session_id, cards: res.data.cards } })
    } catch {
      toast.error('Failed to start session')
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle size={20} className="text-amber-500" />
          <h1 className="text-2xl font-bold">At-risk cards</h1>
        </div>
        <p className="text-sm text-gray-500">
          High-difficulty cards that are significantly overdue — most likely to be forgotten.
        </p>
      </div>

      {/* Controls */}
      <div className="card flex flex-wrap gap-6 items-end">
        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-600">
            Min difficulty: <span className="text-gray-900">{difficultyThreshold.toFixed(1)}</span>
          </label>
          <input
            type="range"
            min={5.0}
            max={10.0}
            step={0.5}
            value={difficultyThreshold}
            onChange={(e) => setDifficultyThreshold(Number(e.target.value))}
            className="w-40 accent-brand-500"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-600">
            Min overdue: <span className="text-gray-900">{overdueDays}d</span>
          </label>
          <input
            type="range"
            min={1}
            max={90}
            step={1}
            value={overdueDays}
            onChange={(e) => setOverdueDays(Number(e.target.value))}
            className="w-40 accent-brand-500"
          />
        </div>

        <button
          onClick={handleReviewThese}
          disabled={cards.length === 0}
          className="btn-primary flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <BookOpen size={15} />
          Review these ({cards.length})
        </button>
      </div>

      {/* Results table */}
      {loading ? (
        <div className="text-center py-12 text-gray-400">Loading…</div>
      ) : cards.length === 0 ? (
        <div className="card text-center py-12 text-gray-400">
          No at-risk cards match these criteria.
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">Thai</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">English</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">Deck</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">Difficulty</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">Overdue</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-500">Last reviewed</th>
              </tr>
            </thead>
            <tbody>
              {cards.map((card) => (
                <tr
                  key={card.id}
                  onClick={() => setSelectedCardId(card.id)}
                  className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-2.5 thai font-medium">{card.thai}</td>
                  <td className="px-4 py-2.5 text-gray-700">{card.english}</td>
                  <td className="px-4 py-2.5 text-gray-500">{card.deck_name}</td>
                  <td className="px-4 py-2.5">
                    <DifficultyBar value={card.fsrs_difficulty} />
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={
                        (card.days_overdue ?? 0) >= 30
                          ? 'text-red-600 font-medium'
                          : (card.days_overdue ?? 0) >= 7
                          ? 'text-amber-600 font-medium'
                          : 'text-gray-600'
                      }
                    >
                      {card.days_overdue != null ? `${card.days_overdue}d` : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-400">{formatRelative(card.last_reviewed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CardDetailDrawer
        cardId={selectedCardId}
        onClose={() => setSelectedCardId(null)}
      />
    </div>
  )
}
