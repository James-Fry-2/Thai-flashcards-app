import { useState } from 'react'
import { useQuery } from 'react-query'
import { useNavigate } from 'react-router-dom'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'
import { TrendingUp, Sparkles, Inbox } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import type {
  ProgressPayload, MasteryGroup, DimensionRollup, Pattern,
} from '../types'

const BAND_COLOR: Record<string, string> = {
  solid: '#22c55e',      // green-500
  developing: '#60a5fa', // blue-400
  fragile: '#f59e0b',    // amber-500
  struggling: '#ef4444', // red-500
}
const BAND_LABEL: Record<string, string> = {
  solid: 'Solid',
  developing: 'Developing',
  fragile: 'Fragile',
  struggling: 'Struggling',
}
const BAND_ORDER = ['solid', 'developing', 'fragile', 'struggling'] as const

const DIMENSIONS: { key: keyof Pick<ProgressPayload, 'topic' | 'chapter' | 'card_type'>; label: string }[] = [
  { key: 'topic', label: 'Topic' },
  { key: 'chapter', label: 'Chapter' },
  { key: 'card_type', label: 'Card type' },
]

function isoWeekToDate(year: number, week: number): Date {
  const simple = new Date(Date.UTC(year, 0, 1 + (week - 1) * 7))
  const dow = simple.getUTCDay() || 7
  simple.setUTCDate(simple.getUTCDate() + 1 - dow)
  return simple
}

function BandBar({ distribution, sampleSize }: { distribution: MasteryGroup['band_distribution']; sampleSize: number }) {
  if (sampleSize === 0) return null
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden bg-gray-100 gap-[2px]">
      {BAND_ORDER.map((band) => {
        const pct = distribution[band] ?? 0
        if (pct <= 0) return null
        return (
          <div
            key={band}
            style={{ width: `${pct * 100}%`, backgroundColor: BAND_COLOR[band] }}
            title={`${BAND_LABEL[band]}: ${Math.round(pct * 100)}%`}
          />
        )
      })}
    </div>
  )
}

function GroupRow({ group, onStudy }: { group: MasteryGroup; onStudy: (ids: number[], label: string) => void }) {
  return (
    <div className="space-y-1.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-gray-800 truncate">{group.name}</span>
        <span className="text-xs text-gray-400 shrink-0">{group.reviewed_cards} reviewed</span>
      </div>
      <BandBar distribution={group.band_distribution} sampleSize={group.reviewed_cards} />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-500">
          {group.mean_accuracy != null ? `${Math.round(group.mean_accuracy * 100)}% accuracy` : '—'}
          {group.mean_retention != null ? ` · ${Math.round(group.mean_retention * 100)}% retention` : ''}
        </span>
        {group.weak_card_ids.length > 0 && (
          <button
            onClick={() => onStudy(group.weak_card_ids, group.name)}
            className="text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            Study these ({group.weak_card_ids.length})
          </button>
        )}
      </div>
    </div>
  )
}

function DimensionSection({
  rollup, onStudy,
}: {
  rollup: DimensionRollup
  onStudy: (ids: number[], label: string) => void
}) {
  if (rollup.strengths.length === 0 && rollup.weaknesses.length === 0) {
    return <p className="text-sm text-gray-400 py-4 text-center">Not enough data yet in this view.</p>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Strengths</p>
        <div className="divide-y divide-gray-50">
          {rollup.strengths.map((g) => (
            <GroupRow key={g.id} group={g} onStudy={onStudy} />
          ))}
        </div>
      </div>
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Weaknesses</p>
        <div className="divide-y divide-gray-50">
          {rollup.weaknesses.map((g) => (
            <GroupRow key={g.id} group={g} onStudy={onStudy} />
          ))}
        </div>
      </div>
    </div>
  )
}

function describePattern(p: Pattern): string {
  const pct = (n: number) => `${Math.round(n * 100)}%`
  if (p.baseline_again_rate > 0) {
    const ratio = p.subgroup_again_rate / p.baseline_again_rate
    return `${p.label} are missed ~${ratio.toFixed(1)}× your average (${pct(p.subgroup_again_rate)} vs ${pct(p.baseline_again_rate)}).`
  }
  return `${p.label} are missed ${pct(p.subgroup_again_rate)} of the time, vs ${pct(p.baseline_again_rate)} overall.`
}

