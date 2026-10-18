import { useQuery } from '@tanstack/react-query'
import { request, type DecisionRow, type Filters, type Health, type ReceiptDetail } from './client'
export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: ({ signal }) => request<Health>('/health', signal) })
export function useDecisions(filters: Filters = {}) {
  const params = new URLSearchParams()
  if (filters.verdict) params.set('verdict', filters.verdict)
  if (filters.employee_id) params.set('employee_id', filters.employee_id)
  return useQuery({ queryKey: ['decisions', filters], queryFn: ({ signal }) => request<DecisionRow[]>(`/decisions?${params}`, signal) })
}
export const useReceipt = (id: string) => useQuery({ queryKey: ['receipt', id], queryFn: ({ signal }) => request<ReceiptDetail>(`/receipts/${encodeURIComponent(id)}`, signal) })
export const useReceiptFile = (id: string) => useQuery({ queryKey: ['receipt-file', id, 'original'], queryFn: ({ signal }) => request<Blob>(`/receipts/${encodeURIComponent(id)}/image?variant=original`, signal, true), retry: false })
