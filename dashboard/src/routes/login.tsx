import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import { authClient } from '~/lib/auth-client'

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

function LoginPage() {
  const navigate = useNavigate()
  const { data: session, isPending } = authClient.useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!isPending && session) navigate({ to: '/companies' })
  }, [isPending, session])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (isSignUp) {
        await authClient.signUp.email({
          email,
          password,
          name: email.split('@')[0],
        })
      } else {
        await authClient.signIn.email({ email, password })
      }
      navigate({ to: '/companies' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  if (isPending) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-950">
        <p className="text-zinc-400">Loading…</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950">
      <div className="w-full max-w-sm space-y-6 p-8 bg-zinc-900 rounded-xl border border-zinc-800">
        <div>
          <h1 className="text-2xl font-bold text-zinc-50">DRI Dashboard</h1>
          <p className="text-zinc-400 text-sm mt-1">
            {isSignUp ? 'Create your account' : 'Sign in to your account'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-zinc-300 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-50 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-sm text-zinc-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-50 focus:outline-none focus:border-zinc-500"
              placeholder="••••••••"
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-zinc-50 text-zinc-900 rounded-lg font-medium hover:bg-zinc-200 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {loading ? 'Loading…' : isSignUp ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p className="text-zinc-400 text-sm text-center">
          {isSignUp ? 'Already have an account?' : "Don't have an account?"}{' '}
          <button
            type="button"
            onClick={() => { setIsSignUp(v => !v); setError('') }}
            className="text-zinc-50 underline cursor-pointer hover:text-white transition-colors"
          >
            {isSignUp ? 'Sign in' : 'Create one'}
          </button>
        </p>
      </div>
    </div>
  )
}
