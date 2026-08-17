import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft } from 'lucide-react'
import toast from 'react-hot-toast'
import QuizCard from '../components/QuizCard'
import api from '../services/api'
import type { QuizItem, QuizOption, QuizSession } from '../types'

type SessionState = 'loading' | 'quizzing' | 'done'

interface MissedItem {
  item: QuizItem
  chosen: QuizOption
}

export default function QuizPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const deckId = searchParams.get('deck_id')
  const topicId = searchParams.get('topic_id')

  const [state, setState] = useState<SessionState>('loading')
  const [session, setSession] = useState<QuizSession | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answered, setAnswered] = useState<QuizOption | null>(null)
  const [score, setScore] = useState(0)
  const [missed, setMissed] = useState<MissedItem[]>([])
  const itemStartRef = useRef(performance.now())

  useEffect(() => {
    const params = new URLSearchParams()
    if (deckId) params.set('deck_id', deckId)
    if (topicId) params.set('topic_id', topicId)
    params.set('limit', '20')

    api.post(`/quiz/session?${params.toString()}`).then((r) => {
      const data: QuizSession = r.data
      if (data.items.length === 0) {
        toast('No cards available for a quiz right now!')
        navigate('/dashboard')
        return
      }
      setSession(data)
      setState('quizzing')
      itemStartRef.current = performance.now()
    })
  }, [deckId, topicId])

  const currentItem = session?.items[currentIndex]

  const handleChoose = useCallback(
    async (option: QuizOption) => {
      if (!session || !currentItem || answered) return

      const latency_ms = Math.round(performance.now() - itemStartRef.current)
      const correct = option.card_id === currentItem.card_id
      setAnswered(option)

      if (correct) {
        setScore((s) => s + 1)
      } else {
        setMissed((m) => [...m, { item: currentItem, chosen: option }])
      }

      try {
        await api.post('/quiz/answer', {
          quiz_session_id: session.quiz_session_id,
          target_card_id: currentItem.card_id,
          chosen_card_id: option.card_id,
          latency_ms,
          options: currentItem.options,
        })
      } catch (_) {
        // error handled by interceptor
      }

      setTimeout(() => {
        if (currentIndex + 1 >= session.items.length) {
          setState('done')
        } else {
          setCurrentIndex((i) => i + 1)
          setAnswered(null)
          itemStartRef.current = performance.now()
        }
      }, 900)
    },
    [session, currentItem, currentIndex, answered]
  )

  // Keyboard shortcuts 1-4
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (state !== 'quizzing' || answered || !currentItem) return
      if (['1', '2', '3', '4'].includes(e.key)) {
        const idx = Number(e.key) - 1
        const option = [...currentItem.options].sort((a, b) => a.position - b.position)[idx]
        if (option) handleChoose(option)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [state, answered, currentItem, handleChoose])

  if (state === 'loading') {
    return <div className="text-center py-20 text-gray-400">Loading quiz…</div>
  }

  if (state === 'done' && session) {
    return (
      <div className="max-w-lg mx-auto text-center py-16 space-y-6">
        <div className="text-6xl">{score === session.items.length ? '🎉' : '📝'}</div>
        <h2 className="text-2xl font-bold">Quiz complete!</h2>
        <p className="text-gray-500">
          {score} / {session.items.length} correct
        </p>

        {missed.length > 0 && (
          <div className="text-left border-t border-gray-100 pt-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-600">Missed</h3>
            {missed.map(({ item, chosen }) => (
              <div key={item.card_id} className="text-sm bg-gray-50 rounded-lg px-3 py-2">
                <span className="thai font-medium">{item.thai}</span>
                <span className="text-gray-400"> — </span>
                <span className="text-green-700">
                  {item.options.find((o) => o.card_id === item.card_id)?.english}
                </span>
                <span className="text-gray-400"> (you picked "{chosen.english}")</span>
              </div>
            ))}
          </div>
        )}

        <Link to="/dashboard" className="btn-primary mx-auto inline-block">
          Back to dashboard
        </Link>
      </div>
    )
  }

  if (!currentItem || !session) return null

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="flex items-center justify-between text-sm text-gray-400">
        <Link to="/dashboard" className="flex items-center gap-1 hover:text-gray-600">
          <ArrowLeft size={14} />
          Dashboard
        </Link>
        <span className="text-gray-600 font-medium">Quiz</span>
        <span>
          {currentIndex + 1} / {session.items.length}
        </span>
      </div>

      <div className="w-full bg-gray-200 rounded-full h-1.5">
        <div
          className="bg-brand-500 h-1.5 rounded-full transition-all"
          style={{ width: `${(currentIndex / session.items.length) * 100}%` }}
        />
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={currentItem.card_id}
          initial={{ opacity: 0, x: 40 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -40 }}
          transition={{ duration: 0.2 }}
        >
          <QuizCard item={currentItem} answered={answered} onChoose={handleChoose} />
        </motion.div>
      </AnimatePresence>

      {!answered && (
        <p className="text-center text-sm text-gray-400">
          Press <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">1</kbd>–
          <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">4</kbd> to answer
        </p>
      )}
    </div>
  )
}
