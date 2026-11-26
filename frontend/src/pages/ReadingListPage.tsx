import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from 'react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2, MessagesSquare, ListOrdered, ShieldAlert, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'
import api from '../services/api'
import KnownBar from '../components/reading/KnownBar'
import { formatCost } from '../components/reading/CostDetails'
import type { GeneratedKind, GeneratedTextSummary, ReadableUpload, ReadingSources } from '../types'

const KIND_OPTIONS: { value: GeneratedKind; label: string; description: string; icon: JSX.Element }[] = [
  {
    value: 'dialogue',
    label: 'Dialogue',
    description: 'A short everyday conversation using the words',
    icon: <MessagesSquare size={16} />,
  },
  {
    value: 'sentences',
    label: 'Example sentences',
    description: '2–3 sentences for each word',
    icon: <ListOrdered size={16} />,
  },
]

export default function ReadingListPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: texts = [], isLoading: textsLoading } = useQuery<GeneratedTextSummary[]>('reading-texts', () =>
    api.get('/reading/texts').then((r) => r.data),
  )
  const { data: sources } = useQuery<ReadingSources>('reading-sources', () =>
    api.get('/reading/sources').then((r) => r.data),
  )

  const [kind, setKind] = useState<GeneratedKind>('dialogue')
  const [source, setSource] = useState('')

  const generate = useMutation(
    () => {
      const [type, id] = source.split(':')
      const body = type === 'topic' ? { kind, topic_id: Number(id) } : { kind, upload_id: Number(id) }
      // Two model calls (write, then check): allow well over the default timeout.
      return api.post('/reading/texts', body, { timeout: 240_000 }).then((r) => r.data as { id: number })
    },
    {
      onSuccess: ({ id }) => {
        qc.invalidateQueries('reading-texts')
        navigate(`/read/texts/${id}`)
      },
    },
  )

  return (
    <div className="space-y-8 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold">Read</h1>
        <p className="text-sm text-gray-500 mt-1">
          Practise reading with dialogues and example sentences written around your own vocabulary. Words you know are
          highlighted; tap any word to look it up or add it as a card.
        </p>
      </div>

      <section className="card space-y-4 border-brand-100">
        <div className="flex items-center gap-2 font-semibold text-gray-900">
          <Sparkles size={16} className="text-brand-600" /> Create something to read
        </div>

        <div className="grid sm:grid-cols-2 gap-2">
          {KIND_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => setKind(o.value)}
              disabled={generate.isLoading}
              className={`text-left rounded-xl border px-3 py-2.5 transition-colors ${
                kind === o.value ? 'border-brand-500 bg-brand-50' : 'border-gray-200 hover:border-brand-200'
              }`}
            >
              <span className="flex items-center gap-2 font-medium text-gray-800">
                {o.icon}
                {o.label}
              </span>
              <span className="block text-xs text-gray-500 mt-0.5">{o.description}</span>
            </button>
          ))}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="reading-source" className="block text-sm font-medium text-gray-700">
            Built around the words in
          </label>
          <select
            id="reading-source"
            value={source}
            disabled={generate.isLoading}
            onChange={(e) => setSource(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          >
            <option value="">Choose a topic or chapter…</option>
            {sources && sources.topics.length > 0 && (
              <optgroup label="Topics">
                {sources.topics.map((t) => (
                  <option key={t.id} value={`topic:${t.id}`}>
                    {t.name} ({t.card_count} cards)
                  </option>
                ))}
              </optgroup>
            )}
            {sources && sources.chapters.length > 0 && (
              <optgroup label="Chapters">
                {sources.chapters.map((c) => (
                  <option key={c.upload_id} value={`upload:${c.upload_id}`}>
                    {c.book_title ? `${c.book_title} · ` : ''}
                    {c.title} ({c.card_count} cards)
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <p className="text-xs text-gray-400">
            Uses the words you&apos;re learning first. Claude writes the text, then a second pass checks it for
            natural Thai and accurate English.
          </p>
        </div>

        <button
          onClick={() => generate.mutate()}
          disabled={!source || generate.isLoading}
          className="btn-primary flex items-center gap-2 disabled:opacity-50"
        >
          {generate.isLoading ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          {generate.isLoading ? 'Writing and checking… (up to a minute)' : 'Create'}
        </button>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Your texts</h2>
        {textsLoading ? (
          <div className="card text-gray-400 text-sm">Loading…</div>
        ) : texts.length === 0 ? (
          <div className="card text-gray-500 text-sm">Nothing yet. Create your first dialogue above.</div>
        ) : (
          <div className="card divide-y divide-gray-100 p-0">
            {texts.map((t) => (
              <button
                key={t.id}
                onClick={() => navigate(`/read/texts/${t.id}`)}
                className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-center gap-4"
              >
                <span className="text-gray-400 shrink-0">
                  {t.kind === 'dialogue' ? <MessagesSquare size={16} /> : <ListOrdered size={16} />}
                </span>
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-medium text-gray-900 truncate">{t.title}</span>
                    <span className="text-xs text-gray-400 shrink-0 flex items-center gap-1">
                      {!t.checked && <ShieldAlert size={12} className="text-amber-500" aria-label="Not checked" />}
                      {t.scope_label} · {new Date(t.created_at).toLocaleDateString()}
                      {t.cost != null && <> · {formatCost(t.cost)}</>}
                    </span>
                  </div>
                  <KnownBar stats={t} />
                </div>
                <div className="w-14 text-right shrink-0">
                  <span className="text-lg font-semibold text-gray-800">{t.known_pct ?? 0}%</span>
                  <span className="block text-[11px] text-gray-400 -mt-0.5">known</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <UploadedPages />
    </div>
  )
}

/** The original uploaded-page reader, kept but tucked away. */
function UploadedPages() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const { data: uploads = [], isLoading } = useQuery<ReadableUpload[]>(
    'reading-uploads',
    () => api.get('/reading/uploads').then((r) => r.data),
    { enabled: open },
  )
  const groups = useMemo(() => {
    const map = new Map<string, ReadableUpload[]>()
    for (const u of uploads) {
      const key = u.book_title ?? 'Other uploads'
      map.set(key, [...(map.get(key) ?? []), u])
    }
    return [...map.entries()]
  }, [uploads])

  async function openUpload(uploadId: number) {
    try {
      const r = await api.get(`/reading/uploads/${uploadId}/first-page`)
      navigate(`/read/${uploadId}/${r.data.page_index}`)
    } catch {
      toast.error('No readable pages')
    }
  }

  return (
    <details className="group" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-sm font-semibold text-gray-500 uppercase tracking-wide select-none">
        Your uploaded pages
      </summary>
      <div className="mt-3 space-y-4">
        {isLoading && <div className="card text-gray-400 text-sm">Loading…</div>}
        {groups.map(([group, items]) => (
          <div key={group} className="space-y-1.5">
            <p className="text-xs text-gray-400">{group}</p>
            <div className="card divide-y divide-gray-100 p-0">
              {items.map((u) => (
                <button
                  key={u.upload_id}
                  onClick={() => openUpload(u.upload_id)}
                  className="w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors flex items-center gap-4"
                >
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm text-gray-800 truncate">{u.title}</span>
                      <span className="text-xs text-gray-400 shrink-0">
                        {u.pages} {u.pages === 1 ? 'page' : 'pages'}
                      </span>
                    </div>
                    <KnownBar stats={u} />
                  </div>
                  <span className="w-10 text-right text-sm font-medium text-gray-700 shrink-0">
                    {u.known_pct ?? 0}%
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </details>
  )
}
