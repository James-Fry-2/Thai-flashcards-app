import { useQuery } from 'react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Zap, BookOpen, AlertTriangle, CheckCircle, LifeBuoy, Plus } from 'lucide-react'
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

  function startLibrarySession(strategy: 'due' | 'at_risk' | 'mixed' | 'catch_up', extend = false) {
    navigate('/review/library', { state: { strategy, extend } })
  }

  const toDoToday = summary?.to_do_today ?? 0
  const today = summary?.today
  const catchUp = today?.catch_up ?? false
  // Due cards that today's limits are holding back ("Study more" can reach them).
  const moreAvailable = summary ? summary.total_due - toDoToday : 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {profile && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="card sm:col-span-2 space-y-3">
            <p className="text-sm font-medium text-gray-600">Progress</p>
            <XPBar xp={profile.xp} level={profile.level} xpNextLevel={profile.xp_next_level} />
          </div>
          <StreakBadge streak={profile.streak_current} longest={profile.streak_longest} />
        </div>
      )}

      {/* Catch-up: backlog bigger than one day's limit */}
      {catchUp && today && (
        <div className="card border-amber-200 bg-amber-50 space-y-3">
          <div className="flex items-start gap-3">
            <LifeBuoy size={20} className="text-amber-700 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-amber-900">Catch-up mode</p>
              <p className="text-sm text-amber-800">
                {today.review_due} reviews have piled up. You don&apos;t need to clear them in one go: do a
                short catch-up session each day and you&apos;ll be back on track in about{' '}
                {today.catch_up_days} {today.catch_up_days === 1 ? 'day' : 'days'}. New cards are paused
                until then.
              </p>
              <p className="text-xs text-amber-700">
                Catch-up shows the cards you&apos;re most likely to still remember first, so each session
                saves as many as possible.
              </p>
            </div>
          </div>
          <button onClick={() => startLibrarySession('catch_up')} className="btn-primary flex items-center gap-2">
            <LifeBuoy size={15} />
            Catch up (30 cards)
          </button>
        </div>
      )}

      {/* Today's Review */}
      {toDoToday > 0 ? (
        <div className="card border-brand-100 bg-brand-50 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-5xl font-bold text-brand-700">{toDoToday}</span>
                <span className="text-brand-700 font-medium">cards for today</span>
              </div>
              {summary && (
                <div className="flex gap-4 mt-2 text-sm flex-wrap">
                  {summary.today_breakdown.learning > 0 && (
                    <span className="text-gray-600">
                      <span className="font-medium text-gray-700">{summary.today_breakdown.learning}</span> learning
                    </span>
                  )}
                  <span className="text-gray-600">
                    <span className="font-medium text-gray-700">{summary.today_breakdown.reviews}</span> reviews
                  </span>
                  <span className="text-gray-600">
                    <span className="font-medium text-gray-700">{summary.today_breakdown.new}</span> new
                    {catchUp && <span className="text-amber-700"> (paused)</span>}
                  </span>
                </div>
              )}
              {today && <DailyProgress today={today} />}
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
              <p className="text-xs text-gray-600 mb-1.5">Or study by deck</p>
              <div className="flex gap-1.5 flex-wrap">
                {decks
                  .filter((d) => d.due_count > 0)
                  .map((d) => (
                    <Link
                      key={d.id}
                      to={`/decks/${d.id}/review`}
                      className="text-xs text-gray-600 bg-white border border-gray-200 hover:border-brand-200 hover:text-brand-700 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1"
                    >
                      <Zap size={11} />
                      {d.name}
                    </Link>
                  ))}
              </div>
            </div>
          )}

          {/* De-emphasized topic chips */}
          {dueTopics.length > 0 && (
            <div>
              <p className="text-xs text-gray-600 mb-1.5">Or study by topic</p>
              <div className="flex gap-1.5 flex-wrap">
                {dueTopics.map((t) => (
                  <Link
                    key={t.id}
                    to={`/topics/${t.id}/review`}
                    className="text-xs text-gray-600 bg-white border border-gray-200 hover:border-brand-200 hover:text-brand-700 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1"
                  >
                    <Zap size={11} />
                    {t.name}
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="card bg-green-50 border-green-100 space-y-3">
          <div className="flex items-center gap-3">
            <CheckCircle size={20} className="text-green-700 shrink-0" />
            <p className="font-medium text-green-700">
              {summary && summary.today.new_done + summary.today.reviews_done > 0
                ? `Done for today: ${summary.today.reviews_done} reviews and ${summary.today.new_done} new cards. Nice work.`
                : 'All caught up. Nothing due today.'}
            </p>
          </div>
          <Link to="/read" className="text-sm text-green-700 underline underline-offset-2 hover:text-green-800 block">
            Read something with the words you know →
          </Link>
          {moreAvailable > 0 && !catchUp && (
            <button
              onClick={() => startLibrarySession('due', true)}
              className="btn-secondary text-sm flex items-center gap-1.5"
            >
              <Plus size={13} />
              Study more anyway
            </button>
          )}
        </div>
      )}

      {profile?.achievements && profile.achievements.length > 0 && (
        <div className="card">
          <p className="text-sm font-medium text-gray-600 mb-3">Recent Achievements</p>
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

function DailyProgress({ today }: { today: NonNullable<DueSummary['today']> }) {
  const done = today.reviews_done + today.new_done
  if (done === 0) return null
  return (
    <p className="text-xs text-gray-600 mt-1">
      Done so far today: {today.reviews_done} reviews, {today.new_done} new
    </p>
  )
}
