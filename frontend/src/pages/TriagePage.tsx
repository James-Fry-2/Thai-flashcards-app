import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from 'react-query'
import toast from 'react-hot-toast'
import { HelpCircle, Sparkles, Check } from 'lucide-react'
import { clsx } from 'clsx'
import api from '../services/api'
import { useTriageQueue } from '../hooks/useTriageQueue'
import type {
  AiVerdict,
  CompoundPart,
  TriageDecision,
  TriageDecisionsResponse,
  TriageEnrichResultItem,
  TriageTranslationItem,
  TriageVerifyResultItem,
} from '../types'
import CardDetailDrawer from '../components/CardDetailDrawer'
import TranslationRow from '../components/triage/TranslationRow'
import CompoundGapRow from '../components/triage/CompoundGapRow'
import OpenFlagRow from '../components/triage/OpenFlagRow'
import SuggestedRow from '../components/triage/SuggestedRow'
import KeepAllConfirmPanel from '../components/triage/KeepAllConfirmPanel'
import ShortcutsSheet from '../components/triage/ShortcutsSheet'

type TabKey = 'translation' | 'compound_gap' | 'open_flags' | 'suggested'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'translation', label: 'Translations' },
  { key: 'compound_gap', label: 'Compound gaps' },
  { key: 'open_flags', label: 'Open flags' },
  { key: 'suggested', label: 'Suggested' },
]

interface SessionSummary {
  kept: number
  corrected: number
  glossesFilled: number
  suppressed: number
  appliedFromSuggestions: number
  skipped: number
  undone: number
}

const EMPTY_SUMMARY: SessionSummary = {
  kept: 0, corrected: 0, glossesFilled: 0, suppressed: 0,
  appliedFromSuggestions: 0, skipped: 0, undone: 0,
}

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

