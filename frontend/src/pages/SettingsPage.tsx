import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import toast from 'react-hot-toast'
import api from '../services/api'
import type { UserPreferences } from '../types'
import SpeakButton from '../components/SpeakButton'

interface TTSStatus {
  configured: boolean
  provider: string
  voices: { female: string; male: string }
  usage: { total_chars: number; month_chars: number; calls: number; total_cost: number; month_cost: number }
}

const DISPLAY_OPTIONS: { value: UserPreferences['romanization_display']; label: string; description: string }[] = [
  { value: 'source', label: 'Source (from material)', description: 'Romanization copied from the source document by the LLM' },
  { value: 'paiboon', label: 'Paiboon+', description: 'Tone-marked romanization system commonly used for Thai learners' },
  { value: 'rtgs', label: 'RTGS', description: 'Royal Thai General System — ASCII, no tone marks' },
  { value: 'ipa', label: 'IPA', description: 'International Phonetic Alphabet' },
]

// Card-face fonts (brand/BRAND-SYSTEM.md §3). Values match data-card-font in brand/tokens.css.
const CARD_FONT_OPTIONS: { value: UserPreferences['card_font']; label: string; family: string; description: string }[] = [
  { value: 'learner', label: 'Learner', family: "'Noto Sans Thai Looped'", description: 'Looped letters, easiest to tell apart while you learn' },
  { value: 'classic', label: 'Classic', family: "'Sarabun'", description: 'Looped, like official documents and many textbooks' },
  { value: 'realworld', label: 'Real-world', family: "'Anuphan'", description: 'Loopless, like signs, menus and websites' },
  { value: 'handwriting', label: 'Handwriting', family: "'Itim'", description: 'Like notes written by hand' },
]

const FALLBACK_OPTIONS: { value: UserPreferences['romanization_fallback']; label: string; description: string }[] = [
  { value: 'paiboon', label: 'Paiboon+', description: 'Fall back to Paiboon+ when the display scheme is empty' },
  { value: 'rtgs', label: 'RTGS', description: 'Fall back to RTGS when the display scheme is empty' },
  { value: 'ipa', label: 'IPA', description: 'Fall back to IPA when the display scheme is empty' },
  { value: 'none', label: 'None (show blank)', description: 'Leave romanization blank when the display scheme is empty' },
]

