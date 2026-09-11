export interface Deck {
  id: number
  name: string
  description?: string
  source_lang: string
  target_lang: string
  card_count: number
  due_count: number
  created_at: string
}

export interface CardTagRef {
  id: number
  name: string
}

export interface CardTopicRef {
  id: number
  name: string
}

export interface CompoundPart {
  thai: string
  romanization?: string | null
  gloss?: string | null
  // 'user' = free-text gloss the learner typed themselves (compound
  // correction UI); candidate-sourced picks keep their real source (card /
  // morpheme / volubilis / lexicon), never flattened to 'user'.
  gloss_source?: 'card' | 'morpheme' | 'volubilis' | 'lexicon' | 'llm' | 'user' | null
}

export type FlagTarget = 'translation' | 'compound' | 'romanization' | 'example' | 'other'
export type OverrideTarget = 'translation' | 'compound'

export interface Card {
  id: number
  deck_id: number
  thai: string
  romanization?: string
  romanization_source?: string
  romanization_paiboon?: string
  romanization_rtgs?: string
  romanization_ipa?: string
  romanization_manual?: string
  english: string
  example_thai?: string
  example_english?: string
  notes?: string
  card_type: 'vocab' | 'phrase' | 'grammar'
  created_at: string
  tags: CardTagRef[]
  topics: CardTopicRef[]
  is_compound?: boolean | null
  compound_breakdown?: CompoundPart[] | null
  translation_status?: 'unverified' | 'ok' | 'flagged' | 'confirmed'
  translation_candidates?: string[] | null
  // User-flags-overrides overlay (present on _card_dict / _build_card_payload
  // responses; absent/undefined when no override or open flag applies)
  english_source?: 'user' | null
  compound_suppressed?: boolean | null
  compound_breakdown_source?: 'user' | null
  open_flag_targets?: FlagTarget[]
  has_open_flags?: boolean
}

export interface CardFlag {
  id: number
  card_id: number
  user_id: number
  target: FlagTarget
  note?: string | null
  flagged_value?: Record<string, unknown> | null
  status: 'open' | 'resolved' | 'dismissed'
  created_at: string
  resolved_at?: string | null
}

export interface FlagListItem extends CardFlag {
  card: { id: number; thai: string; english: string; deck_id: number } | null
}

export interface TranslationOverridePayload {
  english: string
  from_candidate?: boolean
}

export interface CompoundOverridePayload {
  suppressed?: boolean
  parts?: CompoundPart[]
}

export interface GlossCandidate {
  gloss: string
  source: NonNullable<CompoundPart['gloss_source']>
  is_current?: boolean
}

export interface SegmentationCandidate {
  parts: string[]
  is_current: boolean
}

export interface CompoundCandidates {
  segmentations: SegmentationCandidate[]
  part_glosses: Record<string, GlossCandidate[]>
  current: CompoundPart[]
  allow_free_text_gloss: boolean
}

export interface TranslationCandidates {
  candidates: string[]
  allow_free_text: boolean
}

export interface EnrichBreakdownResponse {
  status: 'not_compound' | 'no_gaps' | 'enriched'
  parts?: CompoundPart[]
  confidence?: 'high' | 'medium' | 'low' | null
  filled?: string[]
  // false when `filled` came back non-empty but confidence was too low to
  // trust — the fill was NOT written to compound_breakdown; render it as an
  // unsaved suggestion instead (see BreakdownSection's low-confidence panel)
  persisted?: boolean
  card?: CardDetail
}

export interface VerifyTranslationResponse {
  status: 'not_flagged' | 'checked'
  verdict?: 'likely_error' | 'likely_ok' | 'unsure' | null
  reason?: string | null
}

export interface UserPreferences {
  romanization_display: 'source' | 'paiboon' | 'rtgs' | 'ipa'
  romanization_fallback: 'paiboon' | 'rtgs' | 'ipa' | 'none'
  updated_at: string
}

export interface ScriptSyllable {
  syllable: string
  tone?: string
  [key: string]: unknown
}

export interface LinkedCard {
  id: number
  deck_id?: number
  thai: string
  english: string
  card_type: string
}

export interface LinkItem {
  link_id: number
  link_type: string
  note?: string | null
  card: LinkedCard
}

export interface CardLinks {
  outgoing: LinkItem[]
  incoming: LinkItem[]
}

