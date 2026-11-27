import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft } from 'lucide-react'
import toast from 'react-hot-toast'
import MCQuestion from '../components/MCQuestion'
import FlashCard from '../components/FlashCard'
import api from '../services/api'
import type { Card, PracticeItem, PracticeOption, PracticeSession, PracticeSummary } from '../types'
import Bai from '../components/Bai'
import { play as playAudio } from '../services/audio'
import { useAudioPrefs } from '../hooks/useAudio'

type SessionState = 'loading' | 'practicing' | 'done'

interface MissedItem {
  item: PracticeItem
  chosenOption?: PracticeOption // mc_th_en / listen_th_en
  rating?: number // recall_th_en
}

// Brand rule (brand/BRAND-SYSTEM.md §5): only Good is filled; Again carries a cross, never colour alone.
const RATING_LABELS = [
  { value: 1, label: 'Again', icon: '\u2715', color: 'grade grade-again', key: '1' },
  { value: 2, label: 'Hard', icon: '', color: 'grade', key: '2' },
  { value: 3, label: 'Good', icon: '\u2713', color: 'grade grade-good', key: '3' },
  { value: 4, label: 'Easy', icon: '', color: 'grade', key: '4' },
]

/** MCQuestion/FlashCard's props are exercise-agnostic and don't need most of
 * these fields — placeholders satisfy the shared Card shape without
 * modifying FlashCard.tsx. */
function toFlashCardShape(item: PracticeItem): Card {
  return {
    id: item.card_id,
    deck_id: 0,
    thai: item.thai,
    romanization: item.romanization,
    english: item.english ?? '',
    example_thai: item.example_thai,
    example_english: item.example_english,
    card_type: 'vocab',
    created_at: '',
    tags: [],
    topics: [],
    compound_breakdown: item.compound_breakdown ?? null,
  }
}

const isMultipleChoice = (type: string) => type === 'mc_th_en' || type === 'listen_th_en'

const EXERCISE_LABEL: Record<string, string> = {
  mc_th_en: 'Multiple choice',
  listen_th_en: 'Listening',
}

interface Props {
  /** /quiz renders this page restricted to mc_th_en only — see decision 1
   * in the practice-mode prompt. Still calls only /practice/*. */
  restrictToMc?: boolean
}

