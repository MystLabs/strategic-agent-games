import { NavLink, Outlet } from 'react-router-dom';
import { Swords, Trophy, History, Radio, Bot } from 'lucide-react';

const NAV = [
  { to: '/', icon: Radio, label: 'Arena' },
  { to: '/leaderboard', icon: Trophy, label: 'Leaderboard' },
  { to: '/history', icon: History, label: 'History' },
  { to: '/agents', icon: Bot, label: 'Agents' },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-3 sm:px-6 py-3 flex items-center justify-between bg-surface/60 backdrop-blur-md sticky top-0 z-50">
        <div className="flex items-center gap-2 sm:gap-3">
          <Swords className="w-5 h-5 text-accent flex-shrink-0" />
          <span className="text-base sm:text-lg font-semibold tracking-tight truncate">Strategic agent games</span>
        </div>
        <nav className="flex gap-0.5 sm:gap-1 flex-shrink-0">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2 px-2.5 sm:px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-accent/15 text-accent-light'
                    : 'text-text-muted hover:text-text hover:bg-surface-hover'
                }`
              }
              title={label}
            >
              <Icon className="w-4 h-4" />
              <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
      </header>

      {/* Content */}
      <main className="flex-1 p-3 sm:p-6 max-w-7xl mx-auto w-full">
        <Outlet />
      </main>
    </div>
  );
}
