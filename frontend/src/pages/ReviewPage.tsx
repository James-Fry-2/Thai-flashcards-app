import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import { useQuery } from 'react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft } from 'lucide-react'
import toast from 'react-hot-toast'
import FlashCard from '../components/FlashCard'
import { useAudio, useAudioPrefs } from '../hooks/useAudio'
import api from '../services/api'
import type { ReviewCard, Deck, TopicSummary } from '../types'

type SessionState = 'loading' | 'reviewing' | 'done' | 'limit'
type Scope = 'deck' | 'topic' | 'library' | 'custom' | 'upload'

interface Session {
  session_id: number
  total_cards: number
  cards: ReviewCard[]
  /** Due cards left out only because today's limits are used up. */
  held_back?: number
}

interface LocationState {
  strategy?: 'due' | 'at_risk' | 'mixed' | 'catch_up'
  extend?: boolean
  sessionId?: number
  cards?: ReviewCard[]
  title?: string
  backTo?: string
  backLabel?: string
  backShortLabel?: string
}

const RATING_LABELS = [
  { value: 1, label: 'Again', color: 'bg-red-500 hover:bg-red-600', key: '1' },
  { value: 2, label: 'Hard', color: 'bg-amber-500 hover:bg-amber-600', key: '2' },
  { value: 3, label: 'Good', color: 'bg-green-500 hover:bg-green-600', key: '3' },
  { value: 4, label: 'Easy', color: 'bg-blue-500 hover:bg-blue-600', key: '4' },
]

function detectScope(pathname: string): Scope {
  if (
    pathname.startsWith('/at-risk/review') ||
    pathname.startsWith('/search/review') ||
    pathname.startsWith('/insights/review')
  )
    return 'custom'
  if (pathname.startsWith('/review/library')) return 'library'
  if (pathname.includes('/topics/')) return 'topic'
  if (/\/uploads\/\d+\/review/.test(pathname)) return 'upload'
  return 'deck'
}

