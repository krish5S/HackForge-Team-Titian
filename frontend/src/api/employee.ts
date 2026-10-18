import { useQuery } from '@tanstack/react-query'
import { request, type RecordData, type Verdict } from './client'
export interface EmployeeSubmission {
  id: string
  submitted_at: string
  filename: string
  size_bytes: number | null
  media_type: string | null
  fields: { purpose?: string; client_name?: string; attendee_names?: string; attendee_count?: number | null; notes?: string }
  status: 'UPLOADED' | 'PROCESSING' | 'PROCESSED' | 'EVALUATED' | 'FAILED'
  processing_status: 'UPLOADED' | 'PROCESSING' | 'PROCESSED' | 'FAILED'
  processing_error: string | null
  receipt_id: string | null
  decision: { verdict: Verdict; amounts: RecordData; reasons: unknown; counterfactuals: unknown } | null
}
export const employeeHistoryKey = (userId: string) => ['employee-submissions', userId]
export function useEmployeeHistory(userId: string) {
  return useQuery({ queryKey: employeeHistoryKey(userId), queryFn: ({ signal }) => request<EmployeeSubmission[]>('/employee/submissions', signal), refetchInterval: 30_000 })
}
export const submissionPath = (id: string) => `/employee/submissions/${encodeURIComponent(id)}`
