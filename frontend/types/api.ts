export const VEHICLE_FIELDS = [
  'make',
  'model',
  'badge',
  'transmission_type',
  'fuel_type',
  'drive_type',
] as const

export type VehicleField = (typeof VEHICLE_FIELDS)[number]
export type ExtractionMode = 'NLP' | 'LLM' | 'HYBRID'
export type MatchStatus =
  | 'MATCHED'
  | 'NO_CATALOGUE_MATCH'
  | 'NO_VEHICLE'
  | 'AMBIGUOUS'
  | 'INCOMPLETE'
  | 'ERROR'

export type VehicleFields = Record<VehicleField, string | null>

export interface MatchRequest {
  query: string
  mode: ExtractionMode
}

export interface MatchResponse {
  query: string
  mode: ExtractionMode
  vehicle_id: string | null
  confidence: number
  status: MatchStatus
  is_complete: boolean
  is_decisive: boolean
  source: 'NLP' | 'LLM' | 'HYBRID_NLP' | 'HYBRID_LLM'
  model_name: string
  components_used: string
  fields: VehicleFields
  latency_ms: number
  llm_cost_usd: number | null
  llm_input_tokens: number
  llm_output_tokens: number
  llm_batch_number: number | null
  llm_batch_size: number | null
  error: string | null
}

export interface BatchMatchRecord extends MatchResponse {
  row_number: number
}

export interface BatchStatistics {
  total_queries: number
  matched_queries: number
  match_rate_percent: number
  complete_queries: number
  complete_percent: number
  decisive_queries: number
  decisive_percent: number
  error_queries: number
  average_confidence: number
  processing_ms: number
  average_record_latency_ms: number
  llm_requests: number
  total_llm_cost_usd: number
  llm_input_tokens: number
  llm_output_tokens: number
  status_counts: Record<string, number>
  source_counts: Record<string, number>
  model_counts: Record<string, number>
  field_coverage_percent: Record<VehicleField, number>
}

export interface BatchMatchResponse {
  file_name: string
  mode: ExtractionMode
  statistics: BatchStatistics
  records: BatchMatchRecord[]
}

export interface DatabaseStatus {
  connected: boolean
  database: string | null
  host: string | null
  catalogue_records: number
  catalogue_loaded: boolean
  nlp_ready?: boolean
  nlp_model?: string
  message?: string
}
