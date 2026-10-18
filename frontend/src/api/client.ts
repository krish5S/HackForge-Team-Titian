export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api').replace(/\/$/, '')
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}
export async function request<T>(path: string, signal?: AbortSignal, blob = false, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, signal, credentials: 'include', cache: 'no-store' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(body?.error?.message || `Request failed (${response.status}).`, response.status)
  }
  if (response.status === 204) return undefined as T
  return (blob ? await response.blob() : await response.json()) as T
}
export type Verdict = 'APPROVE' | 'NEEDS_REVIEW' | 'REJECT'
export interface DecisionRow {
  receipt_id: string; employee_id: string; employee_name: string
  merchant_name: string | null; transaction_date: string | null; verdict: Verdict
  claimed: string | null; proposed: string | null; reimbursable: string | null
  amount_at_risk: string | null; risk_score: number | null; top_reason: string | null
}
export type RecordData = Record<string, unknown>
export interface ReceiptDetail {
  receipt_id: string; employee_id: string; employee_name: string
  submission: RecordData; processed_receipt: RecordData
  decision: (RecordData & Partial<DecisionRow>) | null; evaluation_run_id: string | null
}
export interface Health { status: string; service: string; database: string; receipt_count: number; data_loaded: boolean }
export interface Filters { verdict?: string; employee_id?: string }

export function record(value: unknown): RecordData {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RecordData : {}
}
