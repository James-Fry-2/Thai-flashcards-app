import { useEffect } from 'react'
import { clsx } from 'clsx'
import { Loader2, Volume2 } from 'lucide-react'
import type { PracticeItem, PracticeOption } from '../types'
import { useAudio, useAudioPrefs } from '../hooks/useAudio'
import { audioKey } from '../services/audio'

interface Props {
  item: PracticeItem
  answered: PracticeOption | null // the option the learner picked, once answered
  onChoose: (option: PracticeOption) => void
}

export default function MCQuestion({ item, answered, onChoose }: Props) {
  const sortedOptions = [...(item.payload.options ?? [])].sort((a, b) => a.position - b.position)

  return (
    <div className="space-y-6">
      {item.exercise_type === 'listen_th_en' ? (
        <ListenPrompt item={item} answered={answered !== null} />
      ) : (
        <div className="card flex flex-col items-center justify-center gap-3 py-10">
          <p className="text-5xl font-bold thai text-gray-900">{item.thai}</p>
          {item.romanization && (
            <p className="text-lg text-gray-600">{item.romanization}</p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-2">
        {sortedOptions.map((option, i) => {
          const isChosen = answered?.card_id === option.card_id
          const isTarget = option.card_id === item.card_id
          const showResult = answered !== null

          return (
            <button
              key={option.card_id}
              disabled={showResult}
              onClick={() => onChoose(option)}
              className={clsx(
                'flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-base font-medium transition-colors',
                !showResult && 'border-gray-200 hover:border-brand-400 hover:bg-brand-50',
                showResult && isTarget && 'border-green-500 bg-green-50 text-green-800',
                showResult && isChosen && !isTarget && 'border-red-500 bg-red-50 text-red-800',
                showResult && !isChosen && !isTarget && 'border-gray-200 text-gray-600'
              )}
            >
              <span className="text-xs opacity-60">[{i + 1}]</span>
              {option.english}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/** Listening prompt: plays the card's audio on arrival, keeps the Thai
 * hidden until the learner has answered, then shows what they heard. */
function ListenPrompt({ item, answered }: { item: PracticeItem; answered: boolean }) {
  const { key, status, play, stop } = useAudio()
  const { defaultSpeed } = useAudioPrefs()
  const source = { kind: 'card' as const, cardId: item.card_id }
  const listen = (speed = defaultSpeed) => play({ source, thai: item.thai, speed })

  useEffect(() => {
    listen()
    return () => stop()
  }, [item.card_id])

  const active = key === audioKey({ source, speed: 'normal' }) || key === audioKey({ source, speed: 'slow' })
  const other = defaultSpeed === 'slow' ? 'normal' : 'slow'

  return (
    <div className="card flex flex-col items-center justify-center gap-3 py-8">
      <button
        type="button"
        onClick={() => listen()}
        className={clsx(
          'h-20 w-20 rounded-full flex items-center justify-center transition-colors',
          active ? 'bg-brand-100 text-brand-700' : 'bg-brand-50 text-brand-600 hover:bg-brand-100',
        )}
        aria-label="Play the word again"
        title="Play again (R)"
      >
        {active && status === 'loading' ? <Loader2 size={32} className="animate-spin" /> : <Volume2 size={32} />}
      </button>
      <button
        type="button"
        onClick={() => listen(other)}
        className="text-xs font-medium uppercase tracking-wide text-gray-500 hover:text-brand-600"
      >
        Play {other}
      </button>
      {answered ? (
        <div className="text-center mt-1">
          <p className="text-4xl font-bold thai text-gray-900">{item.thai}</p>
          {item.romanization && <p className="text-base text-gray-600">{item.romanization}</p>}
        </div>
      ) : (
        <p className="text-sm text-gray-500 mt-1">What does this mean?</p>
      )}
    </div>
  )
}
