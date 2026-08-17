import { clsx } from 'clsx'
import type { QuizItem, QuizOption } from '../types'

interface Props {
  item: QuizItem
  answered: QuizOption | null // the option the learner picked, once answered
  onChoose: (option: QuizOption) => void
}

export default function QuizCard({ item, answered, onChoose }: Props) {
  const sortedOptions = [...item.options].sort((a, b) => a.position - b.position)

  return (
    <div className="space-y-6">
      <div className="card flex flex-col items-center justify-center gap-3 py-10">
        <p className="text-5xl font-bold thai text-gray-900">{item.thai}</p>
        {item.romanization && (
          <p className="text-lg text-gray-400">{item.romanization}</p>
        )}
      </div>

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
                showResult && !isChosen && !isTarget && 'border-gray-200 text-gray-400'
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
