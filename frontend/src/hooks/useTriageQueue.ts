import { useQuery } from 'react-query'
import api from '../services/api'
import type { TriageQueueResponse } from '../types'

/**
 * Shared query key so the nav badge (Layout) and TriagePage read the same
 * cache entry — one fetch serves both. The queue is always recomputed
 * fresh server-side; there is no client cache to keep in sync beyond
 * react-query's own invalidation after a decision/undo.
 */
export function useTriageQueue() {
  return useQuery<TriageQueueResponse>(
    'triage-queue',
    () => api.get('/triage/queue').then((r) => r.data),
    { refetchInterval: 30_000 }
  )
}
