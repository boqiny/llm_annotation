export interface Project {
  id: number
  name: string
  description: string
  llm_provider: string
  llm_model: string
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface Label {
  id: number
  name: string
  definition: string
  examples: string[]
  sort_order: number
}

export interface Dimension {
  id: number
  name: string
  dim_type: string
  instructions: string
  sort_order: number
  labels: Label[]
}

export interface Codebook {
  id: number
  project_id: number
  name: string
  description: string
  raw_json: Record<string, unknown>
  dimensions: Dimension[]
}

export interface Dataset {
  id: number
  project_id: number
  name: string
  file_type: string
  total_items: number
  is_gold: boolean
}

export interface DataItem {
  id: number
  index: number
  content: string
  context: string
  metadata: Record<string, unknown>
  gold_labels: Record<string, string>
}

export interface DatasetPreview {
  dataset: Dataset
  items: DataItem[]
}

export interface PipelineStep {
  name: string
  dimensions: string[]
  prompt: string
  gate: string | null
}

export interface Pipeline {
  id: number
  project_id: number
  steps: PipelineStep[]
  auto_generated: boolean
}

export interface Job {
  id: number
  project_id: number
  dataset_id: number
  pipeline_id: number
  status: string
  total_items: number
  completed_items: number
  failed_items: number
  total_tokens: number
  total_cost: number
  created_at: string | null
  updated_at: string | null
}

export interface AnnotationResult {
  id: number
  job_id: number
  data_item_id: number
  step_order: number
  dimension_name: string
  predicted_label: string
  reasoning: string
  tokens_used: number
}

export interface PerClassMetrics {
  precision: number
  recall: number
  f1: number
  support: number
  tp: number
  fp: number
  fn: number
}

export interface MetricsData {
  accuracy: number
  macro_precision: number
  macro_recall: number
  macro_f1: number
  weighted_f1: number
  per_class: Record<string, PerClassMetrics>
  n: number
  classes: string[]
}

export interface DimensionMetrics {
  dimension: string
  metrics: MetricsData
}

export interface PresetInfo {
  name: string
  description: string
  dimensions: number
}

export interface WSProgressMessage {
  job_id: number
  completed: number
  total: number
  tokens: number
  cost: number
  status: string
  failed?: number
}
