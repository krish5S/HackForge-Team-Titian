import { useQuery, type QueryClient } from '@tanstack/react-query'
import { request, type RecordData, type Verdict } from './client'
export interface Metrics {
  run_id: string | null; currency: string | null; evaluated: number; automatically_decided: number | null
  approved_amount: string | null; blocked_amount: string | null; pending_amount: string | null
  policy_id?: string; policy_version?: number; period?: string; verdict_counts: Record<string, number>
}
export const useMetrics = () => useQuery({ queryKey: ['metrics'], queryFn: ({ signal }) => request<Metrics>('/metrics', signal) })
export interface Clause { clause_id: string; text: string }
export interface Rule { clause_id: string; rule_type: string; source_quote: string; summary: string; parameters: RecordData }
export interface CompileResult { policy: unknown | null; flags: { code: string; clause_id: string | null; message: string }[]; trust_report: RecordData }
export interface PolicyData { id: string; version: number; source_text: string; compiled: { base_currency: string; clauses: Clause[]; rules: Rule[] }; trust_report: unknown; latest_compilation: CompileResult | null }
export interface TimelineEvent { seq: number; submitted_at: string; receipt_id: string; verdict_at_arrival: Verdict; flips: { receipt_id: string; from: Verdict; to: Verdict; reason: string }[] }
export interface Timeline { run_id: string | null; policy_version: number | null; events: TimelineEvent[] }
export interface Replay { run_id: string | null; currency: string | null; snapshot: { verdict_counts: Record<string, number>; amounts: Record<string, string>; ledger_meters: { employee_id: string; label: string; cap: string; used_after: string; remaining: string }[]; decisions: { receipt_id: string; verdict: Verdict; reimbursable: string | null; amount_at_risk: string }[] } | null }
export async function refreshResults(client: QueryClient) {
  await client.invalidateQueries({ predicate: q => q.queryKey[0] !== 'session' && q.queryKey[0] !== 'receipt-file' })
}
