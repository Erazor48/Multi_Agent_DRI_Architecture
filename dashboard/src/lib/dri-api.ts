const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────

export interface Company {
  id: string
  name: string
  vision: string
  pitch: string
  org_structure: unknown[]
  status: string
  created_at: string
}

export interface Agent {
  id: string
  title: string
  role: string
  dept_slug: string
  task_count: number
  success_count: number
  success_rate: number
  token_budget: number
  notes: string
  status: string
  last_active_at: string
  created_at: string
}

export interface Approval {
  type: string
  description: string
  payload: unknown
  status: 'pending' | 'approved' | 'rejected'
  requested_at?: string
  decided_at?: string
  decision_note?: string | null
}

export interface CompanyStatus extends Company {
  team: Agent[]
  pending_approvals: number
  file_count: number
  recent_tasks: string[]
}

export interface SSEEvent {
  type: 'status' | 'result' | 'error'
  message?: string
  text?: string
  company?: Company
}

// ── Internal helpers ───────────────────────────────────────────────────────

function _headers(userId: string): HeadersInit {
  return { 'Content-Type': 'application/json', 'X-User-ID': userId }
}

async function _get<T>(path: string, userId: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: _headers(userId) })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function _post<T>(path: string, body: unknown, userId: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: _headers(userId),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((err as { detail: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function* streamPost(
  path: string,
  body: unknown,
  userId: string,
): AsyncGenerator<SSEEvent> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: _headers(userId),
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      if (part.startsWith('data: ')) {
        yield JSON.parse(part.slice(6)) as SSEEvent
      }
    }
  }
}

// ── Companies ──────────────────────────────────────────────────────────────

export const listCompanies = (userId: string) =>
  _get<Company[]>('/api/companies', userId)

export const getCompany = (id: string, userId: string) =>
  _get<Company>(`/api/companies/${id}`, userId)

export async function* createCompany(pitch: string, userId: string) {
  yield* streamPost('/api/companies', { pitch }, userId)
}

export async function deleteCompany(id: string, userId: string): Promise<void> {
  await fetch(`${API_BASE}/api/companies/${id}`, {
    method: 'DELETE',
    headers: _headers(userId),
  })
}

// ── Company actions ────────────────────────────────────────────────────────

export async function* chat(id: string, message: string, userId: string) {
  yield* streamPost(`/api/companies/${id}/chat`, { message }, userId)
}

export async function* task(id: string, taskDesc: string, userId: string) {
  yield* streamPost(`/api/companies/${id}/task`, { task: taskDesc }, userId)
}

// ── Approvals ──────────────────────────────────────────────────────────────

export const listApprovals = (id: string, userId: string, all = false) =>
  _get<Approval[]>(`/api/companies/${id}/approvals${all ? '?all=true' : ''}`, userId)

export const approveAction = (id: string, n: number, note: string, userId: string) =>
  _post<Approval>(`/api/companies/${id}/approvals/${n}/approve`, { note }, userId)

export const rejectAction = (id: string, n: number, note: string, userId: string) =>
  _post<Approval>(`/api/companies/${id}/approvals/${n}/reject`, { note }, userId)

// ── Team ───────────────────────────────────────────────────────────────────

export const listTeam = (id: string, userId: string) =>
  _get<Agent[]>(`/api/companies/${id}/team`, userId)

// ── Status ─────────────────────────────────────────────────────────────────

export const getStatus = (id: string, userId: string) =>
  _get<CompanyStatus>(`/api/companies/${id}/status`, userId)