export default function InsightsPanel() {
  const navigate = useNavigate()
  const [dimension, setDimension] = useState<'topic' | 'chapter' | 'card_type'>('topic')

  const { data, isLoading } = useQuery<ProgressPayload>('progress', () =>
    api.get('/analytics/progress').then((r) => r.data)
  )

  async function studyThese(cardIds: number[], label: string) {
    if (cardIds.length === 0) return
    try {
      const res = await api.post('/review/session/from-cards', { card_ids: cardIds, direction: 'th_to_en' })
      navigate('/insights/review', {
        state: {
          sessionId: res.data.session_id,
          cards: res.data.cards,
          title: label,
          backTo: '/dashboard',
          backLabel: 'Back to dashboard',
          backShortLabel: 'Dashboard',
        },
      })
    } catch {
      toast.error('Failed to start session')
    }
  }

  if (isLoading || !data) return null

  const hasAnyReviewHistory = data.patterns.baseline_again_rate != null
  if (!hasAnyReviewHistory) return null

  const trendData = data.trend.map((pt) => ({
    label: isoWeekToDate(pt.year, pt.week).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    againRate: pt.again_rate,
  }))

  const coverageGroups = [...data.coverage.topic, ...data.coverage.chapter]
    .sort((a, b) => b.new_cards - a.new_cards)
    .slice(0, 6)

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-bold flex items-center gap-2">
        <Sparkles size={18} className="text-brand-500" />
        Insights
      </h2>

      {/* Trend */}
      {trendData.some((d) => d.againRate != null) && (
        <div className="card">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={15} className="text-gray-400" />
            <p className="text-sm font-medium text-gray-600">Weekly again-rate</p>
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={trendData} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(v) => `${Math.round(v * 100)}%`}
                tick={{ fontSize: 11, fill: '#9ca3af' }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip
                formatter={(v: number) => [`${Math.round(v * 100)}%`, 'Again rate']}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              />
              <Line type="monotone" dataKey="againRate" stroke="#a855f7" strokeWidth={2} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Strengths / weaknesses by dimension */}
      <div className="card">
        <div className="flex items-center gap-1 mb-2">
          {DIMENSIONS.map((d) => (
            <button
              key={d.key}
              onClick={() => setDimension(d.key)}
              className={`text-xs font-medium px-2.5 py-1 rounded-lg transition-colors ${
                dimension === d.key ? 'bg-brand-100 text-brand-700' : 'text-gray-500 hover:bg-gray-50'
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
        <DimensionSection rollup={data[dimension]} onStudy={studyThese} />
      </div>

      {/* Coverage */}
      {coverageGroups.length > 0 && (
        <div className="card">
          <div className="flex items-center gap-2 mb-2">
            <Inbox size={15} className="text-gray-400" />
            <p className="text-sm font-medium text-gray-600">Not started yet</p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {coverageGroups.map((c) => (
              <span
                key={`${c.id}`}
                className="text-xs text-gray-500 bg-gray-50 border border-gray-200 px-2.5 py-1 rounded-lg"
              >
                {c.name} ({c.new_cards} new)
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Patterns */}
      {(data.patterns.patterns.length > 0 || data.patterns.acquisition_vs_retention) && (
        <div className="card space-y-3">
          <p className="text-sm font-medium text-gray-600">Patterns we noticed</p>
          {data.patterns.patterns.map((p) => (
            <div key={p.key} className="flex items-center justify-between gap-3 text-sm">
              <p className="text-gray-700">{describePattern(p)}</p>
              <button
                onClick={() => studyThese(p.card_ids, p.label)}
                className="text-xs font-medium text-brand-600 hover:text-brand-700 shrink-0"
              >
                Study these ({p.card_ids.length})
              </button>
            </div>
          ))}
          {data.patterns.acquisition_vs_retention && (
            <div className="flex flex-col gap-2 text-sm border-t border-gray-50 pt-3">
              <p className="text-gray-700">
                {data.patterns.acquisition_vs_retention.struggling_count} cards need reteaching (getting them
                wrong) and {data.patterns.acquisition_vs_retention.fragile_count} need re-spacing (getting them
                right, but not sticking) — these need opposite fixes.
              </p>
              <div className="flex gap-4">
                <button
                  onClick={() =>
                    studyThese(data.patterns.acquisition_vs_retention!.struggling_card_ids, 'Reteach')
                  }
                  className="text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  Study struggling ({data.patterns.acquisition_vs_retention.struggling_count})
                </button>
                <button
                  onClick={() => studyThese(data.patterns.acquisition_vs_retention!.fragile_card_ids, 'Re-space')}
                  className="text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  Study fragile ({data.patterns.acquisition_vs_retention.fragile_count})
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
