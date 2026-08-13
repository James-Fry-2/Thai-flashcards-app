import { useQuery } from 'react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, BookOpen, AlertTriangle, CheckCircle } from 'lucide-react'
import XPBar from '../components/XPBar'
import StreakBadge from '../components/StreakBadge'
import InsightsPanel from '../components/InsightsPanel'
import api from '../services/api'
import type { Profile, Deck, Topic, DueSummary } from '../types'

export default function DashboardPage() {
  const navigate = useNavigate()

  const { data: profile } = useQuery<Profile>('profile', () =>
    api.get('/gamification/profile').then((r) => r.data)
  )
  const { data: decks = [] } = useQuery<Deck[]>('decks', () =>
    api.get('/decks/').then((r) => r.data)
  )
  const { data: dueTopics = [] } = useQuery<Topic[]>('due-topics', () =>
    api.get('/topics?has_due=true').then((r) => r.data)
  )
  const { data: summary } = useQuery<DueSummary>('due-summary', () =>
    api.get('/review/summary').then((r) => r.data)
  )

  function startLibrarySession(strategy: 'due' | 'at_risk' | 'mixed') {
    navigate('/review/library', { state: { strategy } })
  }

  const totalDue = summary?.total_due ?? 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {profile && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="card sm:col-span-2 space-y-3">
            <p className="text-sm font-medium text-gray-500">Progress</p>
            <XPBar xp={profile.xp} level={profile.level} xpNextLevel={profile.xp_next_level} />
          </div>
          <StreakBadge streak={profile.streak_current} longest={profile.streak_longest} />
        </div>
      )}

      {/* Today's Review */}
      {totalDue > 0 ? (
        <div className="card border-brand-100 bg-brand-50 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-5xl font-bold text-brand-700">{totalDue}</span>
                <span className="text-brand-600 font-medium">cards to review today</span>
              </div>
              {summary && (
                <div className="flex gap-4 mt-2 text-sm flex-wrap">
                  <span className="text-gray-500">
                    <span className="font-medium text-gray-700">{summary.new_cards}</span> new
                  </span>
                  <span className="text-gray-500">
                    <span className="font-medium text-gray-700">{summary.due_today}</span> due
                  </span>
                  <span className={summary.overdue_by_7d > 0 ? 'text-amber-600' : 'text-gray-400'}>
                    <span className="font-medium">{summary.overdue_by_7d}</span> overdue &gt;7d
                  </span>
                  <span className={summary.overdue_by_30d > 0 ? 'text-red-600' : 'text-gray-400'}>
                    <span className="font-medium">{summary.overdue_by_30d}</span> overdue &gt;30d
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => startLibrarySession('mixed')}
              className="btn-primary flex items-center gap-2"
            >
              <BookOpen size={15} />
              Start review
            </button>
            <button
              onClick={() => startLibrarySession('due')}
              className="btn-secondary text-sm"
            >
              Just due cards
            </button>
            <button
              onClick={() => startLibrarySession('at_risk')}
              className="btn-secondary text-sm flex items-center gap-1.5"
            >
              <AlertTriangle size={13} />
              Focus on at-risk
            </button>
          </div>

          {/* De-emphasized deck chips */}
          {decks.filter((d) => d.due_count > 0).length > 0 && (
            <div>
              <p className="text-xs text-gray-400 mb-1.5">Or study by deck</p>
              <div className="flex gap-1.5 flex-wrap">
                {decks
                  .filter((d) => d.due_count > 0)
                  .map((d) => (
                    <Link
                      key={d.id}
                      to={`/decks/${d.id}/review`}
                      className="text-xs text-gray-500 bg-white border border-gray-200 hover:border-brand-200 hover:text-brand-600 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1"
                    >
                      <Zap size={11} />
                      {d.name} ({d.due_count})
                    </Link>
                  ))}
              </div>
            </div>
          )}

          {/* De-emphasized topic chips */}
          {dueTopics.length > 0 && (
            <div>
              <p className="text-xs text-gray-400 mb-1.5">Or study by topic</p>
              <div className="flex gap-1.5 flex-wrap">
                {dueTopics.map((t) => {
                  const count = (t.due_count ?? 0) + (t.new_count ?? 0)
                  return (
                    <Link
                      key={t.id}
                      to={`/topics/${t.id}/review`}
                      className="text-xs text-gray-500 bg-white border border-gray-200 hover:border-brand-200 hover:text-brand-600 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1"
                    >
                      <Zap size={11} />
                      {t.name} ({count})
                    </Link>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="card bg-green-50 border-green-100 flex items-center gap-3">
          <CheckCircle size={20} className="text-green-500 shrink-0" />
          <p className="font-medium text-green-700">All caught up. Nothing due today.</p>
        </div>
      )}

      {profile?.achievements && profile.achievements.length > 0 && (
        <div className="card">
          <p className="text-sm font-medium text-gray-500 mb-3">Recent Achievements</p>
          <div className="flex flex-wrap gap-2">
            {profile.achievements.slice(-6).map((a) => (
              <div
                key={a.key}
                className="flex items-center gap-1.5 bg-gray-50 border border-gray-100 rounded-lg px-3 py-1.5 text-sm"
                title={a.description}
              >
                <span>{a.icon}</span>
                <span className="font-medium">{a.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <InsightsPanel />
    </div>
  )
}