export default function TriagePage() {
  const qc = useQueryClient()
  const { data: queue, isLoading } = useTriageQueue()

  const [tab, setTab] = useState<TabKey>('translation')
  const [focusedIndex, setFocusedIndex] = useState(0)
  const [drawerCardId, setDrawerCardId] = useState<number | null>(null)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [summary, setSummary] = useState<SessionSummary>(EMPTY_SUMMARY)
  const [lastAction, setLastAction] = useState<{ batchId?: string; eventId?: number } | null>(null)
  const [propagationBanner, setPropagationBanner] = useState<
    {
      target: 'translation' | 'compound'
      action: 'correct' | 'edit_gloss' | 'suppress' | 'keep'
      count: number
      cardIds: number[]
      sourceEventId: number
      payload: Record<string, unknown> | undefined
    } | null
  >(null)

  // Translation tab client state (never persisted until a decision is made)
  const [verdicts, setVerdicts] = useState<Record<number, { verdict: AiVerdict; reason: string | null }>>({})
  const [checkingIds, setCheckingIds] = useState<Set<number>>(new Set())
  const [correctOpenId, setCorrectOpenId] = useState<number | null>(null)
  const [keepAllOpen, setKeepAllOpen] = useState(false)

  // Compound tab client state
  const [fillingIds, setFillingIds] = useState<Set<number>>(new Set())
  const [editingPart, setEditingPart] = useState<{ cardId: number; thai: string } | null>(null)
  const [groupByMissingPart, setGroupByMissingPart] = useState(false)

  // Suggested tab: locally-dismissed ("Not here") suggestions, no event
  const [ignoredSuggestions, setIgnoredSuggestions] = useState<Set<string>>(new Set())

  const translationItems = queue?.groups.translation ?? []
  const compoundItems = queue?.groups.compound_gap ?? []
  const openFlagItems = queue?.groups.open_flags ?? []
  const suggestedItems = (queue?.groups.suggested ?? []).filter(
    (it) => !ignoredSuggestions.has(`${it.card_id}:${it.target}`)
  )

  const listLength =
    tab === 'translation' ? translationItems.length :
    tab === 'compound_gap' ? compoundItems.length :
    tab === 'open_flags' ? openFlagItems.length : suggestedItems.length

  useEffect(() => {
    setFocusedIndex((i) => Math.min(i, Math.max(listLength - 1, 0)))
  }, [listLength, tab])

  // Sub-groups for the translation tab, once any verdict exists
  const hasVerdicts = Object.keys(verdicts).length > 0
  const translationBuckets = useMemo(() => {
    if (!hasVerdicts) return null
    const buckets: Record<'unchecked' | AiVerdict, TriageTranslationItem[]> = {
      unchecked: [], likely_error: [], unsure: [], likely_ok: [],
    }
    for (const item of translationItems) {
      const v = verdicts[item.card_id]
      buckets[v ? v.verdict : 'unchecked'].push(item)
    }
    return buckets
  }, [translationItems, verdicts, hasVerdicts])

  const uncheckedCount = translationItems.filter((i) => !verdicts[i.card_id]).length
  const likelyOkItems = translationItems.filter((i) => verdicts[i.card_id]?.verdict === 'likely_ok')

  function invalidateQueue() {
    qc.invalidateQueries('triage-queue')
  }

  // ---------------------------------------------------------------------
  // AI checks
  // ---------------------------------------------------------------------

  async function runVerify(cardIds: number[]) {
    if (cardIds.length === 0) return
    setCheckingIds((s) => new Set([...s, ...cardIds]))
    try {
      for (const batch of chunk(cardIds, 50)) {
        const { data } = await api.post('/triage/verify-translations', { card_ids: batch })
        const results = data.items as TriageVerifyResultItem[]
        setVerdicts((prev) => {
          const next = { ...prev }
          for (const r of results) {
            if (r.status === 'checked' && r.verdict) next[r.card_id] = { verdict: r.verdict, reason: r.reason ?? null }
          }
          return next
        })
        const errors = results.filter((r) => r.status === 'error')
        if (errors.length > 0) toast.error(`${errors.length} translation check(s) failed`)
      }
    } finally {
      setCheckingIds((s) => {
        const next = new Set(s)
        cardIds.forEach((id) => next.delete(id))
        return next
      })
    }
  }

  async function runEnrich(cardIds: number[]) {
    if (cardIds.length === 0) return
    setFillingIds((s) => new Set([...s, ...cardIds]))
    try {
      let filledCount = 0
      let lowConfidenceCount = 0
      for (const batch of chunk(cardIds, 50)) {
        const { data } = await api.post('/triage/enrich-breakdowns', { card_ids: batch })
        const results = data.items as TriageEnrichResultItem[]
        filledCount += results.filter((r) => r.status === 'enriched').length
        lowConfidenceCount += results.filter((r) => r.status === 'low_confidence').length
        const errors = results.filter((r) => r.status === 'error')
        if (errors.length > 0) toast.error(`${errors.length} enrichment(s) failed`)
      }
      if (filledCount > 0) {
        setSummary((s) => ({ ...s, glossesFilled: s.glossesFilled + filledCount }))
        toast.success(`Filled ${filledCount} breakdown${filledCount === 1 ? '' : 's'}`)
      }
      if (lowConfidenceCount > 0) {
        // Nothing was written to these cards — enrich_breakdown()'s own
        // confidence guard declined the fill. Say so explicitly rather than
        // folding it into "no gaps", which would misleadingly imply there
        // was nothing to fill in the first place.
        toast(
          `${lowConfidenceCount} fill${lowConfidenceCount === 1 ? '' : 's'} came back too low-confidence to save`,
          { icon: '⚠️' }
        )
      }
      if (filledCount === 0 && lowConfidenceCount === 0) {
        toast('No gaps could be filled', { icon: 'ℹ️' })
      }
      invalidateQueue()
    } finally {
      setFillingIds((s) => {
        const next = new Set(s)
        cardIds.forEach((id) => next.delete(id))
        return next
      })
    }
  }

  // ---------------------------------------------------------------------
  // Decisions + undo
  // ---------------------------------------------------------------------

  const decisionsMutation = useMutation(
    (decisions: TriageDecision[]) =>
      api.post('/triage/decisions', { decisions }).then((r) => r.data as TriageDecisionsResponse),
    {
      onSuccess: (data, decisions) => {
        invalidateQueue()
        if (data.events.length === 0) return

        setLastAction(data.batch_id ? { batchId: data.batch_id } : { eventId: data.events[0].event_id })

        // /triage/decisions applies every decision in order and never skips
        // one (unlike llm_fill, decisions here always produce a concrete
        // event), so events[i] corresponds positionally to decisions[i].
        const idx = data.events.findIndex((e) => e.propagation_candidates.length > 0)
        if (idx !== -1) {
          const ev = data.events[idx]
          const originDecision = decisions[idx]
          const originTarget = originDecision?.target
          const originAction = originDecision?.action
          if (
            (originTarget === 'translation' || originTarget === 'compound') &&
            (originAction === 'correct' || originAction === 'edit_gloss' || originAction === 'suppress' || originAction === 'keep')
          ) {
            setPropagationBanner({
              target: originTarget,
              action: originAction,
              count: ev.propagation_candidates.length,
              cardIds: ev.propagation_candidates,
              sourceEventId: ev.event_id,
              payload: originDecision.payload,
            })
          }
        }

        showUndoToast(data.batch_id ? { batch_id: data.batch_id } : { event_id: data.events[0].event_id })
      },
      onError: () => { toast.error('Could not save that decision') },
    }
  )

  const undoMutation = useMutation(
    (body: { batch_id?: string; event_id?: number }) =>
      api.post('/triage/undo', body).then((r) => r.data),
    {
      onSuccess: () => {
        invalidateQueue()
        toast.success('Undone')
      },
    }
  )

  function showUndoToast(body: { batch_id?: string; event_id?: number }) {
    toast((t) => (
      <div className="flex items-center gap-3">
        <span>Saved</span>
        <button
          onClick={() => {
            undoMutation.mutate(body)
            toast.dismiss(t.id)
          }}
          className="font-semibold text-brand-600 hover:underline"
        >
          Undo
        </button>
      </div>
    ))
  }

  function submitDecision(decision: TriageDecision, summaryKey?: keyof SessionSummary) {
    if (summaryKey) setSummary((s) => ({ ...s, [summaryKey]: s[summaryKey] + 1 }))
    decisionsMutation.mutate([decision])
  }

  function undoLast() {
    if (!lastAction) return
    undoMutation.mutate(lastAction.batchId ? { batch_id: lastAction.batchId } : { event_id: lastAction.eventId })
    setSummary((s) => ({ ...s, undone: s.undone + 1 }))
    setLastAction(null)
  }

  // ---------------------------------------------------------------------
  // Row action handlers
  // ---------------------------------------------------------------------

  function keepTranslation(item: TriageTranslationItem) {
    submitDecision({ card_id: item.card_id, target: 'translation', action: 'keep' }, 'kept')
  }

  function correctTranslation(item: TriageTranslationItem, english: string) {
    const v = verdicts[item.card_id]
    setCorrectOpenId(null)
    submitDecision(
      {
        card_id: item.card_id, target: 'translation', action: 'correct',
        payload: { english },
        ai_verdict: v?.verdict, ai_reason: v?.reason ?? undefined,
      },
      'corrected'
    )
  }

  function skip(summaryKeyOnly = true) {
    if (summaryKeyOnly) setSummary((s) => ({ ...s, skipped: s.skipped + 1 }))
    setFocusedIndex((i) => Math.min(i + 1, listLength - 1))
  }

  function suppressCompound(cardId: number) {
    submitDecision({ card_id: cardId, target: 'compound', action: 'suppress' }, 'suppressed')
  }

  function saveGloss(cardId: number, parts: CompoundPart[], thai: string, gloss: string) {
    const nextParts = parts.map((p) =>
      p.thai === thai ? { ...p, gloss, gloss_source: 'user' as const } : p
    )
    setEditingPart(null)
    submitDecision(
      { card_id: cardId, target: 'compound', action: 'edit_gloss', payload: { parts: nextParts } },
      'corrected'
    )
  }

  function dismissFlag(cardId: number, target: string) {
    submitDecision({ card_id: cardId, target: target as TriageDecision['target'], action: 'dismiss_flag' })
  }

  // The suggested group doesn't carry the origin action explicitly — infer
  // it from to_value's shape (null => keep, {suppressed} => suppress,
  // {english}/{parts} => correct/edit_gloss) rather than assuming every
  // translation suggestion is a 'correct'.
  function applySuggestion(item: { card_id: number; target: string; event_id: number; to_value: Record<string, unknown> | null }) {
    let decision: TriageDecision
    if (item.target === 'translation') {
      decision = item.to_value
        ? { card_id: item.card_id, target: 'translation', action: 'correct', payload: { english: item.to_value.english }, applied_from_event_id: item.event_id }
        : { card_id: item.card_id, target: 'translation', action: 'keep', applied_from_event_id: item.event_id }
    } else if (item.to_value?.suppressed) {
      decision = { card_id: item.card_id, target: 'compound', action: 'suppress', applied_from_event_id: item.event_id }
    } else {
      decision = {
        card_id: item.card_id, target: 'compound', action: 'edit_gloss',
        payload: { parts: item.to_value?.parts }, applied_from_event_id: item.event_id,
      }
    }
    submitDecision(decision, 'appliedFromSuggestions')
  }

  function ignoreSuggestion(cardId: number, target: string) {
    setIgnoredSuggestions((s) => new Set(s).add(`${cardId}:${target}`))
  }

  // ---------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------

  const stateRef = useRef({ tab, focusedIndex, translationItems, compoundItems, openFlagItems, suggestedItems, correctOpenId, editingPart })
  stateRef.current = { tab, focusedIndex, translationItems, compoundItems, openFlagItems, suggestedItems, correctOpenId, editingPart }

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
      if (isInput && e.key !== 'Enter' && e.key !== 'Escape') return

      const s = stateRef.current

      if (e.key === '?') {
        setShowShortcuts((v) => !v)
        return
      }
      if (isInput) return // Enter/Esc are handled by the row's own input

      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedIndex((i) => i + 1)
        return
      }
      if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'u') {
        undoLast()
        return
      }
      if (e.key === 's') {
        skip()
        return
      }

      if (s.tab === 'translation') {
        const item = s.translationItems[s.focusedIndex]
        if (!item) return
        if (e.key === '1') keepTranslation(item)
        if (e.key === '2') setCorrectOpenId(item.card_id)
        if (e.key === '3') runVerify([item.card_id])
      } else if (s.tab === 'compound_gap') {
        const item = s.compoundItems[s.focusedIndex]
        if (!item) return
        if (e.key === '4') runEnrich([item.card_id])
      } else if (s.tab === 'suggested') {
        const item = s.suggestedItems[s.focusedIndex]
        if (!item) return
        if (e.key === 'a') applySuggestion(item)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastAction])

  if (isLoading || !queue) {
    return <div className="text-gray-400 text-sm">Loading triage queue…</div>
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-gray-900">Triage</h1>
        <button
          onClick={() => setShowShortcuts(true)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600"
        >
          <HelpCircle size={14} /> Shortcuts (?)
        </button>
      </div>

      <div className="flex gap-1 border-b border-gray-200 mb-3">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setFocusedIndex(0) }}
            className={clsx(
              'px-3 py-2 text-sm font-medium border-b-2 -mb-px flex items-center gap-1.5',
              tab === t.key ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-500 hover:text-gray-700'
            )}
          >
            {t.label}
            <span className="px-1.5 py-0.5 rounded-full text-[11px] bg-gray-100 text-gray-500">
              {queue.counts[t.key]}
            </span>
          </button>
        ))}
      </div>

      {propagationBanner && (
        <div className="flex items-center justify-between bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-sm text-amber-800 mb-3">
          <span>
            {propagationBanner.count} other card{propagationBanner.count === 1 ? '' : 's'} show the same{' '}
            {propagationBanner.target === 'translation' ? 'translation' : 'compound breakdown'}. Apply there too?
          </span>
          <div className="flex gap-3">
            <button
              className="font-medium hover:underline"
              onClick={() => {
                decisionsMutation.mutate(
                  propagationBanner.cardIds.map((cid) => ({
                    card_id: cid,
                    target: propagationBanner.target,
                    action: propagationBanner.action,
                    applied_from_event_id: propagationBanner.sourceEventId,
                    payload: propagationBanner.payload,
                  }))
                )
                setSummary((s) => ({ ...s, appliedFromSuggestions: s.appliedFromSuggestions + propagationBanner.cardIds.length }))
                setPropagationBanner(null)
              }}
            >
              Apply
            </button>
            <button className="hover:underline" onClick={() => { setTab('suggested'); setPropagationBanner(null) }}>
              Review in Suggested
            </button>
            <button className="text-amber-600 hover:underline" onClick={() => setPropagationBanner(null)}>
              Ignore
            </button>
          </div>
        </div>
      )}

      {tab === 'translation' && (
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => runVerify(translationItems.filter((i) => !verdicts[i.card_id]).map((i) => i.card_id))}
            disabled={uncheckedCount === 0}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-brand-50 text-brand-700 hover:bg-brand-100 disabled:opacity-40"
          >
            <Sparkles size={13} /> Check all unchecked ({uncheckedCount})
          </button>
          {likelyOkItems.length > 0 && (
            <button
              onClick={() => setKeepAllOpen(true)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-green-50 text-green-700 hover:bg-green-100"
            >
              <Check size={13} /> Keep all Likely OK ({likelyOkItems.length})
            </button>
          )}
        </div>
      )}

      {tab === 'compound_gap' && (
        <div className="flex items-center gap-3 mb-2">
          <button
            onClick={() => runEnrich(compoundItems.map((i) => i.card_id))}
            disabled={compoundItems.length === 0}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-brand-50 text-brand-700 hover:bg-brand-100 disabled:opacity-40"
          >
            <Sparkles size={13} /> Fill all with AI ({compoundItems.length})
          </button>
          <label className="flex items-center gap-1.5 text-xs text-gray-500">
            <input type="checkbox" checked={groupByMissingPart} onChange={(e) => setGroupByMissingPart(e.target.checked)} />
            Group by missing part
          </label>
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        {tab === 'translation' && (
          translationItems.length === 0 ? (
            <EmptyState label="No flagged translations left" />
          ) : translationBuckets ? (
            (['likely_error', 'unsure', 'unchecked', 'likely_ok'] as const).map((bucket) =>
              translationBuckets[bucket].length === 0 ? null : (
                <div key={bucket}>
                  <div className="px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400 bg-gray-50">
                    {bucket === 'unchecked' ? 'Unchecked' : bucket === 'likely_error' ? 'Likely error' : bucket === 'unsure' ? 'Unsure' : 'Likely OK'}
                  </div>
                  {translationBuckets[bucket].map((item) => {
                    const idx = translationItems.indexOf(item)
                    return (
                      <TranslationRow
                        key={item.card_id}
                        item={item}
                        focused={idx === focusedIndex}
                        checking={checkingIds.has(item.card_id)}
                        correctOpen={correctOpenId === item.card_id}
                        verdict={verdicts[item.card_id]}
                        onKeep={() => keepTranslation(item)}
                        onCorrect={(english) => correctTranslation(item, english)}
                        onToggleCorrect={() => setCorrectOpenId((id) => (id === item.card_id ? null : item.card_id))}
                        onCheck={() => runVerify([item.card_id])}
                        onSkip={() => { setFocusedIndex(idx); skip() }}
                      />
                    )
                  })}
                </div>
              )
            )
          ) : (
            translationItems.map((item, idx) => (
              <TranslationRow
                key={item.card_id}
                item={item}
                focused={idx === focusedIndex}
                checking={checkingIds.has(item.card_id)}
                correctOpen={correctOpenId === item.card_id}
                verdict={verdicts[item.card_id]}
                onKeep={() => keepTranslation(item)}
                onCorrect={(english) => correctTranslation(item, english)}
                onToggleCorrect={() => setCorrectOpenId((id) => (id === item.card_id ? null : item.card_id))}
                onCheck={() => runVerify([item.card_id])}
                onSkip={() => { setFocusedIndex(idx); skip() }}
              />
            ))
          )
        )}

        {tab === 'compound_gap' && (
          compoundItems.length === 0 ? (
            <EmptyState label="No compound gaps left" />
          ) : (
            compoundItems.map((item, idx) => (
              <CompoundGapRow
                key={item.card_id}
                item={item}
                focused={idx === focusedIndex}
                filling={fillingIds.has(item.card_id)}
                editingPart={editingPart?.cardId === item.card_id ? editingPart.thai : null}
                onFillWithAi={() => runEnrich([item.card_id])}
                onStartEditGloss={(thai) => setEditingPart({ cardId: item.card_id, thai })}
                onSaveGloss={(thai, gloss) => saveGloss(item.card_id, item.parts, thai, gloss)}
                onCancelEditGloss={() => setEditingPart(null)}
                onSuppress={() => suppressCompound(item.card_id)}
                onWrongSplit={() => setDrawerCardId(item.card_id)}
                onSkip={() => { setFocusedIndex(idx); skip() }}
              />
            ))
          )
        )}

        {tab === 'open_flags' && (
          openFlagItems.length === 0 ? (
            <EmptyState label="No open flags left" />
          ) : (
            openFlagItems.map((item, idx) => (
              <OpenFlagRow
                key={item.flag_id}
                item={item}
                focused={idx === focusedIndex}
                onDismiss={() => dismissFlag(item.card_id, item.target)}
                onOpenDrawer={() => setDrawerCardId(item.card_id)}
              />
            ))
          )
        )}

        {tab === 'suggested' && (
          suggestedItems.length === 0 ? (
            <EmptyState label="No suggestions right now" />
          ) : (
            suggestedItems.map((item, idx) => {
              const siblingCount = suggestedItems.filter((i) => i.event_id === item.event_id).length
              return (
                <SuggestedRow
                  key={`${item.card_id}:${item.target}`}
                  item={item}
                  focused={idx === focusedIndex}
                  siblingCount={siblingCount}
                  onApply={() => applySuggestion(item)}
                  onIgnore={() => ignoreSuggestion(item.card_id, item.target)}
                  onApplyAllForEvent={() => {
                    const siblings = suggestedItems.filter((i) => i.event_id === item.event_id)
                    siblings.forEach((sib) => applySuggestion(sib))
                  }}
                />
              )
            })
          )
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
        <span>Kept: {summary.kept}</span>
        <span>Corrected: {summary.corrected}</span>
        <span>Glosses filled: {summary.glossesFilled}</span>
        <span>Suppressed: {summary.suppressed}</span>
        <span>Applied from suggestions: {summary.appliedFromSuggestions}</span>
        <span>Skipped: {summary.skipped}</span>
        <span>Undone: {summary.undone}</span>
      </div>

      {keepAllOpen && (
        <KeepAllConfirmPanel
          items={likelyOkItems}
          onCancel={() => setKeepAllOpen(false)}
          onConfirm={(cardIds) => {
            const decisions: TriageDecision[] = cardIds.map((cid) => ({
              card_id: cid, target: 'translation', action: 'keep',
              ai_verdict: 'likely_ok',
            }))
            setSummary((s) => ({ ...s, kept: s.kept + decisions.length }))
            decisionsMutation.mutate(decisions)
            setKeepAllOpen(false)
          }}
        />
      )}

      {showShortcuts && <ShortcutsSheet onClose={() => setShowShortcuts(false)} />}

      <CardDetailDrawer cardId={drawerCardId} onClose={() => setDrawerCardId(null)} />
    </div>
  )
}

function EmptyState({ label }: { label: string }) {
  return <div className="px-4 py-10 text-center text-sm text-gray-400">{label}</div>
}
