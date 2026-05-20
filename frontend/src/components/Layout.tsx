import { Outlet, NavLink } from 'react-router-dom'
import { BookOpen, Home, Upload, Layers } from 'lucide-react'
import { clsx } from 'clsx'

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
        <span className="text-xl font-bold text-brand-600 thai">เด็กการ์ด</span>
        <div className="flex gap-1 ml-4">
          <NavItem to="/dashboard" icon={<Home size={16} />} label="Dashboard" />
          <NavItem to="/decks" icon={<Layers size={16} />} label="Decks" />
          <NavItem to="/upload" icon={<Upload size={16} />} label="Upload" />
        </div>
      </nav>
      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function NavItem({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
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
