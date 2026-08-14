import { NavLink, Outlet } from 'react-router-dom'
import { motion } from 'framer-motion'

const navItems = [
  { to: '/',        label: 'Dashboard',  icon: '🎬' },
  { to: '/profiles', label: 'Profiles',  icon: '🎯' },
  { to: '/sources',  label: 'Sources',   icon: '🔌' },
  { to: '/library',  label: 'Library',   icon: '📁' },
  { to: '/settings', label: 'Settings',  icon: '⚙️' },
  { to: '/docs/adapter', label: 'Adapter Docs', icon: '📖' },
]

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <nav className="w-56 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="px-5 py-6 border-b border-gray-800">
          <h1 className="text-lg font-bold text-brand-400 tracking-tight">B-Roll Engine</h1>
          <p className="text-xs text-gray-500 mt-0.5">Local B-roll toolkit</p>
        </div>
        <ul className="flex-1 py-3 space-y-0.5 px-2 overflow-y-auto">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-brand-600/20 text-brand-400'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'
                  }`
                }
              >
                <span className="text-base">{item.icon}</span>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="px-5 py-4 border-t border-gray-800">
          <p className="text-xs text-gray-600">v1.0.0 · Local server</p>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
          className="p-8 max-w-6xl mx-auto"
        >
          <Outlet />
        </motion.div>
      </main>
    </div>
  )
}