export default function ReviewPage() {
  const { deckId, topicId, uploadId } = useParams<{ deckId?: string; topicId?: string; uploadId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const locationState = (location.state ?? {}) as LocationState

  const scope = detectScope(location.pathname)
  const isTopicScope = scope === 'topic'
  const isDeckScope = scope === 'deck'
  const isUploadScope = scope === 'upload'
  const scopeId = isTopicScope ? Number(topicId) : isDeckScope ? Number(deckId) : isUploadScope ? Number(uploadId) : undefined

  // Deck / topic metadata (only loaded when relevant)
  const { data: deck } = useQuery<Deck>(
    ['deck', scopeId],
    () => api.get(`/decks/${scopeId}`).then((r) => r.data),
    { enabled: isDeckScope && scopeId !== undefined }
  )
  const { data: topicSummary } = useQuery<TopicSummary>(
    ['topic-summary', scopeId],
    () => api.get(`/topics/${scopeId}/summary`).then((r) => r.data),
    { enabled: isTopicScope && scopeId !== undefined }
  )

  const strategy = locationState.strategy ?? 'mixed'

  // Derive display metadata per scope
  const scopeTitle =
    scope === 'library'
      ? `Today's review`
      : scope === 'custom' || isUploadScope
      ? (locationState.title ?? (isUploadScope ? 'Chapter review' : 'At-risk cards'))
      : isTopicScope
      ? topicSummary?.name
      : deck?.name

  const scopeSubtitle =
    scope === 'library'
      ? strategy === 'due'
        ? 'Due cards across library'
        : strategy === 'at_risk'
        ? 'At-risk cards across library'
        : strategy === 'catch_up'
        ? 'Catch-up: most savable cards first'
        : 'Mixed: due cards and at-risk'
      : undefined

  const backTo =
    scope === 'library'
      ? '/dashboard'
      : scope === 'custom'
      ? (locationState.backTo ?? '/at-risk')
      : isUploadScope
      ? (locationState.backTo ?? `/uploads/${scopeId}/chapters`)
      : isTopicScope
      ? `/topics/${scopeId}`
      : `/decks/${scopeId}`

  const [state, setState] = useState<SessionState>('loading')
  // "Study more": go past today's new-card / review limits.
  const [extend, setExtend] = useState(locationState.extend ?? false)
  const [run, setRun] = useState(0)
  const [session, setSession] = useState<Session | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isFlipped, setIsFlipped] = useState(false)
  const [summary, setSummary] = useState<{
    cards_reviewed: number
    xp_earned: number
    streak: number
  } | null>(null)

  useEffect(() => {
    // Custom scope: session was pre-started by the caller; use injected state
    if (scope === 'custom') {
      if (locationState.sessionId && locationState.cards) {
        setSession({
          session_id: locationState.sessionId,
          total_cards: locationState.cards.length,
          cards: locationState.cards,
        })
        setState('reviewing')
      } else {
        navigate(locationState.backTo ?? '/at-risk')
      }
      return
    }

    // All other scopes: start session on mount
    let param: string
    if (scope === 'library') {
      param = `scope=library&strategy=${strategy}`
    } else if (isTopicScope) {
      param = `topic_id=${scopeId}`
    } else if (isUploadScope) {
      param = `upload_id=${scopeId}`
    } else {
      param = `deck_id=${scopeId}`
    }
    if (extend) param += '&extend=true'

    setState('loading')
    api.post(`/review/session?${param}`).then((r) => {
      const data: Session = r.data
      if (data.cards.length === 0) {
        if (data.held_back) {
          setSession(data)
          setState('limit')
          return
        }
        navigate(backTo)
        toast('No cards due right now!')
        return
      }
      setSession(data)
      setCurrentIndex(0)
      setIsFlipped(false)
      setState('reviewing')
    })
  }, [scope, scopeId, strategy, isUploadScope, extend, run])

  function studyMore() {
    setExtend(true)
    setRun((n) => n + 1) // restart even if already extended
  }

  const currentCard = session?.cards[currentIndex]
  const audio = useAudio()
  const { defaultSpeed, autoplayOnReveal } = useAudioPrefs()
  const speakCurrent = useCallback(() => {
    if (currentCard) audio.play({ source: { kind: 'card', cardId: currentCard.id }, thai: currentCard.thai, speed: defaultSpeed })
  }, [currentCard?.id, defaultSpeed])

  // Autoplay the Thai when the answer is revealed (Settings → Audio).
  useEffect(() => {
    if (isFlipped && autoplayOnReveal && state === 'reviewing') speakCurrent()
  }, [isFlipped])

  // Moving to the next card (or leaving the page) stops any audio.
  useEffect(() => () => audio.stop(), [currentCard?.id])

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
          res.data.new_achievements.forEach((key: string) =>
            toast.success(`Achievement unlocked: ${key} 🏆`)
          )
        }
      } catch (_) {
        // error handled by interceptor
      }

      if (currentIndex + 1 >= session.cards.length) {
        try {
          const endRes = await api.post(`/review/session/${session.session_id}/end`)
          setSummary(endRes.data)
        } catch (_) {
          setSummary({ cards_reviewed: session.cards.length, xp_earned: 0, streak: 0 })
        }
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
      // Don't hijack keystrokes while the user is typing somewhere (e.g. the
      // flag note field on FlashCard's answer side).
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return
      }
      if (e.code === 'Space') {
        e.preventDefault()
        setIsFlipped((f) => !f)
      }
      if (e.key === 'r' || e.key === 'R') {
        e.preventDefault()
        speakCurrent()
      }
      if (isFlipped && ['1', '2', '3', '4'].includes(e.key)) {
        handleRate(Number(e.key))
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [state, isFlipped, handleRate, speakCurrent])

  if (state === 'loading') {
    return <div className="text-center py-20 text-gray-400">Loading session…</div>
  }

  if (state === 'limit' && session) {
    return (
      <div className="max-w-sm mx-auto text-center py-20 space-y-4">
        <div className="text-6xl">✅</div>
        <h2 className="text-2xl font-bold">Done for today</h2>
        <p className="text-gray-500">
          You&apos;ve hit today&apos;s limit. {session.held_back} more{' '}
          {session.held_back === 1 ? 'card is' : 'cards are'} waiting. They&apos;ll still be there tomorrow.
        </p>
        <div className="flex flex-col gap-2 items-center">
          <Link to={backTo} className="btn-primary">
            Finish for today
          </Link>
          <button onClick={studyMore} className="btn-secondary text-sm">
            Study more anyway
          </button>
        </div>
      </div>
    )
  }

  if (state === 'done' && summary) {
    const backLabel =
      scope === 'library'
        ? 'Back to dashboard'
        : scope === 'custom'
        ? (locationState.backLabel ?? 'Back to at-risk')
        : isUploadScope
        ? 'Back to chapters'
        : isTopicScope
        ? 'Back to topic'
        : 'Back to deck'

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
        <div className="flex flex-col gap-2 items-center">
          <Link to={backTo} className="btn-primary">
            {backLabel}
          </Link>
          {!!session?.held_back && strategy !== 'catch_up' && (
            <button onClick={studyMore} className="btn-secondary text-sm">
              Study more ({session.held_back} waiting)
            </button>
          )}
        </div>
      </div>
    )
  }

  if (!currentCard) return null

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="flex items-center justify-between text-sm text-gray-400">
        <Link to={backTo} className="flex items-center gap-1 hover:text-gray-600">
          <ArrowLeft size={14} />
          {scope === 'library' ? 'Dashboard' : scope === 'custom' ? (locationState.backShortLabel ?? 'At-risk') : isUploadScope ? 'Chapters' : isTopicScope ? 'Topic' : 'Deck'}
        </Link>
        <div className="text-center">
          <span className="text-gray-600 font-medium block truncate max-w-[200px]">
            {scopeTitle}
          </span>
          {scopeSubtitle && (
            <span className="text-xs text-gray-400">{scopeSubtitle}</span>
          )}
        </div>
        <span>
          {currentIndex + 1} / {session!.total_cards}
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-200 rounded-full h-1.5">
        <div
          className="bg-brand-500 h-1.5 rounded-full transition-all"
          style={{ width: `${(currentIndex / session!.total_cards) * 100}%` }}
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
          Press <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">Space</kbd> or tap card to reveal ·{' '}
          <kbd className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">R</kbd> to listen
        </p>
      )}
    </div>
  )
}
