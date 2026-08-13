import { motion } from 'framer-motion'
import { Card } from '../types'
import CompoundBreakdown from './CompoundBreakdown'

interface Props {
  card: Card
  isFlipped: boolean
  onFlip: () => void
}

export default function FlashCard({ card, isFlipped, onFlip }: Props) {
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
          <p className="text-3xl font-semibold text-gray-900">{card.english}</p>
          {card.example_thai && (
            <div className="text-center mt-2 border-t border-gray-100 pt-3 w-full">
              <p className="thai text-base text-gray-700">{card.example_thai}</p>
              <p className="text-sm text-gray-400 mt-1">{card.example_english}</p>
            </div>
          )}
          {card.compound_breakdown && card.compound_breakdown.length >= 2 && (
            <div className="mt-3">
              <CompoundBreakdown parts={card.compound_breakdown} compact />
            </div>
          )}
        </div>
      </motion.div>
    </div>
  )
}