export default function SettingsPage() {
  const qc = useQueryClient()

  const { data: tts } = useQuery<TTSStatus>('tts-status', () => api.get('/tts/status').then((r) => r.data))

  const { data: prefs, isLoading } = useQuery<UserPreferences>(
    'preferences',
    () => api.get('/preferences/').then((r) => r.data),
  )

  type Patch = Partial<Omit<UserPreferences, 'updated_at'>>
  const update = useMutation(
    (patch: Patch) => api.patch('/preferences/', patch).then((r) => r.data as UserPreferences),
    {
      onSuccess: (updated, patch) => {
        qc.setQueryData('preferences', updated)
        qc.invalidateQueries('due-summary')
        const romanization = 'romanization_display' in patch || 'romanization_fallback' in patch
        toast.success(romanization ? 'Settings saved — all cards updated' : 'Settings saved')
      },
    },
  )

  // Local drafts so typing doesn't PATCH on every keystroke; saved on blur.
  const [newLimit, setNewLimit] = useState('')
  const [reviewLimit, setReviewLimit] = useState('')
  useEffect(() => {
    if (prefs) {
      setNewLimit(String(prefs.daily_new_limit))
      setReviewLimit(String(prefs.daily_review_limit))
    }
  }, [prefs?.daily_new_limit, prefs?.daily_review_limit])

  function saveLimit(field: 'daily_new_limit' | 'daily_review_limit', raw: string) {
    const value = Number(raw)
    if (!prefs || !Number.isInteger(value) || value === prefs[field]) {
      if (prefs) (field === 'daily_new_limit' ? setNewLimit : setReviewLimit)(String(prefs[field]))
      return
    }
    update.mutate({ [field]: value })
  }

  if (isLoading || !prefs) {
    return (
      <div className="max-w-xl space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />
      </div>
    )
  }

  return (
    <div className="max-w-xl space-y-8">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-0.5">Daily limits</h2>
          <p className="text-sm text-gray-600">
            Keep each day&apos;s review a manageable size. Cards you&apos;re part-way through learning are
            always shown. The day resets at 4am.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="daily-new" className="block text-sm font-medium text-gray-700">
              New cards per day
            </label>
            <input
              id="daily-new"
              type="number"
              min={0}
              max={200}
              className="w-full border border-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              value={newLimit}
              disabled={update.isLoading}
              onChange={(e) => setNewLimit(e.target.value)}
              onBlur={() => saveLimit('daily_new_limit', newLimit)}
              onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
            />
            <p className="text-xs text-gray-600">0–200. Rule of thumb: daily reviews settle at about 10× this number.</p>
          </div>
          <div className="space-y-2">
            <label htmlFor="daily-review" className="block text-sm font-medium text-gray-700">
              Reviews per day
            </label>
            <input
              id="daily-review"
              type="number"
              min={10}
              max={2000}
              className="w-full border border-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              value={reviewLimit}
              disabled={update.isLoading}
              onChange={(e) => setReviewLimit(e.target.value)}
              onBlur={() => saveLimit('daily_review_limit', reviewLimit)}
              onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
            />
            <p className="text-xs text-gray-600">
              10–2000. If more than this are due, catch-up mode pauses new cards until you&apos;re back on track.
            </p>
          </div>
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-0.5">Thai card font</h2>
          <p className="text-sm text-gray-600">
            The typeface for Thai on your cards. Looped letters are easier to tell apart when you&apos;re
            starting out. Switch to Real-world when you want to practise the letter shapes you&apos;ll see in Thailand.
          </p>
        </div>

        <div role="radiogroup" aria-label="Thai card font" className="grid grid-cols-2 gap-3">
          {CARD_FONT_OPTIONS.map((o) => {
            const selected = prefs.card_font === o.value
            return (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={update.isLoading}
                onClick={() => update.mutate({ card_font: o.value })}
                className={`text-left rounded-[14px] p-3 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-700 ${
                  selected ? 'bg-brand-50 ring-2 ring-brand-700' : 'bg-white ring-1 ring-gray-500 hover:bg-gray-50'
                }`}
              >
                <span className="block text-3xl leading-snug text-gray-900" style={{ fontFamily: o.family }} lang="th">
                  บ ป ด ต
                </span>
                <span className="block text-sm font-medium text-gray-900 mt-1">
                  {selected && <span aria-hidden="true">&#10003; </span>}
                  {o.label}
                </span>
                <span className="block text-xs text-gray-600">{o.description}</span>
              </button>
            )
          })}
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-0.5">Audio</h2>
          <p className="text-sm text-gray-600">
            {tts?.configured ? (
              <>Thai audio uses Azure Neural voices. Each word or sentence is generated once and saved.</>
            ) : (
              <>
                No speech service is set up, so your browser&apos;s own Thai voice is used. Set{' '}
                <code className="text-xs bg-gray-100 px-1 rounded">AZURE_SPEECH_KEY</code> on the server for
                natural voices.
              </>
            )}
          </p>
        </div>

        <div className="flex items-center gap-2 text-sm text-gray-700">
          Try it:
          <span className="thai text-lg">สวัสดีครับ</span>
          <SpeakButton source={{ kind: 'text', text: 'สวัสดีครับ', voice: 'male' }} thai="สวัสดีครับ" showSlow />
        </div>

        <div className="space-y-2">
          <label htmlFor="tts-speed" className="block text-sm font-medium text-gray-700">
            Default speed
          </label>
          <select
            id="tts-speed"
            className="w-full border border-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={prefs.tts_default_speed}
            disabled={update.isLoading}
            onChange={(e) => update.mutate({ tts_default_speed: e.target.value as UserPreferences['tts_default_speed'] })}
          >
            <option value="normal">Normal</option>
            <option value="slow">Slow</option>
          </select>
          <p className="text-xs text-gray-600">Shift-click any speaker button to hear the other speed.</p>
        </div>

        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-gray-500 text-brand-700 focus:ring-brand-500"
            checked={prefs.tts_autoplay_on_reveal}
            disabled={update.isLoading}
            onChange={(e) => update.mutate({ tts_autoplay_on_reveal: e.target.checked })}
          />
          <span>
            <span className="block text-sm font-medium text-gray-700">Play the Thai when you reveal a card</span>
            <span className="block text-xs text-gray-600">In review you can also press R to listen at any time.</span>
          </span>
        </label>

        {tts?.configured && (
          <p className="text-xs text-gray-600 border-t border-gray-100 pt-4">
            This month: {tts.usage.month_chars.toLocaleString()} characters generated (about $
            {tts.usage.month_cost.toFixed(2)}). Azure&apos;s free tier covers 500,000 characters a month.
          </p>
        )}
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-6">
        <div>
          <h2 className="text-base font-semibold text-gray-900 mb-0.5">Romanization scheme</h2>
          <p className="text-sm text-gray-600">
            All schemes are stored at ingestion time. Changing this setting instantly recomputes the
            display value for every card — no re-derivation.
          </p>
        </div>

        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">Display scheme</label>
          <select
            className="w-full border border-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={prefs.romanization_display}
            disabled={update.isLoading}
            onChange={(e) =>
              update.mutate({ romanization_display: e.target.value as UserPreferences['romanization_display'] })
            }
          >
            {DISPLAY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-600">
            {DISPLAY_OPTIONS.find((o) => o.value === prefs.romanization_display)?.description}
          </p>
        </div>

        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">Fallback scheme</label>
          <select
            className="w-full border border-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            value={prefs.romanization_fallback}
            disabled={update.isLoading}
            onChange={(e) =>
              update.mutate({ romanization_fallback: e.target.value as UserPreferences['romanization_fallback'] })
            }
          >
            {FALLBACK_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-600">
            Used when the display scheme is empty on a card.{' '}
            {FALLBACK_OPTIONS.find((o) => o.value === prefs.romanization_fallback)?.description}
          </p>
        </div>

        <p className="text-xs text-gray-600 border-t border-gray-100 pt-4">
          Manual overrides (set per-card in the card drawer) always take precedence over these settings.
        </p>
      </section>
    </div>
  )
}
