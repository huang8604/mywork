export type ReviewStatus = 'known' | 'unknown' | 'skipped'
export type ReviewSource = 'quick_review' | 'online_practice' | 'print_manual'
export type ActorType = 'web_user' | 'api_client'
export type AsyncPhase = 'idle' | 'loading' | 'success' | 'empty' | 'error'

export interface ApiMeta { page?: number; size?: number; total?: number; [key: string]: unknown }
export interface ApiEnvelope<T> { code: string; message: string; data: T; meta: ApiMeta; request_id: string }
export interface ApiErrorDetail { path?: Array<string | number>; reason?: string; current_version?: number; value?: unknown }
export interface ApiErrorBody { code: string; message: string; details: ApiErrorDetail[]; request_id?: string }

export interface WordStats {
  known_count: number; unknown_count: number; skipped_count: number; total_attempts: number
  accuracy: number | null; consecutive_known: number; consecutive_unknown: number
  last_status: ReviewStatus | null; last_reviewed_at: string | null
  last_effective_status: ReviewStatus | null; last_effective_reviewed_at: string | null
  interval_days: number; due_at: string | null; updated_at?: string
}

export interface Word {
  id: number; en_word: string; normalized_en_word: string; phonetic: string | null
  cn_meaning: string; example_sentence: string | null; is_custom: boolean; tags: string[]
  version: number; created_at: string; updated_at: string; deleted_at: string | null; stats: WordStats
}

export interface WordPayload {
  en_word: string; phonetic: string | null; cn_meaning: string; example_sentence: string | null
  is_custom: boolean; tags: string[]
}
export interface WordUpdatePayload extends WordPayload { expected_version: number }
export interface WordFilters {
  page?: number; size?: number; keyword?: string; tag?: string[]; is_custom?: boolean
  created_from?: string; created_to?: string
  sort?: 'created_at_desc' | 'created_at_asc' | 'en_word_asc' | 'en_word_desc'
}

export interface ReviewLog {
  id: number; word_id: number; session_item_id: number | null; review_round_id: number | null
  status: ReviewStatus; source: ReviewSource; actor_type: ActorType; actor_id: string | null
  client_event_id: string; duration_ms: number | null; reviewed_at: string; version: number
  created_at: string; updated_at: string; stats?: WordStats
}
export interface ReviewFilters {
  page?: number; size?: number; word_id?: number; status?: ReviewStatus; source?: ReviewSource
  actor_type?: ActorType; session_id?: number; round_id?: number; reviewed_from?: string
  reviewed_to?: string; sort?: 'reviewed_at_desc' | 'reviewed_at_asc'
}
export interface StatsSummary {
  known_count: number; unknown_count: number; skipped_count: number; total_attempts: number
  accuracy: number | null; reviewed_words: number; due_words: number
}

export interface StrategyRequest {
  new_words_limit: number; error_words_limit: number; due_words_limit: number
  custom_words_limit: number; fallback_unreviewed_days: number; seed?: number; word_ids: number[]
}
export interface SessionWord { en_word: string; phonetic: string | null; cn_meaning: string; example_sentence: string | null }
export interface PracticeItem {
  item_id: number; position: number; word_id: number; word: SessionWord
  source_categories: string[]; reason: string; latest_review_log_id: number | null
}
export interface PracticeRound {
  round_id: number; session_id: number; mode: 'offline' | 'online'; status: string; version: number
  started_at: string; completed_at: string | null; item_total: number; answered_count: number
}
export interface PracticeSession {
  session_id: number; status: 'active' | 'archived'; strategy_version: string; seed: number
  strategy_params: StrategyRequest; requested_counts: Record<string, number>; actual_counts: Record<string, number>
  created_by_actor_type: ActorType; created_by_actor_id: string | null; skill_name: string | null
  skill_version: string | null; version: number; generated_at: string; printed_at: string | null
  completed_at: string | null; archived_at: string | null; items?: PracticeItem[]; rounds?: PracticeRound[]
  title: string | null; note: string | null
  web_url?: string; print_url?: string
}
export interface ImportSummary { created: number; updated: number; skipped: number; rejected: number; unresolved?: number; unresolved_words?: string[]; total: number; dry_run: boolean; dictionary_matches?: number }
export interface EnrichedWord extends WordPayload {
  dictionary_found: boolean; source: 'dictionary-index' | 'ai' | null; missing_fields: string[]
}
export interface BatchRoundResult {
  item_id: number; status: ReviewStatus; client_event_id: string
  expected_version?: number; duration_ms?: number; reviewed_at?: string
}
export interface BatchRoundResponse { round: PracticeRound; items: ReviewLog[] }
export interface Capabilities {
  api_version: string; server_time: string; server_timezone: string
  review_statuses: ReviewStatus[]; review_modes: Array<'offline' | 'online'>
  max_import_bytes: number; max_import_rows: number; max_practice_words: number
  max_batch_results: number; idempotency_retention_days: number
  features: Record<string, boolean>
}

export type WebRole = 'admin' | 'student'
export interface AuthUser { username: string | null; role: WebRole | null; actor_type: string }
export interface LoginPayload { username: string; password: string }
export interface PasswordChangePayload { old_password: string; new_password: string }
export interface WebUser {
  id: number; username: string; role: WebRole; disabled_at: string | null; created_at: string
}
export interface UserCreatePayload { username: string; password: string; role: WebRole }
export interface UserUpdatePayload { role?: WebRole; disabled?: boolean }
