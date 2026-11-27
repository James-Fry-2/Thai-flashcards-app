import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from 'react-query'
import { ArrowLeft, Eye, EyeOff, Languages, Play, ShieldCheck, ShieldAlert, Square, Trash2 } from 'lucide-react'
import api from '../services/api'
import KnownBar from '../components/reading/KnownBar'
import { SegmentLine, WordPanel, type Selected } from '../components/reading/WordTools'
import type { GeneratedLine, GeneratedText } from '../types'
import CostDetails from '../components/reading/CostDetails'
import SpeakButton from '../components/SpeakButton'
import { useAudio, useAudioPrefs } from '../hooks/useAudio'

export default function TextReaderPage() {
  const { textId } = useParams<{ textId: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Selected | null>(null)
  const audio = useAudio()
  const { defaultSpeed } = useAudioPrefs()
  // Index of the line being read aloud by "Play all", for highlighting.
  const [playingLine, setPlayingLine] = useState<number | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [shown, setShown] = useState<Set<number>>(new Set())
  // Romanization is on by default; the choice is remembered between visits.
  const [showRoman, setShowRoman] = useState(() => localStorage.getItem('reader.showRomanization') !== 'false')
  function toggleRoman() {
    setShowRoman((v) => {
      localStorage.setItem('reader.showRomanization', String(!v))
      return !v
    })
  }

  const { data: text, isLoading, isError } = useQuery<GeneratedText>(['reading-text', textId], () =>
    api.get(`/reading/texts/${textId}`).then((r) => r.data),
  )

  const remove = useMutation(() => api.delete(`/reading/texts/${textId}`), {
    onSuccess: () => {
      qc.invalidateQueries('reading-texts')
      navigate('/read')
    },
  })

  useEffect(() => () => audio.stop(), []) // leaving the page stops playback

  useEffect(() => {
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && setSelected(null)
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  if (isLoading) return <div className="text-center py-20 text-gray-600">Loading…</div>
  if (isError || !text) {
    return (
      <div className="text-center py-20 space-y-3">
        <p className="text-gray-600">This text isn&apos;t available.</p>
        <Link to="/read" className="btn-secondary">Back to reading</Link>
      </div>
    )
  }

  const toggleLine = (i: number) =>
    setShown((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  // Sentences are grouped under the word they illustrate.
  const groups: { word: string; items: { line: GeneratedLine; i: number }[] }[] = []
  text.lines.forEach((line, i) => {
    const key = text.kind === 'sentences' ? line.word : ''
    const last = groups[groups.length - 1]
    if (last && last.word === key) last.items.push({ line, i })
    else groups.push({ word: key, items: [{ line, i }] })
  })

  // Alternate speaker colours so a dialogue is easy to follow.
  const speakers = [...new Set(text.lines.map((l) => l.speaker).filter(Boolean))]
  const speakerStyle = (s: string) =>
    speakers.indexOf(s) % 2 === 0 ? 'text-brand-700 bg-brand-50' : 'text-teal-700 bg-teal-50'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 text-sm">
        <Link to="/read" className="flex items-center gap-1 text-gray-600 hover:text-gray-600">
          <ArrowLeft size={14} /> Read
        </Link>
        <div className="text-center min-w-0">
          <span className="block font-medium text-gray-700 truncate">{text.title}</span>
          <span className="block text-xs text-gray-600 truncate">
            {text.kind === 'dialogue' ? 'Dialogue' : 'Example sentences'}
            {text.scope_label && <> · {text.scope_label}</>}
          </span>
        </div>
        <button
          onClick={() => window.confirm('Delete this text?') && remove.mutate()}
          className="p-1.5 rounded-lg text-gray-600 hover:text-red-600 hover:bg-red-50"
          aria-label="Delete text"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] items-start">
        <div className="space-y-4">
          <div className="card space-y-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <p className="text-sm text-gray-700">
                You know <span className="font-semibold text-gray-900">{text.stats.known_pct ?? 0}%</span> of the
                words in this text
                {text.stats.unknown_unique > 0 && <> · {text.stats.unknown_unique} not in your cards yet</>}
              </p>
              <CheckBadge check={text.check} />
            </div>
            <KnownBar stats={text.stats} showLegend />
            {text.usage && <CostDetails usage={text.usage} />}
          </div>

          <div className="card space-y-1">
            <div className="flex justify-end gap-4">
              <button
                onClick={() => {
                  if (playingLine !== null) {
                    audio.stop()
                    return
                  }
                  audio.playSequence(
                    text.lines.map((line, i) => ({
                      source: { kind: 'line' as const, textId: text.id, index: i },
                      thai: line.thai,
                      speed: defaultSpeed,
                    })),
                    setPlayingLine,
                  )
                }}
                className="text-xs text-gray-600 hover:text-gray-700 flex items-center gap-1 mr-auto"
              >
                {playingLine !== null ? <Square size={13} /> : <Play size={13} />}
                {playingLine !== null ? 'Stop' : text.kind === 'dialogue' ? 'Play dialogue' : 'Play all'}
              </button>
              <button
                onClick={toggleRoman}
                className="text-xs text-gray-600 hover:text-gray-700 flex items-center gap-1"
              >
                <Languages size={13} />
                {showRoman ? 'Hide romanization' : 'Show romanization'}
              </button>
              <button
                onClick={() => {
                  setShowAll((v) => !v)
                  setShown(new Set())
                }}
                className="text-xs text-gray-600 hover:text-gray-700 flex items-center gap-1"
              >
                {showAll ? <EyeOff size={13} /> : <Eye size={13} />}
                {showAll ? 'Hide all English' : 'Show all English'}
              </button>
            </div>

            {groups.map((group, g) => (
              <div key={g} className={text.kind === 'sentences' ? 'pt-3 first:pt-0' : ''}>
                {group.word && (
                  <p className="text-xs font-medium text-gray-600 uppercase tracking-wide mb-1">
                    <span className="font-thai normal-case text-sm text-gray-600">{group.word}</span>
                  </p>
                )}
                {group.items.map(({ line, i }) => {
                  const english = showAll || shown.has(i)
                  return (
                    <div
                      key={i}
                      className={`py-2 border-b border-gray-50 last:border-0 transition-colors ${
                        playingLine === i ? 'bg-brand-50/60 -mx-2 px-2 rounded-lg' : ''
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        {line.speaker && (
                          <span
                            className={`shrink-0 mt-1.5 text-xs font-medium rounded-md px-1.5 py-0.5 font-thai ${speakerStyle(
                              line.speaker,
                            )}`}
                          >
                            {line.speaker}
                          </span>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start gap-1">
                            <p className="flex-1 min-w-0 text-xl leading-loose text-gray-800 font-thai break-words">
                              <SegmentLine segments={line.segments} selected={selected} onSelect={setSelected} />
                            </p>
                            <SpeakButton
                              source={{ kind: 'line', textId: text.id, index: i }}
                              thai={line.thai}
                              className="mt-1.5 shrink-0"
                            />
                          </div>
                          {showRoman && line.romanization && (
                            <p className="text-sm text-gray-600 -mt-1 mb-0.5">{line.romanization}</p>
                          )}
                          {english ? (
                            <p className="text-sm text-gray-600">{line.english}</p>
                          ) : (
                            <button
                              onClick={() => toggleLine(i)}
                              className="text-xs text-gray-600 hover:text-gray-600"
                            >
                              Show English
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="lg:sticky lg:top-4">
          {selected ? (
            <WordPanel
              key={selected.thai}
              selected={selected}
              uploadId={text.scope === 'upload' ? text.scope_id : undefined}
              onClose={() => setSelected(null)}
              onStatus={(status) => {
                setSelected((s) => (s ? { ...s, status } : s))
                qc.invalidateQueries(['reading-text', textId])
                qc.invalidateQueries('reading-texts')
              }}
            />
          ) : (
            <div className="card text-sm text-gray-600 hidden lg:block">
              Tap a Thai word to look it up. Underlined words aren&apos;t in your cards yet.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function CheckBadge({ check }: { check: GeneratedText['check'] }) {
  if (!check?.checked) {
    return (
      <span className="flex items-center gap-1 text-xs text-amber-700" title="The checking pass didn't run for this text">
        <ShieldAlert size={13} /> Not checked
      </span>
    )
  }
  const details: string[] = []
  if (check.simplified?.length) details.push(`Simplified: replaced ${check.simplified.join(' ')}`)
  if (check.rewritten) details.push(`Rewritten by the checker: ${check.problem || 'it read unnaturally'}`)
  details.push(...check.notes.map((n) => `Line ${n.index + 1}: ${n.note}`))
  const label = check.rewritten
    ? 'Checked · rewritten to read naturally'
    : check.fixed > 0
    ? `Checked · ${check.fixed} ${check.fixed === 1 ? 'line' : 'lines'} corrected`
    : 'Checked'
  return (
    <span
      className="flex items-center gap-1 text-xs text-green-700"
      title={details.length ? details.join('\n') : 'No problems found'}
    >
      <ShieldCheck size={13} />
      {label}
    </span>
  )
}
