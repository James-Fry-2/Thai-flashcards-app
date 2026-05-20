import { motion } from 'framer-motion'

interface Props {
  xp: number
  level: number
  xpNextLevel: number
}

export default function XPBar({ xp, level, xpNextLevel }: Props) {
  const prevLevelXP = (level - 1) * (level - 1) * 100
  const progress = Math.min(((xp - prevLevelXP) / (xpNextLevel - prevLevelXP)) * 100, 100)

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-bold text-brand-600 w-16">Lvl {level}</span>
      <div className="flex-1 bg-gray-200 rounded-full h-3 overflow-hidden">
        <motion.div
          className="h-3 bg-gradient-to-r from-brand-500 to-purple-400 rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        />
      </div>
      <span className="text-xs text-gray-500 w-20 text-right">{xp} / {xpNextLevel} XP</span>
    </div>
  )
}
