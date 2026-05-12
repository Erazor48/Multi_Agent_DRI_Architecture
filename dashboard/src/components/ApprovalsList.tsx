import { useState, useEffect } from 'react'
import { listApprovals, approveAction, rejectAction, type Approval } from '~/lib/dri-api'

interface Props {
  companyId: string
  userId: string
}

export function ApprovalsList({ companyId, userId }: Props) {
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [note, setNote] = useState<Record<number, string>>({})

  async function load(all: boolean) {
    setLoading(true)
    try {
      const data = await listApprovals(companyId, userId, all)
      setApprovals(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (userId) load(showAll)
  }, [companyId, userId, showAll])

  async function handleApprove(idx: number) {
    setActionLoading(idx)
    try {
      const updated = await approveAction(companyId, idx + 1, note[idx] ?? '', userId)
      setApprovals(prev => prev.map((a, i) => (i === idx ? (updated as Approval) : a)))
    } finally {
      setActionLoading(null)
    }
  }

  async function handleReject(idx: number) {
    setActionLoading(idx)
    try {
      const updated = await rejectAction(companyId, idx + 1, note[idx] ?? '', userId)
      setApprovals(prev => prev.map((a, i) => (i === idx ? (updated as Approval) : a)))
    } finally {
      setActionLoading(null)
    }
  }

  if (loading) return <p className="text-zinc-400 text-sm py-8 text-center">Loading…</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">
          {showAll ? 'All Actions' : 'Pending Approvals'}
          <span className="ml-2 text-xs text-zinc-400 font-normal">({approvals.length})</span>
        </h2>
        <button
          onClick={() => setShowAll(v => !v)}
          className="text-xs text-zinc-400 hover:text-zinc-50 transition-colors"
        >
          {showAll ? 'Show pending only' : 'Show all'}
        </button>
      </div>

      {approvals.length === 0 ? (
        <p className="text-zinc-500 text-sm text-center py-8">No pending approvals.</p>
      ) : (
        <div className="space-y-3">
          {approvals.map((a, i) => (
            <div key={i} className="p-4 bg-zinc-900 border border-zinc-800 rounded-xl space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="text-xs font-mono text-zinc-400 uppercase tracking-wider">
                    {a.type}
                  </span>
                  <p className="text-sm text-zinc-200 mt-0.5">{a.description}</p>
                </div>
                <span
                  className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-mono ${
                    a.status === 'pending'
                      ? 'bg-amber-900 text-amber-400'
                      : a.status === 'approved'
                        ? 'bg-emerald-900 text-emerald-400'
                        : 'bg-red-900 text-red-400'
                  }`}
                >
                  {a.status}
                </span>
              </div>

              {a.status === 'pending' && (
                <div className="space-y-2">
                  <input
                    type="text"
                    placeholder="Optional note…"
                    value={note[i] ?? ''}
                    onChange={e => setNote(prev => ({ ...prev, [i]: e.target.value }))}
                    className="w-full px-3 py-1.5 bg-zinc-800 border border-zinc-700 rounded-lg text-zinc-50 placeholder-zinc-600 focus:outline-none focus:border-zinc-500 text-xs"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleApprove(i)}
                      disabled={actionLoading === i}
                      className="px-3 py-1.5 bg-emerald-800 text-emerald-100 rounded-lg text-xs font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleReject(i)}
                      disabled={actionLoading === i}
                      className="px-3 py-1.5 bg-red-900 text-red-100 rounded-lg text-xs font-medium hover:bg-red-800 disabled:opacity-50 transition-colors"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              )}

              {a.decided_at && (
                <p className="text-zinc-600 text-xs font-mono">
                  Decided {new Date(a.decided_at).toLocaleString()}
                  {a.decision_note ? ` · ${a.decision_note}` : ''}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
