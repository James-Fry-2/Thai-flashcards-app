import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from 'react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import UploadDropzone from '../components/UploadDropzone'
import api from '../services/api'
import type { Deck, Upload } from '../types'

export default function UploadPage() {
  const [selectedDeckId, setSelectedDeckId] = useState<number | ''>('')
  const [pendingUploadId, setPendingUploadId] = useState<number | null>(null)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: decks = [] } = useQuery<Deck[]>('decks', () =>
    api.get('/decks/').then((r) => r.data)
  )

  // Poll upload status every 2s while pending/processing
  const { data: uploadStatus } = useQuery<Upload>(
    ['upload', pendingUploadId],
    () => api.get(`/uploads/${pendingUploadId}`).then((r) => r.data),
    {
      enabled: pendingUploadId != null,
      refetchInterval: (data) =>
        data?.status === 'done' || data?.status === 'failed' ? false : 2000,
      onSuccess: (data) => {
        if (data.status === 'done') {
          toast.success(`Done! ${data.cards_created} cards created`)
          qc.invalidateQueries('decks')
          if (data.deck_id) {
            setTimeout(() => navigate(`/decks/${data.deck_id}`), 1500)
          }
        }
        if (data.status === 'failed') {
          toast.error(`Upload failed: ${data.error_message}`)
        }
      },
    }
  )

  const uploadMutation = useMutation(
    async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      if (selectedDeckId) form.append('deck_id', String(selectedDeckId))
      const res = await api.post('/uploads/', form)
      return res.data as { id: number }
    },
    {
      onSuccess: (data) => {
        setPendingUploadId(data.id)
        toast.success('Upload received — processing…')
      },
    }
  )

  const isProcessing =
    uploadStatus?.status === 'pending' || uploadStatus?.status === 'processing'

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload Notes</h1>
        <p className="text-gray-500 mt-1">
          Upload a PDF or photo of your Thai learning notes. Cards are generated automatically.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Add cards to deck
        </label>
        <select
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
          value={selectedDeckId}
          onChange={(e) => setSelectedDeckId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">— No deck (import later) —</option>
          {decks.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>

      <UploadDropzone
        onFile={(file) => uploadMutation.mutate(file)}
        disabled={uploadMutation.isLoading || isProcessing}
      />

      {/* Status */}
      {uploadStatus && (
        <div className="card">
          <StatusDisplay upload={uploadStatus} />
        </div>
      )}
    </div>
  )
}

function StatusDisplay({ upload }: { upload: Upload }) {
  if (upload.status === 'done') {
    return (
      <div className="flex items-center gap-3 text-green-700">
        <CheckCircle size={20} />
        <span>
          Complete — <strong>{upload.cards_created}</strong> cards created
          {upload.ocr_engine_used && (
            <span className="text-xs text-gray-400 ml-2">via {upload.ocr_engine_used}</span>
          )}
        </span>
      </div>
    )
  }
  if (upload.status === 'failed') {
    return (
      <div className="flex items-center gap-3 text-red-600">
        <AlertCircle size={20} />
        <span>{upload.error_message || 'Upload failed'}</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-3 text-gray-600">
      <Loader2 size={20} className="animate-spin" />
      <span className="capitalize">{upload.status}…</span>
    </div>
  )
}
