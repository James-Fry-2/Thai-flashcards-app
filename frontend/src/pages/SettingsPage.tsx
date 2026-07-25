import { useQuery, useMutation, useQueryClient } from 'react-query'
import toast from 'react-hot-toast'
import api from '../services/api'
import type { UserPreferences } from '../types'

const DISPLAY_OPTIONS: { value: UserPreferences['romanization_display']; label: string; description: string }[] = [
  { value: 'source', label: 'Source (from material)', description: 'Romanization copied from the source document by the LLM' },
  { value: 'paiboon', label: 'Paiboon+', description: 'Tone-marked romanization system commonly used for Thai learners' },
  { value: 'rtgs', label: 'RTGS', description: 'Royal Thai General System — ASCII, no tone marks' },
  { value: 'ipa', label: 'IPA', description: 'International Phonetic Alphabet' },
]

const FALLBACK_OPTIONS: { value: UserPreferences['romanization_fallback']; label: string; description: string }[] = [
  { value: 'paiboon', label: 'Paiboon+', description: 'Fall back to Paiboon+ when the display scheme is empty' },
  { value: 'rtgs', label: 'RTGS', description: 'Fall back to RTGS when the display scheme is empty' },
  { value: 'ipa', label: 'IPA', description: 'Fall back to IPA when the display scheme is empty' },
  { value: 'none', label: 'None (show blank)', description: 'Leave romanization blank when the display scheme is empty' },
]

export default function SettingsPage() {
  const qc = useQueryClient()

  const { data: prefs, isLoading } = useQuery<UserPreferences>(
    'preferences',
    () => api.get('/preferences/').then((r) => r.data),
  )

  const update = useMutation(
    (patch: Partial<Pick<UserPreferences, 'romanization_display' | 'romanization_fallback'>>) =>
      api.patch('/preferences/', patch).then((r) => r.data as UserPreferences),
    {
      onSuccess: (updated) => {
        qc.setQueryData('preferences', updated)
        toast.success('Settings saved — all cards updated')
      },
    },
  )

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
          <h2 className="text-base font-semibold text-gray-900 mb-0.5">Romanization scheme</h2>
          <p className="text-sm text-gray-500">
            All schemes are stored at ingestion time. Changing this setting instantly recomputes the
            display value for every card — no re-derivation.
          </p>
        </div>

        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">Display scheme</label>
          <select
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
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
          <p className="text-xs text-gray-400">
            {DISPLAY_OPTIONS.find((o) => o.value === prefs.romanization_display)?.description}
          </p>
        </div>

        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">Fallback scheme</label>
          <select
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
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
          <p className="text-xs text-gray-400">
            Used when the display scheme is empty on a card.{' '}
            {FALLBACK_OPTIONS.find((o) => o.value === prefs.romanization_fallback)?.description}
          </p>
        </div>

        <p className="text-xs text-gray-400 border-t border-gray-100 pt-4">
          Manual overrides (set per-card in the card drawer) always take precedence over these settings.
        </p>
      </section>
    </div>
  )
}