export interface CardDetail extends Omit<Card, 'tags' | 'topics'> {
  syllable_count?: number
  tone_pattern?: string[]
  consonant_classes?: string[]
  has_cluster?: boolean
  has_rare_consonant?: boolean
  has_silent_mark?: boolean
  script_analysis?: ScriptSyllable[]
  tags: CardTagRef[]
  topics: CardTopicRef[]
  links?: CardLinks
}

export interface ReviewCard extends Card {
  schedule_id: number
  fsrs_state: string
}

/** New boundary format — page_end is ALWAYS derived, never stored */
export interface ChapterBoundary {
  idx: number
  page_start: number      // 1-indexed
  page_end?: number       // derived: only present in API responses, not submitted to PUT/POST
  title_en: string | null
  title_th: string | null
  include: boolean
  confidence: number
  signals: string[]       // e.g. ["font_outlier", "sparse_page", "template_match"]
  source: 'auto' | 'structure' | 'user' | 'example_match'
  child_upload_id: number | null
  // Enriched in GET /uploads/{id} children list
  status?: string | null
  stage?: string | null
  cards_created?: number
  card_count?: number
  due_count?: number
}

/** Per-page signal data from the ensemble detector */
export interface PageSignals {
  char_count: number
  font_outlier: boolean
  sparse_page: boolean
  template_match: boolean
  header_change: boolean
  recto_start: boolean
  lexical_hit: boolean
  topic_shift: boolean
  heuristic_score: number
  top_span_text: string | null
  top_thai_span_text: string | null
  image_xrefs: number[]
  layout_fingerprint: string
  header_text: string | null
}

/** Response from GET /uploads/{id}/split */
export interface SplitData {
  id: number
  page_count: number
  boundaries: ChapterBoundary[]
  page_signals: Record<string, PageSignals>  // 1-indexed string keys
  source_title: string | null
  stage: string
  status: string
}

/** Legacy chapter map entry (kept for backwards compat) */
export interface ChapterMapEntry {
  idx: number
  chapter_label: string
  section_label?: string | null
  page_start: number
  page_end: number
  child_upload_id?: number | null
  source_filename?: string
  status?: string | null
  stage?: string | null
  cards_created?: number
}

/** Helper to build the thumbnail URL for a page */
export function thumbnailUrl(uploadId: number, page: number): string {
  return `/api/uploads/${uploadId}/pages/${page}/thumbnail`
}

export interface Upload {
  id: number
  filename: string
  kind: 'single' | 'book_parent' | 'chapter_child'
  parent_upload_id?: number | null
  status: 'pending' | 'processing' | 'done' | 'failed' | 'awaiting_confirmation'
  stage: 'queued' | 'ocr' | 'generating' | 'tagging' | 'complete' | 'splitting' | 'awaiting_confirmation' | 'dispatching'
  deck_id?: number
  source_title?: string | null
  chapter_label?: string | null
  section_label?: string | null
  cards_created: number
  total_pages?: number
  pages_processed: number
  attempts: number
  ocr_engine_used?: string
  ocr_confidence?: number
  error_message?: string
  created_at: string
  // book_parent rollup (present on GET /uploads/{id} and /uploads/active)
  chapter_map?: ChapterBoundary[]   // new format (boundaries)
  page_count?: number
  chapters_total?: number
  chapters_complete?: number
  chapters_failed?: number
  cards_created_total?: number
  children?: ChapterBoundary[]
}

export interface Achievement {
  key: string
  name: string
  description: string
  icon?: string
  xp_reward: number
  earned_at?: string
}

export interface Profile {
  xp: number
  level: number
  xp_next_level: number
  streak_current: number
  streak_longest: number
  achievements: Achievement[]
}

export interface Tag {
  id: number
  name: string
  description?: string
  parent_id?: number
  card_count: number
}

export interface Topic {
  id: number
  name: string
  description?: string
  parent_id?: number
  sort_order: number
  card_count: number
  avg_fsrs_difficulty?: number
  new_count?: number
  due_count?: number
}

export interface TopicTreeNode {
  id: number
  name: string
  description?: string
  parent_id?: number | null
  sort_order: number
  card_count: number
  children: TopicTreeNode[]
}

export interface TopicSummary {
  id: number
  name: string
  description?: string | null
  parent_id?: number | null
  card_count: number
  new_count: number
  due_count: number
  decks_represented: { deck_id: number; deck_name: string; card_count: number }[]
  card_type_breakdown: Record<string, number>
}

export interface TopicDuplicatePair {
  topic_a: { id: number; name: string; card_count: number }
  topic_b: { id: number; name: string; card_count: number }
  reason: string
}

