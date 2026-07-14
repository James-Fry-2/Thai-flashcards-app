import { useRef, useEffect, useState, type ReactNode } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { Home, Upload, Layers, Tag, AlertTriangle, Search } from 'lucide-react'
import { clsx } from 'clsx'

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()

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
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
        <span className="text-xl font-bold text-brand-600 thai">เด็กการ์ด</span>
        <div className="flex gap-1 ml-4">
          <NavItem to="/dashboard" icon={<Home size={16} />} label="Dashboard" />
          <NavItem to="/decks" icon={<Layers size={16} />} label="Decks" />
          <NavItem to="/topics" icon={<Tag size={16} />} label="Topics" />
          <NavItem to="/at-risk" icon={<AlertTriangle size={16} />} label="At-risk" />
          <NavItem to="/upload" icon={<Upload size={16} />} label="Upload" />
        </div>
        <div className="ml-auto relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search to study… ⌘K"
            className="pl-8 pr-3 py-1.5 text-sm rounded-lg border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent w-56"
          />
        </div>
      </nav>
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
          isActive
            ? 'bg-brand-100 text-brand-700'
            : 'text-gray-600 hover:bg-gray-100'
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}
