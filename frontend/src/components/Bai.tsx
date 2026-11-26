/**
 * Bai, the Baimai leaf (brand/BRAND-SYSTEM.md §6).
 *
 * Bai appears only at the edges of a session: empty states, the end-of-session screen, milestones,
 * "needs checking" prompts and help. Never on a card face or during a review, and never next to jokes.
 * Drawn to match brand/logo/bai-mark.svg.
 */
type Mood = 'happy' | 'sleeping' | 'thinking'

interface BaiProps {
  size?: number
  mood?: Mood
  /** Marigold Bai is reserved for milestones. */
  milestone?: boolean
  className?: string
  /** Leave empty when the text beside Bai already says what it means. */
  label?: string
}

const INK = '#211f1b'
const BLUSH = '#f2aabb'

export default function Bai({ size = 64, mood = 'happy', milestone = false, className, label }: BaiProps) {
  const leaf = milestone ? '#f2b33d' : '#3da35d'
  const vein = milestone ? '#b17d00' : '#1d8544'
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label || undefined}
      aria-hidden={label ? undefined : true}
    >
      <path fill={leaf} d="M50 95 C16 79 13 40 50 5 C87 40 84 79 50 95 Z" />
      <path fill="none" stroke={vein} strokeWidth={3.5} strokeLinecap="round" d="M50 89 V74" />
      {mood === 'sleeping' ? (
        <path
          fill="none"
          stroke={INK}
          strokeWidth={3.5}
          strokeLinecap="round"
          d="M34 51 Q39 55 44 51 M56 51 Q61 55 66 51 M45 65 Q50 67 55 65"
        />
      ) : (
        <>
          <circle cx={mood === 'thinking' ? 41 : 39} cy={mood === 'thinking' ? 48 : 50} r={5.5} fill={INK} />
          <circle cx={mood === 'thinking' ? 63 : 61} cy={mood === 'thinking' ? 48 : 50} r={5.5} fill={INK} />
          <circle cx={mood === 'thinking' ? 43 : 41} cy={mood === 'thinking' ? 46 : 48} r={1.8} fill="#fff" />
          <circle cx={mood === 'thinking' ? 65 : 63} cy={mood === 'thinking' ? 46 : 48} r={1.8} fill="#fff" />
          <path
            fill="none"
            stroke={INK}
            strokeWidth={3.5}
            strokeLinecap="round"
            d={mood === 'thinking' ? 'M44 65 H58' : 'M42 63 Q50 70 58 63'}
          />
        </>
      )}
      <ellipse cx={30} cy={60} rx={4.5} ry={3.2} fill={BLUSH} />
      <ellipse cx={70} cy={60} rx={4.5} ry={3.2} fill={BLUSH} />
    </svg>
  )
}
