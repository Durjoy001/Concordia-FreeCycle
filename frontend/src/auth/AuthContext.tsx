import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api, onSessionEnded, tokenStore } from '../api/client'
import type { UserMe } from '../api/types'

interface AuthState {
  user: UserMe | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (displayName: string, email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [user, setUser] = useState<UserMe | null>(null)
  const [loading, setLoading] = useState(true)

  // Restore the session on load: a stored token is only trusted once /auth/me
  // confirms it (and the client transparently refreshes an expired access token).
  useEffect(() => {
    let active = true
    if (!tokenStore.isAuthenticated) {
      setLoading(false)
      return
    }
    api.auth
      .me()
      .then((me) => {
        if (active) setUser(me)
      })
      .catch(() => {
        if (active) setUser(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  // The client tells us when a refresh failed, so the UI drops to signed-out.
  useEffect(() => onSessionEnded(() => setUser(null)), [])

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.auth.login(email, password)
    setUser(result.user)
  }, [])

  const register = useCallback(
    async (displayName: string, email: string, password: string) => {
      const result = await api.auth.register(displayName, email, password)
      setUser(result.user)
    },
    [],
  )

  const logout = useCallback(() => {
    api.auth.logout()
    setUser(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (context === null) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
