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

export interface Card {
  id: number
  deck_id: number
  thai: string
  romanization?: string
  english: string
  example_thai?: string
  example_english?: string
  notes?: string
  card_type: 'vocab' | 'phrase' | 'grammar'
  created_at: string
  tags: CardTagRef[]
  topics: CardTopicRef[]
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

export interface Upload {
  id: number
  filename: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  deck_id?: number
  cards_created: number
  ocr_engine_used?: string
  error_message?: string
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
