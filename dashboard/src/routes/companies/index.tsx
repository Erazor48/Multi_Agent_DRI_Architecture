import { createFileRoute, redirect, Link } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import { authClient } from '~/lib/auth-client'
import { listCompanies, createCompany, type Company } from '~/lib/dri-api'
import { CompanyCard } from '~/components/CompanyCard'

export const Route = createFileRoute('/companies/')({
  beforeLoad: async () => {
    const session = await authClient.getSession()
    if (!session.data) throw redirect({ to: '/login' })
  },
  component: CompaniesPage,
})

function CompaniesPage() {
  const { data: session } = authClient.useSession()
  const userId = session?.user.id ?? ''

  const [companies, setCompanies] = useState<Company[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [pitch, setPitch] = useState('')
  const [creating, setCreating] = useState(false)
  const [statusMessages, setStatusMessages] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    if (!userId) return
    listCompanies(userId)
      .then(setCompanies)
      .catch(e => setError(String(e.message)))
      .finally(() => setLoading(false))
  }, [userId])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!pitch.trim() || !userId || creating) return
    setCreating(true)
    setStatusMessages([])
    setError('')

    try {
      let newCompany: Company | null = null
      for await (const event of createCompany(pitch, userId)) {
        if (event.type === 'status' && event.message) {
          setStatusMessages(prev => [...prev, event.message!])
        } else if (event.type === 'result' && event.company) {
          newCompany = event.company
        } else if (event.type === 'error') {
          setError(event.message ?? 'Unknown error')
        }
      }
      if (newCompany) {
        setCompanies(prev => [newCompany!, ...prev])
        setPitch('')
        setShowForm(false)
        setStatusMessages([])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create company')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <span className="text-lg font-bold tracking-tight">DRI Dashboard</span>
        <div className="flex items-center gap-4">
          <span className="text-zinc-400 text-sm">{session?.user.email}</span>
          <button
            onClick={() => authClient.signOut()}
            className="text-sm text-zinc-400 hover:text-zinc-50 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold">Companies</h1>
          <button
            onClick={() => { setShowForm(v => !v); setError(''); setStatusMessages([]) }}
            className="px-4 py-2 bg-zinc-50 text-zinc-900 rounded-lg font-medium hover:bg-zinc-200 transition-colors text-sm"
          >
            + New Company
          </button>
        </div>

        {showForm && (
          <div className="mb-8 p-6 bg-zinc-900 rounded-xl border border-zinc-800">
            <h2 className="font-semibold mb-4">Create Company</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <textarea
                value={pitch}
                onChange={e => setPitch(e.target.value)}
                placeholder="Describe your company idea in a few sentences…"
                rows={4}
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-50 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none text-sm"
              />
              {statusMessages.length > 0 && (
                <div className="space-y-1 font-mono text-xs text-zinc-400">
                  {statusMessages.map((m, i) => (
                    <p key={i}>→ {m}</p>
                  ))}
                </div>
              )}
              {error && <p className="text-red-400 text-sm">{error}</p>}
              <div className="flex gap-3">
                <button
                  type="submit"
                  disabled={creating || !pitch.trim()}
                  className="px-4 py-2 bg-zinc-50 text-zinc-900 rounded-lg font-medium hover:bg-zinc-200 disabled:opacity-50 transition-colors text-sm"
                >
                  {creating ? 'Creating…' : 'Create'}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowForm(false); setStatusMessages([]); setError('') }}
                  className="px-4 py-2 text-zinc-400 hover:text-zinc-50 transition-colors text-sm"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        )}

        {loading ? (
          <p className="text-zinc-400 text-center py-16">Loading…</p>
        ) : companies.length === 0 ? (
          <div className="text-center py-16 text-zinc-400">
            <p className="text-lg font-medium">No companies yet.</p>
            <p className="text-sm mt-1">Create your first company to get started.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {companies.map(c => (
              <CompanyCard key={c.id} company={c} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
