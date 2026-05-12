import { useState, useEffect } from 'react'
import { listTeam, type Agent } from '~/lib/dri-api'

interface Props {
  companyId: string
  userId: string
}

export function TeamView({ companyId, userId }: Props) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!userId) return
    listTeam(companyId, userId)
      .then(setAgents)
      .finally(() => setLoading(false))
  }, [companyId, userId])

  if (loading) return <p className="text-zinc-400 text-sm py-8 text-center">Loading…</p>

  if (agents.length === 0) {
    return (
      <p className="text-zinc-500 text-sm text-center py-8">
        No agents spawned yet. Start a task to build your team.
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <h2 className="font-semibold">
        Team
        <span className="ml-2 text-xs text-zinc-400 font-normal">({agents.length} agents)</span>
      </h2>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {agents.map(a => (
          <div key={a.id} className="p-4 bg-zinc-900 border border-zinc-800 rounded-xl">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div>
                <p className="font-medium text-sm text-zinc-50">{a.title}</p>
                <p className="text-xs text-zinc-400 font-mono">{a.dept_slug}</p>
              </div>
              <span
                className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-mono ${
                  a.status === 'active'
                    ? 'bg-emerald-900 text-emerald-400'
                    : 'bg-zinc-800 text-zinc-500'
                }`}
              >
                {a.status}
              </span>
            </div>

            <p className="text-zinc-400 text-xs leading-relaxed line-clamp-2 mb-3">
              {a.role}
            </p>

            <div className="flex items-center gap-4 text-xs text-zinc-500 font-mono">
              <span title="Tasks completed">
                {a.success_count}/{a.task_count} tasks
              </span>
              <span title="Success rate">
                {a.task_count > 0 ? Math.round(a.success_rate * 100) : 0}% success
              </span>
            </div>

            {a.notes && (
              <p className="mt-2 text-xs text-zinc-500 italic line-clamp-1">{a.notes}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
