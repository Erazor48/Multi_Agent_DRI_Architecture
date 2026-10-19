import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import { authClient } from '~/lib/auth-client'
import { getCompany, type Company } from '~/lib/dri-api'
import { ChatInterface } from '~/components/ChatInterface'
import { ApprovalsList } from '~/components/ApprovalsList'
import { TeamView } from '~/components/TeamView'

type Tab = 'chat' | 'approvals' | 'team'

export const Route = createFileRoute('/companies/$companyId')({
  component: CompanyPage,
})

function CompanyPage() {
  const navigate = useNavigate()
  const { companyId } = Route.useParams()
  const { data: session, isPending } = authClient.useSession()
  const userId = session?.user.id ?? ''

  const [company, setCompany] = useState<Company | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('chat')

  useEffect(() => {
    if (!isPending && !session) navigate({ to: '/login' })
  }, [isPending, session])

  useEffect(() => {
    if (!userId) return
    getCompany(companyId, userId)
      .then(setCompany)
      .finally(() => setLoading(false))
  }, [companyId, userId])

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <p className="text-zinc-400">Loading…</p>
      </div>
    )
  }

  if (!company) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-zinc-400 mb-4">Company not found.</p>
          <Link to="/companies" className="text-zinc-50 underline text-sm">
            Back to companies
          </Link>
        </div>
      </div>
    )
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'chat', label: 'Chat' },
    { id: 'approvals', label: 'Approvals' },
    { id: 'team', label: 'Team' },
  ]

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-50 flex flex-col">
      <header className="border-b border-zinc-800 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <Link to="/companies" className="text-zinc-400 hover:text-zinc-50 transition-colors text-sm">
            ← Companies
          </Link>
          <div>
            <h1 className="text-lg font-bold">{company.name}</h1>
            <p className="text-zinc-400 text-xs truncate max-w-md">{company.vision}</p>
          </div>
          <span
            className={`ml-auto text-xs px-2 py-1 rounded-full font-mono ${
              company.status === 'active'
                ? 'bg-emerald-900 text-emerald-400'
                : 'bg-zinc-800 text-zinc-400'
            }`}
          >
            {company.status}
          </span>
        </div>
      </header>

      <div className="border-b border-zinc-800 px-6">
        <div className="max-w-5xl mx-auto flex gap-1">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-zinc-50 text-zinc-50'
                  : 'border-transparent text-zinc-400 hover:text-zinc-300'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 max-w-5xl mx-auto w-full px-6 py-6">
        {tab === 'chat' && <ChatInterface companyId={companyId} userId={userId} />}
        {tab === 'approvals' && <ApprovalsList companyId={companyId} userId={userId} />}
        {tab === 'team' && <TeamView companyId={companyId} userId={userId} />}
      </div>
    </div>
  )
}
