import { useState } from 'react'
import { motion } from 'framer-motion'
import { useMutation } from 'react-query'
import { Flag } from 'lucide-react'
import toast from 'react-hot-toast'
import { Card, FlagTarget } from '../types'
import api from '../services/api'
import CompoundBreakdown from './CompoundBreakdown'

interface Props {
  card: Card
  isFlipped: boolean
  onFlip: () => void
}

const FLAG_TARGETS: { value: FlagTarget; label: string }[] = [
  { value: 'translation', label: 'Translation' },
  { value: 'compound', label: 'Breakdown' },
  { value: 'romanization', label: 'Romanization' },
  { value: 'example', label: 'Example' },
  { value: 'other', label: 'Other' },
]

export default function FlashCard({ card, isFlipped, onFlip }: Props) {
  const [flagOpen, setFlagOpen] = useState(false)
  const [flagTarget, setFlagTarget] = useState<FlagTarget>('translation')
  const [flagNote, setFlagNote] = useState('')

  // Flagging never touches review/grading endpoints and never blocks the
  // grade buttons — it's a one-tap report that closes immediately, not a
  // correction UI (see CardDetailDrawer for corrections).
  const createFlag = useMutation(
    () => api.post(`/cards/${card.id}/flags`, { target: flagTarget, note: flagNote.trim() || undefined }),
    {
      onSuccess: () => {
        toast.success('Flagged for review')
        setFlagOpen(false)
        setFlagNote('')
      },
    }
  )

  return (
    <div
      className="relative w-full max-w-lg mx-auto cursor-pointer select-none"
      style={{ perspective: 1200, height: 280 }}
      onClick={onFlip}
    >
      <motion.div
        style={{ transformStyle: 'preserve-3d', height: '100%' }}
        animate={{ rotateY: isFlipped ? 180 : 0 }}
        transition={{ duration: 0.45, ease: 'easeInOut' }}
        className="relative w-full h-full"
      >
        {/* Front */}
        <div
          className="absolute inset-0 card flex flex-col items-center justify-center gap-3 backface-hidden"
          style={{ backfaceVisibility: 'hidden' }}
        >
          <p className="text-5xl font-bold thai text-gray-900">{card.thai}</p>
          {card.romanization && (
            <p className="text-lg text-gray-400">{card.romanization}</p>
          )}
          <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
            {card.card_type}
          </span>
          <p className="text-xs text-gray-400 mt-4">tap to reveal</p>
        </div>

        {/* Back */}
        <div
          className="absolute inset-0 card flex flex-col items-center justify-center gap-3"
          style={{ backfaceVisibility: 'hidden', transform: 'rotateY(180deg)' }}
        >
          <button
            onClick={(e) => {
              e.stopPropagation()
              setFlagOpen((v) => !v)
            }}
            className="absolute top-3 right-3 p-1.5 rounded-lg text-gray-300 hover:text-amber-600 hover:bg-amber-50 transition-colors"
            title="Flag something wrong with this card"
          >
            <Flag size={14} />
          </button>

          {flagOpen && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="absolute top-11 right-3 w-56 bg-white border border-gray-200 rounded-xl shadow-lg p-3 z-10 text-left"
            >
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                What's wrong?
              </p>
              <div className="flex flex-wrap gap-1 mb-2">
                {FLAG_TARGETS.map((t) => (
                  <button
                    key={t.value}
                    onClick={() => setFlagTarget(t.value)}
                    className={`text-[11px] px-2 py-1 rounded-full border transition-colors ${
                      flagTarget === t.value
                        ? 'bg-amber-600 text-white border-amber-600'
                        : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              <textarea
                value={flagNote}
                onChange={(e) => setFlagNote(e.target.value)}
                placeholder="Optional note…"
                rows={2}
                disabled={createFlag.isLoading}
                className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-2 focus:outline-none focus:ring-2 focus:ring-amber-400"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setFlagOpen(false)}
                  className="flex-1 text-xs px-2 py-1.5 rounded-lg text-gray-500 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createFlag.mutate()}
                  disabled={createFlag.isLoading}
                  className="flex-1 text-xs px-2 py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 transition-colors"
                >
                  Flag
                </button>
              </div>
            </div>
          )}

          <p className="text-3xl font-semibold text-gray-900">{card.english}</p>
          {card.example_thai && (
            <div className="text-center mt-2 border-t border-gray-100 pt-3 w-full">
              <p className="thai text-base text-gray-700">{card.example_thai}</p>
              <p className="text-sm text-gray-400 mt-1">{card.example_english}</p>
            </div>
          )}
          {card.compound_breakdown && card.compound_breakdown.length >= 2 && (
            <div className="mt-3">
              <CompoundBreakdown
                parts={card.compound_breakdown}
                compact
                sourceIsUser={card.compound_breakdown_source === 'user'}
              />
            </div>
          )}
        </div>
      </motion.div>
    </div>
  )
}
