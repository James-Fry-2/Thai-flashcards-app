import { useQuery } from 'react-query'
import { Link } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Zap } from 'lucide-react'
import XPBar from '../components/XPBar'
import StreakBadge from '../components/StreakBadge'
import api from '../services/api'
import type { Profile, Deck } from '../types'

export default function DashboardPage() {
  const { data: profile } = useQuery<Profile>('profile', () =>
    api.get('/gamification/profile').then((r) => r.data)
  )
  const { data: decks = [] } = useQuery<Deck[]>('decks', () =>
    api.get('/decks/').then((r) => r.data)
  )

  const totalDue = decks.reduce((sum, d) => sum + d.due_count, 0)

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

      {totalDue > 0 && (
        <div className="card bg-brand-50 border-brand-100">
          <p className="font-medium text-brand-700">
            You have <strong>{totalDue}</strong> cards due across {decks.filter((d) => d.due_count > 0).length} decks
          </p>
          <div className="flex gap-2 mt-3 flex-wrap">
            {decks
              .filter((d) => d.due_count > 0)
              .map((d) => (
                <Link
                  key={d.id}
                  to={`/decks/${d.id}/review`}
                  className="btn-primary text-sm"
                >
                  <Zap size={13} />
                  {d.name} ({d.due_count})
                </Link>
              ))}
          </div>
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
    </div>
  )
}
