// Thai audio playback, shared by every speaker button in the app.
//
// One clip plays at a time: starting a new one stops the last. Audio comes
// from the backend (Azure Neural voices, cached as mp3 on the server). When
// the server has no TTS key (503 tts_not_configured) or a request fails, the
// browser's own speechSynthesis reads the Thai instead.
//
// Plain fetch rather than the shared axios client, so a missing key doesn't
// raise the global error toast on every click.
import toast from 'react-hot-toast'

export type Speed = 'normal' | 'slow'
export type Voice = 'female' | 'male'

export type AudioSource =
  | { kind: 'card'; cardId: number; field?: 'thai' | 'example' }
  | { kind: 'line'; textId: number; index: number }
  | { kind: 'text'; text: string; voice?: Voice }

export interface PlayRequest {
  source: AudioSource
  thai: string // spoken by the browser fallback
  speed: Speed
}

export function audioKey({ source, speed }: Pick<PlayRequest, 'source' | 'speed'>): string {
  switch (source.kind) {
    case 'card':
      return `card:${source.cardId}:${source.field ?? 'thai'}:${speed}`
    case 'line':
      return `line:${source.textId}:${source.index}:${speed}`
    case 'text':
      return `text:${source.voice ?? 'female'}:${speed}:${source.text}`
  }
}

// ---------------------------------------------------------------------------
// Tiny external store: which clip is playing / loading, for button state.
// ---------------------------------------------------------------------------

export interface AudioState {
  key: string | null
  status: 'idle' | 'loading' | 'playing'
}

let state: AudioState = { key: null, status: 'idle' }
const listeners = new Set<() => void>()

function setState(next: AudioState) {
  state = next
  listeners.forEach((l) => l())
}

export function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getState(): AudioState {
  return state
}

// ---------------------------------------------------------------------------
// Fetching (object URLs kept in a small LRU so replays are instant)
// ---------------------------------------------------------------------------

const MAX_CACHED = 150
const urlCache = new Map<string, string>()
// After a 503 (no TTS key on the server) skip the server for a minute, then
// try again, so adding a key takes effect without reloading the page.
const RETRY_SERVER_AFTER_MS = 60_000
let serverUnavailableUntil = 0
let warnedServerError = false
let warnedNoVoice = false

class ServerUnavailable extends Error {}

function remember(key: string, url: string) {
  urlCache.set(key, url)
  if (urlCache.size > MAX_CACHED) {
    const oldest = urlCache.keys().next().value as string
    URL.revokeObjectURL(urlCache.get(oldest)!)
    urlCache.delete(oldest)
  }
}

async function fetchAudio(req: PlayRequest, signal: AbortSignal): Promise<string> {
  const key = audioKey(req)
  const cached = urlCache.get(key)
  if (cached) {
    urlCache.delete(key) // refresh LRU position
    urlCache.set(key, cached)
    return cached
  }

  const { source, speed } = req
  let res: Response
  if (source.kind === 'text') {
    res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: source.text, voice: source.voice ?? 'female', speed }),
      signal,
    })
  } else {
    const path =
      source.kind === 'card'
        ? `/api/cards/${source.cardId}/audio?field=${source.field ?? 'thai'}&speed=${speed}`
        : `/api/reading/texts/${source.textId}/lines/${source.index}/audio?speed=${speed}`
    res = await fetch(path, { signal })
  }
  if (res.status === 503) throw new ServerUnavailable()
  if (!res.ok) throw new Error(`audio request failed (${res.status})`)
  const url = URL.createObjectURL(await res.blob())
  remember(key, url)
  return url
}

// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

let audioEl: HTMLAudioElement | null = null
let generation = 0
let abort: AbortController | null = null
let finishCurrent: (() => void) | null = null

function element(): HTMLAudioElement {
  if (!audioEl) audioEl = new Audio()
  return audioEl
}

/** Stop whatever is playing (or loading). */
export function stop() {
  generation++
  abort?.abort()
  abort = null
  if (audioEl) {
    audioEl.pause()
    audioEl.onended = audioEl.onerror = null
  }
  finishCurrent?.()
  finishCurrent = null
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  if (state.status !== 'idle') setState({ key: null, status: 'idle' })
}

function playUrl(url: string): Promise<void> {
  const el = element()
  return new Promise((resolve, reject) => {
    finishCurrent = resolve // stop() resolves it so a waiting sequence can exit
    el.onended = () => resolve()
    el.onerror = () => reject(new Error('audio playback failed'))
    el.src = url
    el.play().catch(reject)
  })
}

function thaiVoice(): SpeechSynthesisVoice | undefined {
  return window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith('th'))
}

function speakInBrowser(thai: string, speed: Speed): Promise<void> {
  if (!('speechSynthesis' in window)) return Promise.resolve()
  const voice = thaiVoice()
  if (!voice && !warnedNoVoice) {
    warnedNoVoice = true
    toast('No Thai voice in this browser. Set AZURE_SPEECH_KEY on the server for audio.', { icon: '🔇' })
  }
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(thai)
    u.lang = 'th-TH'
    if (voice) u.voice = voice
    u.rate = speed === 'slow' ? 0.65 : 0.95
    u.onend = u.onerror = () => resolve()
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(u)
  })
}

async function playOne(req: PlayRequest, gen: number): Promise<void> {
  const key = audioKey(req)
  setState({ key, status: 'loading' })

  if (Date.now() >= serverUnavailableUntil) {
    abort = new AbortController()
    try {
      const url = await fetchAudio(req, abort.signal)
      if (gen !== generation) return
      setState({ key, status: 'playing' })
      await playUrl(url)
      return
    } catch (err) {
      if (gen !== generation) return
      if (err instanceof ServerUnavailable) {
        serverUnavailableUntil = Date.now() + RETRY_SERVER_AFTER_MS
      } else if (!warnedServerError) {
        warnedServerError = true
        console.warn('TTS failed, using browser voice', err)
        toast.error('Audio service failed, using the browser voice instead')
      }
    }
  }

  if (gen !== generation) return
  setState({ key, status: 'playing' })
  await speakInBrowser(req.thai, req.speed)
}

/** Play one clip, stopping anything already playing. Resolves when it ends. */
export async function play(req: PlayRequest): Promise<void> {
  stop()
  const gen = generation
  try {
    await playOne(req, gen)
  } finally {
    if (gen === generation) setState({ key: null, status: 'idle' })
  }
}

/** Play clips one after another (e.g. a whole dialogue). onIndex reports progress. */
export async function playSequence(
  reqs: PlayRequest[],
  onIndex?: (i: number | null) => void,
  gapMs = 350,
): Promise<void> {
  stop()
  const gen = generation
  try {
    for (let i = 0; i < reqs.length; i++) {
      if (gen !== generation) return
      onIndex?.(i)
      await playOne(reqs[i], gen)
      if (gen !== generation) return
      await new Promise((r) => setTimeout(r, gapMs))
    }
  } finally {
    onIndex?.(null)
    if (gen === generation) setState({ key: null, status: 'idle' })
  }
}

// Some browsers load speech voices lazily; ask early so the first click has them.
if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  window.speechSynthesis.getVoices()
}