export default function PracticePage({ restrictToMc }: Props) {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const deckId = searchParams.get('deck_id')
  const topicId = searchParams.get('topic_id')

  const [state, setState] = useState<SessionState>('loading')
  const [session, setSession] = useState<PracticeSession | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [mcAnswered, setMcAnswered] = useState<PracticeOption | null>(null)
  const [isFlipped, setIsFlipped] = useState(false)
  const [missed, setMissed] = useState<MissedItem[]>([])
  const [summary, setSummary] = useState<PracticeSummary | null>(null)
  const itemStartRef = useRef(performance.now())
  const { defaultSpeed } = useAudioPrefs()

  useEffect(() => {
    const params = new URLSearchParams()
    if (deckId) params.set('deck_id', deckId)
    if (topicId) params.set('topic_id', topicId)
    params.set('limit', '20')
    if (restrictToMc) params.append('exercise_types', 'mc_th_en')

    api.post(`/practice/session?${params.toString()}`).then((r) => {
      const data: PracticeSession = r.data
      if (data.items.length === 0) {
        toast('No cards available to practice right now!')
        navigate('/dashboard')
        return
      }
      setSession(data)
      setState('practicing')
      itemStartRef.current = performance.now()
    })
  }, [deckId, topicId, restrictToMc])

  const currentItem = session?.items[currentIndex]

  const advance = useCallback(() => {
    if (!session) return
    if (currentIndex + 1 >= session.items.length) {
      api
        .post(`/practice/session/${session.session_id}/end`)
        .then((r) => setSummary(r.data))
        .catch(() => setSummary({ total: session.items.length, by_exercise_type: {}, binary_accuracy: null, self_rated_rating_distribution: {} }))
        .finally(() => setState('done'))
    } else {
      setCurrentIndex((i) => i + 1)
      setMcAnswered(null)
      setIsFlipped(false)
      itemStartRef.current = performance.now()
    }
  }, [session, currentIndex])

  const handleChoose = useCallback(
    async (option: PracticeOption) => {
      if (!session || !currentItem || mcAnswered) return

      const latency_ms = Math.round(performance.now() - itemStartRef.current)
      const correct = option.card_id === currentItem.card_id
      setMcAnswered(option)

      if (!correct) {
        setMissed((m) => [...m, { item: currentItem, chosenOption: option }])
      }

      try {
        await api.post('/practice/attempt', {
          session_id: session.session_id,
          card_id: currentItem.card_id,
          exercise_type: currentItem.exercise_type,
          latency_ms,
          chosen_card_id: option.card_id,
          options: currentItem.payload.options,
        })
      } catch (_) {
        // error handled by interceptor
      }

      // Listening reveals the Thai on answer, so leave time to read it.
      setTimeout(advance, currentItem.exercise_type === 'listen_th_en' ? 1800 : 900)
    },
    [session, currentItem, mcAnswered, advance]
  )

  const handleRate = useCallback(
    async (rating: number) => {
      if (!session || !currentItem) return

      const latency_ms = Math.round(performance.now() - itemStartRef.current)
      if (rating === 1) {
        setMissed((m) => [...m, { item: currentItem, rating }])
      }

      try {
        await api.post('/practice/attempt', {
          session_id: session.session_id,
          card_id: currentItem.card_id,
          exercise_type: currentItem.exercise_type,
          latency_ms,
          rating,
        })
      } catch (_) {
        // error handled by interceptor
      }

      advance()
    },
    [session, currentItem, advance]
  )

  // Keyboard: 1-4 selects an option in MC; Space flips and 1-4 rates in recall.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (state !== 'practicing' || !currentItem) return
      // Don't hijack keystrokes while the user is typing somewhere (e.g. the
      // flag note field on FlashCard's answer side, used by recall_th_en).
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return
      }

      if (currentItem.exercise_type === 'listen_th_en' && (e.key === 'r' || e.key === 'R')) {
        e.preventDefault()
        playAudio({ source: { kind: 'card', cardId: currentItem.card_id }, thai: currentItem.thai, speed: defaultSpeed })
        return
      }
      if (isMultipleChoice(currentItem.exercise_type)) {
        if (mcAnswered) return
        if (['1', '2', '3', '4'].includes(e.key)) {
          const idx = Number(e.key) - 1
          const option = [...(currentItem.payload.options ?? [])].sort((a, b) => a.position - b.position)[idx]
          if (option) handleChoose(option)
        }
      } else if (currentItem.exercise_type === 'recall_th_en') {
        if (e.code === 'Space') {
          e.preventDefault()
          setIsFlipped((f) => !f)
        }
        if (isFlipped && ['1', '2', '3', '4'].includes(e.key)) {
          handleRate(Number(e.key))
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [state, currentItem, mcAnswered, isFlipped, handleChoose, handleRate, defaultSpeed])

  if (state === 'loading') {
    return <div className="text-center py-20 text-gray-600">Loading practice session…</div>
  }

  if (state === 'done' && session) {
    return (
      <div className="max-w-lg mx-auto text-center py-16 space-y-6">
        <Bai size={88} className="mx-auto" mood={missed.length === 0 ? 'happy' : 'thinking'} />
        <h2 className="text-2xl font-bold">Practice complete!</h2>
        {summary && (
          <div className="text-gray-600 space-y-1">
            <p>{summary.total} cards practiced</p>
            {summary.accuracy_by_exercise_type
              ? Object.entries(summary.accuracy_by_exercise_type).map(([type, acc]) => (
                  <p key={type}>
                    {EXERCISE_LABEL[type] ?? type}: {Math.round(acc * 100)}% correct
                  </p>
                ))
              : summary.binary_accuracy !== null && (
                  <p>Multiple choice: {Math.round(summary.binary_accuracy * 100)}% correct</p>
                )}
            {Object.keys(summary.self_rated_rating_distribution).length > 0 && (
              <p>
                Recall ratings:{' '}
                {Object.entries(summary.self_rated_rating_distribution)
                  .map(([rating, count]) => `${RATING_LABELS[Number(rating) - 1]?.label ?? rating}×${count}`)
                  .join(', ')}
              </p>
            )}
          </div>
        )}

        {missed.length > 0 && (
          <div className="text-left border-t border-gray-100 pt-4 space-y-3">
            <h3 className="text-sm font-semibold text-gray-600">Missed</h3>
            {missed.map(({ item, chosenOption, rating }) => (
              <div key={item.card_id} className="text-sm bg-gray-50 rounded-lg px-3 py-2">
                <span className="thai font-medium">{item.thai}</span>
                <span className="text-gray-600"> — </span>
                <span className="text-green-700">
                  {isMultipleChoice(item.exercise_type)
                    ? item.payload.options?.find((o) => o.card_id === item.card_id)?.english
                    : item.english}
                </span>
                {chosenOption && (
                  <span className="text-gray-600"> (you picked "{chosenOption.english}")</span>
                )}
                {rating !== undefined && <span className="text-gray-600"> (rated "Again")</span>}
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
      <div className="flex items-center justify-between text-sm text-gray-600">
        <Link to="/dashboard" className="flex items-center gap-1 hover:text-gray-600">
          <ArrowLeft size={14} />
          Dashboard
        </Link>
        <div className="text-center">
          <span className="text-gray-600 font-medium block">
            {restrictToMc ? 'Quiz' : 'Practice'}
          </span>
          <span className="text-xs text-gray-600">Practice · doesn't affect scheduling</span>
        </div>
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
          {isMultipleChoice(currentItem.exercise_type) ? (
            <MCQuestion item={currentItem} answered={mcAnswered} onChoose={handleChoose} />
          ) : (
            <FlashCard
              card={toFlashCardShape(currentItem)}
              isFlipped={isFlipped}
              onFlip={() => setIsFlipped((f) => !f)}
            />
          )}
        </motion.div>
      </AnimatePresence>

      {isMultipleChoice(currentItem.exercise_type) && !mcAnswered && (
        <p className="text-center text-sm text-gray-600">
          Press <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">1</kbd>–
          <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">4</kbd> to answer
          {currentItem.exercise_type === 'listen_th_en' && (
            <>
              {' '}· <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">R</kbd> to replay
            </>
          )}
        </p>
      )}

      {currentItem.exercise_type === 'recall_th_en' && isFlipped && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-4 gap-2"
        >
          {RATING_LABELS.map(({ value, label, icon, color, key }) => (
            <button
              key={value}
              className={color}
              onClick={() => handleRate(value)}
            >
              <span className="block text-xs font-normal">[{key}]</span>
              {icon && <span aria-hidden="true">{icon} </span>}
              {label}
            </button>
          ))}
        </motion.div>
      )}

      {currentItem.exercise_type === 'recall_th_en' && !isFlipped && (
        <p className="text-center text-sm text-gray-600">
          Press <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">Space</kbd> or tap card to reveal
        </p>
      )}
    </div>
  )
}
