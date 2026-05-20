import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft, Star } from 'lucide-react'
import toast from 'react-hot-toast'
import FlashCard from '../components/FlashCard'
import api from '../services/api'
import type { ReviewCard } from '../types'

type SessionState = 'loading' | 'reviewing' | 'done'

interface Session {
  session_id: number
  total_cards: number
  cards: ReviewCard[]
}

const RATING_LABELS = [
  { value: 1, label: 'Again', color: 'bg-red-500 hover:bg-red-600', key: '1' },
  { value: 2, label: 'Hard', color: 'bg-amber-500 hover:bg-amber-600', key: '2' },
  { value: 3, label: 'Good', color: 'bg-green-500 hover:bg-green-600', key: '3' },
  { value: 4, label: 'Easy', color: 'bg-blue-500 hover:bg-blue-600', key: '4' },
]

export default function ReviewPage() {
  const { deckId } = useParams<{ deckId: string }>()
  const navigate = useNavigate()
  const id = Number(deckId)

  const [state, setState] = useState<SessionState>('loading')
  const [session, setSession] = useState<Session | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isFlipped, setIsFlipped] = useState(false)
  const [summary, setSummary] = useState<{ cards_reviewed: number; xp_earned: number; streak: number } | null>(null)

  useEffect(() => {
    api.post(`/review/session?deck_id=${id}`).then((r) => {
      const data: Session = r.data
      if (data.cards.length === 0) {
        navigate(`/decks/${id}`)
        toast('No cards due right now!')
        return
      }
      setSession(data)
      setState('reviewing')
    })
  }, [id])

  const currentCard = session?.cards[currentIndex]

  const handleRate = useCallback(
    async (rating: number) => {
      if (!session || !currentCard) return

      try {
        const res = await api.post(`/review/session/${session.session_id}/rate`, {
          card_id: currentCard.id,
          schedule_id: currentCard.schedule_id,
          rating,
        })
        if (res.data.leveled_up) toast.success(`Level up! You're level ${res.data.level} 🎉`)
        if (res.data.new_achievements?.length) {
          res.data.new_achievements.forEach((key: string) => toast.success(`Achievement unlocked: ${key} 🏆`))
        }
      } catch (_) {
        // error handled by interceptor
      }

      if (currentIndex + 1 >= session.cards.length) {
        const endRes = await api.post(`/review/session/${session.session_id}/end`)
        setSummary(endRes.data)
        setState('done')
      } else {
        setCurrentIndex((i) => i + 1)
        setIsFlipped(false)
      }
    },
    [session, currentCard, currentIndex]
  )

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (state !== 'reviewing') return
      if (e.code === 'Space') {
        e.preventDefault()
        setIsFlipped((f) => !f)
      }
      if (isFlipped && ['1', '2', '3', '4'].includes(e.key)) {
        handleRate(Number(e.key))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [state, isFlipped, handleRate])

  if (state === 'loading') {
    return <div className="text-center py-20 text-gray-400">Loading session…</div>
  }

  if (state === 'done' && summary) {
    return (
      <div className="max-w-sm mx-auto text-center py-20 space-y-4">
        <div className="text-6xl">🎉</div>
        <h2 className="text-2xl font-bold">Session complete!</h2>
        <p className="text-gray-500">
          {summary.cards_reviewed} cards reviewed · +{summary.xp_earned} XP
        </p>
        {summary.streak > 1 && (
          <p className="text-orange-500 font-medium">🔥 {summary.streak}-day streak!</p>
        )}
        <Link to={`/decks/${id}`} className="btn-primary mx-auto">
          Back to deck
        </Link>
      </div>
    )
  }

  if (!currentCard) return null

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="flex items-center justify-between text-sm text-gray-400">
        <Link to={`/decks/${id}`} className="flex items-center gap-1 hover:text-gray-600">
          <ArrowLeft size={14} /> Decks
        </Link>
        <span>
          {currentIndex + 1} / {session!.total_cards}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-1.5">
        <div
          className="bg-brand-500 h-1.5 rounded-full transition-all"
          style={{ width: `${((currentIndex) / session!.total_cards) * 100}%` }}
        />
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={currentCard.id}
          initial={{ opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -40 }}
          transition={{ duration: 0.2 }}
        >
          <FlashCard
            card={currentCard}
            isFlipped={isFlipped}
            onFlip={() => setIsFlipped((f) => !f)}
          />
        </motion.div>
      </AnimatePresence>

      {isFlipped && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-4 gap-2"
        >
          {RATING_LABELS.map(({ value, label, color, key }) => (
            <button
              key={value}
              className={`${color} text-white rounded-xl py-3 text-sm font-medium transition-colors`}
              onClick={() => handleRate(value)}
            >
              <span className="block text-xs opacity-70">[{key}]</span>
              {label}
            </button>
          ))}
        </motion.div>
      )}

      {!isFlipped && (
        <p className="text-center text-sm text-gray-400">
          Press <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">Space</kbd> or tap card to reveal
        </p>
      )}
    </div>
  )
}
