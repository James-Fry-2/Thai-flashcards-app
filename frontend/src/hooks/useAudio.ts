import { useSyncExternalStore } from 'react'
import { useQuery } from 'react-query'
import api from '../services/api'
import { getState, play, playSequence, stop, subscribe, type Speed } from '../services/audio'
import type { UserPreferences } from '../types'

/** Current playback state plus the play/stop controls. */
export function useAudio() {
  const state = useSyncExternalStore(subscribe, getState)
  return { ...state, play, playSequence, stop }
}

/** The user's audio preferences (shares the 'preferences' query with Settings). */
export function useAudioPrefs(): { defaultSpeed: Speed; autoplayOnReveal: boolean } {
  const { data } = useQuery<UserPreferences>('preferences', () => api.get('/preferences/').then((r) => r.data), {
    staleTime: 5 * 60_000,
  })
  return {
    defaultSpeed: data?.tts_default_speed ?? 'normal',
    autoplayOnReveal: data?.tts_autoplay_on_reveal ?? false,
  }
}
