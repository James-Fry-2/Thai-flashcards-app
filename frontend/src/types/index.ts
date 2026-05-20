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
