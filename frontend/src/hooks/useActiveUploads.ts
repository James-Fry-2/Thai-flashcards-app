import { useQueryClient, useQuery } from 'react-query'
import api from '../services/api'
import type { Upload } from '../types'

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'awaiting_confirmation'])

function hasActive(uploads: Upload[]) {
  return uploads.some((u) => ACTIVE_STATUSES.has(u.status))
}

/**
 * Polls GET /uploads/active every 2s while any upload is non-terminal.
 * Invalidates the 'decks' query when an upload transitions to 'done'.
 */
export function useActiveUploads() {
  const qc = useQueryClient()

  return useQuery<Upload[]>(
    'activeUploads',
    async () => {
      // Snapshot previous data before the fetch so we can detect transitions
      const prev = qc.getQueryData<Upload[]>('activeUploads') ?? []
      const prevById = new Map(prev.map((u) => [u.id, u]))

      const data: Upload[] = await api.get('/uploads/active').then((r) => r.data)

      // Invalidate decks whenever an upload just became done
      for (const u of data) {
        const p = prevById.get(u.id)
        if ((!p || p.status !== 'done') && u.status === 'done') {
          qc.invalidateQueries('decks')
        }
      }

      return data
    },
    {
      refetchInterval: (data) => (data && hasActive(data) ? 2000 : false),
    }
  )
}
