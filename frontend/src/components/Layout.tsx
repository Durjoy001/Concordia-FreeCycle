import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { NotificationBell } from './NotificationBell'

const navLinkClass = ({ isActive }: { isActive: boolean }): string =>
  `rounded-lg px-3 py-1.5 text-sm font-medium ${
    isActive ? 'bg-maroon/10 text-maroon' : 'text-slate-600 hover:bg-slate-100'
  }`

export function Layout(): JSX.Element {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <Link to="/" className="mr-auto text-lg font-bold tracking-tight">
            <span className="text-maroon">Concordia</span> FreeCycle
          </Link>

          <nav className="flex items-center gap-1">
            <NavLink to="/" className={navLinkClass} end>
              Browse
            </NavLink>
            {user !== null && (
              <>
                <NavLink to="/listings/new" className={navLinkClass}>
                  Give away
                </NavLink>
                <NavLink to="/my-listings" className={navLinkClass}>
                  My listings
                </NavLink>
                <NavLink to="/wishlist" className={navLinkClass}>
                  Wishlist
                </NavLink>
              </>
            )}
          </nav>

          <div className="flex items-center gap-2">
            {user === null ? (
              <>
                <Link to="/login" className="btn-secondary">
                  Sign in
                </Link>
                <Link to="/register" className="btn-primary">
                  Register
                </Link>
              </>
            ) : (
              <>
                <NotificationBell />
                <span className="hidden text-sm text-slate-500 sm:inline">
                  {user.display_name}
                </span>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    logout()
                    navigate('/')
                  }}
                >
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-500">
        Free items for Concordia students. Nothing here is for sale.
      </footer>
    </div>
  )
}
