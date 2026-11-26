import { useRef, useEffect, useState, type ReactNode } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { Home, Upload, Layers, Tag, AlertTriangle, Search, Loader2, Settings, BookOpen, ListChecks, Shuffle, ClipboardCheck, Glasses } from 'lucide-react'
import { clsx } from 'clsx'
import { useActiveUploads } from '../hooks/useActiveUploads'
import { useTriageQueue } from '../hooks/useTriageQueue'
import { useQuery } from 'react-query'
import api from '../services/api'
import type { UserPreferences } from '../types'
import Bai from './Bai'

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { data: activeUploads = [] } = useActiveUploads()
  const processingCount = activeUploads.filter(
    (u) => u.status === 'pending' || u.status === 'processing'
  ).length
  const { data: triageQueue } = useTriageQueue()
  const triageCount = triageQueue
    ? triageQueue.counts.translation + triageQueue.counts.compound_gap + triageQueue.counts.open_flags
    : 0

  // Apply the Thai card-font setting app-wide (brand/tokens.css reads data-card-font).
  const { data: prefs } = useQuery<UserPreferences>(
    'preferences',
    () => api.get('/preferences/').then((r) => r.data),
    { staleTime: 60_000 },
  )
  useEffect(() => {
    const font = prefs?.card_font
    if (font && font !== 'learner') document.documentElement.dataset.cardFont = font
    else delete document.documentElement.dataset.cardFont
  }, [prefs?.card_font])

  const onSearchPage = location.pathname === '/search'
  const urlQ = onSearchPage ? new URLSearchParams(location.search).get('q') ?? '' : ''

  const [input, setInput] = useState(urlQ)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Sync input when arriving at /search from outside (e.g. back-nav)
  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setInput(urlQ)
    }
  }, [urlQ])

  // ⌘K / Ctrl+K to focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value
    setInput(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      navigate(`/search?q=${encodeURIComponent(val.trim())}`)
    }, 250)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      navigate(`/search?q=${encodeURIComponent(input.trim())}`)
    }
    if (e.key === 'Escape') {
      inputRef.current?.blur()
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="bg-white border-b-2 border-gray-100 px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <NavLink to="/dashboard" className="flex items-center gap-2 shrink-0" aria-label="Baimai home">
          <Bai size={30} />
          <span className="text-xl font-semibold text-brand-800" style={{ fontFamily: 'var(--bm-font-display)' }}>
            baimai
          </span>
        </NavLink>
        <div className="flex flex-wrap ml-1">
          <NavItem to="/dashboard" icon={<Home size={16} />} label="Dashboard" />
          <NavItem to="/decks" icon={<Layers size={16} />} label="Decks" />
          <NavItem to="/topics" icon={<Tag size={16} />} label="Topics" />
          <NavItem to="/at-risk" icon={<AlertTriangle size={16} />} label="At-risk" />
          <NavItem to="/quiz" icon={<ListChecks size={16} />} label="Quiz" />
          <NavItem to="/practice" icon={<Shuffle size={16} />} label="Practice" />
          <NavItem to="/read" icon={<Glasses size={16} />} label="Read" />
          <NavItem to="/triage" icon={<ClipboardCheck size={16} />} label="Triage" badge={triageCount} />
          <NavItem to="/books" icon={<BookOpen size={16} />} label="Books" />
          <NavItem to="/upload" icon={<Upload size={16} />} label="Upload" />
          <NavItem to="/settings" icon={<Settings size={16} />} label="Settings" />
        </div>
        {processingCount > 0 && (
          <NavLink
            to="/upload"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-brand-50 text-brand-700 border border-brand-200"
          >
            <Loader2 size={12} className="animate-spin" />
            {processingCount === 1 ? '1 upload processing…' : `${processingCount} uploads processing…`}
          </NavLink>
        )}
        <div className="ml-auto relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600 pointer-events-none" />
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search to study… ⌘K"
            className="pl-8 pr-3 py-1.5 text-sm rounded-lg border border-gray-500 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent w-36"
          />
        </div>
      </nav>
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function NavItem({ to, icon, label, badge }: { to: string; icon: ReactNode; label: string; badge?: number }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors',
          isActive
            ? 'bg-brand-100 text-brand-700'
            : 'text-gray-700 hover:bg-gray-100'
        )
      }
    >
      {icon}
      {label}
      {!!badge && (
        <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-700 leading-none">
          {badge}
        </span>
      )}
    </NavLink>
  )
}
