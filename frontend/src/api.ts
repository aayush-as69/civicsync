// Production (Vercel) serves the API from the same origin at /api; dev talks to local Flask.
const BASE = import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '/api' : 'http://127.0.0.1:5000/api')

export type Ticket = { ticket_id: string; tracking_token?: string; title?: string; summary: string; description: string; category: string; location: string; area_details?: string; urgency: string; confidence: number; analysis_provider: string; department: string; status: string; submitted_at: string; updated_at: string; resolved_at?: string; internal_note?: string; resolution_summary?: string; is_demo: boolean; history: {from?: string; to: string; actor: string; note?: string; at: string}[] }
export type Analysis = { category: string; summary: string; location?: string; urgency: string; suggested_department: string; missing_fields: string[]; confidence: number; provider: string }

async function request<T>(path: string, options: RequestInit = {}, admin = false): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (admin) headers.set('X-Demo-Role', 'admin')
  const response = await fetch(`${BASE}${path}`, { ...options, headers })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw Object.assign(new Error(body?.error?.message || 'Request failed.'), { body, status: response.status })
  return body as T
}

export const api = {
  health: () => request<{status:string; database:string; analysis:string; uagents:string; demo_mode:boolean}>('/health'),
  departments: () => request<{data:{name:string;category:string;description:string}[]}>('/departments'),
  analyze: (payload: object) => request<{data:Analysis}>('/complaints/analyze', { method: 'POST', body: JSON.stringify(payload) }),
  create: (payload: object, idempotencyKey: string) => request<{data:Ticket; idempotent_replay?:boolean}>('/complaints', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(payload) }),
  ticket: (id:string, token:string) => request<{data:Ticket}>(`/tickets/${encodeURIComponent(id)}`, { headers: { 'X-Tracking-Token': token } }),
  summary: () => request<{data:Summary}>('/dashboard/summary', {}, true),
  tickets: (query='') => request<{data:Ticket[]; meta:{total:number}}>(`/tickets${query}`, {}, true),
  status: (id:string, body: object) => request<{data:Ticket}>(`/tickets/${encodeURIComponent(id)}/status`, { method: 'PATCH', body: JSON.stringify(body) }, true),
  agentStatus: () => request<{data:AgentStatus}>('/agents/status'),
  agentEvents: () => request<{data:AgentEvent[]}>('/agents/events', {}, true),
}

export type Summary = { total:number; submitted:number; under_review:number; in_progress:number; resolved:number; by_status:Record<string,number>; by_category:Record<string,number>; by_department:Record<string,number>; recent:Ticket[]; demo_records:number }
export type AgentStatus = { agents:{name:string; responsibility:string; runtime:string; status:string; last_activity?:string}[]; agentverse:string; communication:string }
export type AgentEvent = {ticket_reference?:string; stage:string; agent:string; outcome:string; detail:string; mode:string; at:string}