export interface TagDuplicatePair {
  tag_a: { id: number; name: string; card_count: number }
  tag_b: { id: number; name: string; card_count: number }
  reason: string
}

export interface SimilarCard {
  card_id: number
  thai: string
  english: string
  card_type: string
  deck_id: number | null
  similarity: number
}

export interface DueSummary {
  total_due: number
  due_today: number
  new_cards: number
  overdue_by_7d: number
  overdue_by_30d: number
  by_deck: { deck_id: number; deck_name: string; due_count: number }[]
  by_topic: { topic_id: number; topic_name: string; due_count: number }[]
}

export interface SearchGroupingItem {
  id: number
  name: string
  card_count: number
  match_type: 'lexical' | 'semantic'
  score: number
}

export interface SearchCard {
  id: number
  deck_id: number
  thai: string
  romanization?: string
  english: string
  card_type: string
  tags: CardTagRef[]
  topics: CardTopicRef[]
  score: number
  match_type: 'exact' | 'prefix' | 'substring' | 'semantic'
}

export interface SearchStudyResult {
  query: string
  groupings: {
    topics: SearchGroupingItem[]
    tags: SearchGroupingItem[]
  }
  ad_hoc: {
    card_ids: number[]
    total: number
    topic_spread: { topic_id: number; topic_name: string; count: number }[]
    untagged_count: number
    deck_spread: { deck_id: number; deck_name: string; count: number }[]
    truncated: boolean
  }
  cards: SearchCard[]
}

export type MasteryBand = 'still_learning' | 'struggling' | 'fragile' | 'solid' | 'developing'

export interface MasteryGroup {
  id: number | string
  name: string
  total_cards: number
  reviewed_cards: number
  still_learning_count: number
  band_distribution: Partial<Record<'solid' | 'developing' | 'fragile' | 'struggling', number>>
  mean_accuracy: number | null
  mean_retention: number | null
  mastery_score: number | null
  eligible: boolean
  weak_card_ids: number[]
}

export interface DimensionRollup {
  dimension: 'topic' | 'chapter' | 'card_type'
  groups: MasteryGroup[]
  strengths: MasteryGroup[]
  weaknesses: MasteryGroup[]
}

export interface CoverageGroup {
  id: number | string
  name: string
  total_cards: number
  new_cards: number
}

export interface Pattern {
  key: string
  label: string
  subgroup_again_rate: number
  baseline_again_rate: number
  gap: number
  sample_size: number
  card_ids: number[]
}

export interface AcquisitionVsRetention {
  struggling_count: number
  fragile_count: number
  struggling_card_ids: number[]
  fragile_card_ids: number[]
}

export interface PatternsPayload {
  baseline_again_rate: number | null
  patterns: Pattern[]
  acquisition_vs_retention: AcquisitionVsRetention | null
}

export interface TrendPoint {
  year: number
  week: number
  reviews: number
  again_rate: number | null
}

export interface ProgressPayload {
  topic: DimensionRollup
  chapter: DimensionRollup
  card_type: DimensionRollup
  coverage: { topic: CoverageGroup[]; chapter: CoverageGroup[] }
  patterns: PatternsPayload
  trend: TrendPoint[]
}

export interface PracticeOption {
  card_id: number
  english: string
  source: 'target' | 'orthographic' | 'phonetic' | 'tone' | 'semantic' | 'topic' | 'same_type' | 'random'
  position: number
}

export type ExerciseType = 'mc_th_en' | 'recall_th_en'

export interface PracticeItem {
  card_id: number
  exercise_type: ExerciseType
  grading: 'binary' | 'self_rated'
  thai: string
  romanization?: string
  payload: {
    options?: PracticeOption[]
  }
  // recall_th_en only — the back face; never present on a binary-graded item.
  english?: string
  example_thai?: string
  example_english?: string
  compound_breakdown?: CompoundPart[] | null
}

export interface PracticeSession {
  session_id: number
  direction: string
  items: PracticeItem[]
}

export interface PracticeSummary {
  total: number
  by_exercise_type: Record<string, number>
  binary_accuracy: number | null
  self_rated_rating_distribution: Record<string, number>
}

export interface AtRiskCard {
  id: number
  deck_id: number
  deck_name: string
  schedule_id: number
  thai: string
  english: string
  card_type: string
  created_at: string
  fsrs_difficulty: number
  fsrs_stability: number | null
  fsrs_state: string
  fsrs_lapses: number
  fsrs_due: string | null
  last_reviewed: string | null
  days_overdue: number | null
  direction: string
}
