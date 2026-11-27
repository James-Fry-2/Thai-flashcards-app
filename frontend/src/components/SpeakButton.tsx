import type { MouseEvent } from 'react'
import { Loader2, Square, Volume2 } from 'lucide-react'
import { useAudio, useAudioPrefs } from '../hooks/useAudio'
import { audioKey, type AudioSource, type Speed } from '../services/audio'

interface Props {
  source: AudioSource
  thai: string
  size?: number
  /** Also show a small "slow" button next to the speaker. */
  showSlow?: boolean
  className?: string
}

/**
 * Plays Thai audio. Click plays at the default speed from Settings;
 * Shift-click plays the other speed. Clicking while it plays stops it.
 * Never lets the click bubble, so it is safe inside a clickable card.
 */
export default function SpeakButton({ source, thai, size = 16, showSlow = false, className = '' }: Props) {
  const { key, status, play, stop } = useAudio()
  const { defaultSpeed } = useAudioPrefs()
  const other: Speed = defaultSpeed === 'slow' ? 'normal' : 'slow'

  const keys = {
    normal: audioKey({ source, speed: 'normal' }),
    slow: audioKey({ source, speed: 'slow' }),
  }
  const activeSpeed: Speed | null = key === keys.normal ? 'normal' : key === keys.slow ? 'slow' : null

  function handle(e: MouseEvent, speed: Speed) {
    e.stopPropagation()
    e.preventDefault()
    if (activeSpeed === speed) {
      stop()
      return
    }
    play({ source, thai, speed })
  }

  const mainSpeed: Speed = defaultSpeed
  const mainActive = activeSpeed !== null && (activeSpeed === mainSpeed || !showSlow)
  const Icon = mainActive ? (status === 'loading' ? Loader2 : Square) : Volume2

  return (
    <span className={`inline-flex items-center gap-0.5 align-middle ${className}`}>
      <button
        type="button"
        onClick={(e) => handle(e, e.shiftKey ? other : mainSpeed)}
        className={`p-1.5 rounded-lg transition-colors ${
          mainActive ? 'text-brand-700 bg-brand-50' : 'text-gray-600 hover:text-brand-700 hover:bg-brand-50'
        }`}
        title={`Listen (Shift-click: ${other})`}
        aria-label={mainActive ? 'Stop audio' : 'Play Thai audio'}
      >
        <Icon size={size} className={mainActive && status === 'loading' ? 'animate-spin' : ''} />
      </button>
      {showSlow && (
        <button
          type="button"
          onClick={(e) => handle(e, other)}
          className={`px-1.5 py-0.5 rounded-md text-[10px] font-medium uppercase tracking-wide transition-colors ${
            activeSpeed === other ? 'text-brand-700 bg-brand-50' : 'text-gray-600 hover:text-brand-700 hover:bg-brand-50'
          }`}
          title={`Listen ${other}`}
          aria-label={`Play Thai audio ${other}`}
        >
          {other}
        </button>
      )}
    </span>
  )
}
