import axios from 'axios'
import type {
  Project, Codebook, Dataset, DatasetPreview, Pipeline,
  Job, AnnotationResult, DimensionMetrics, PresetInfo,
} from '../types'

const api = axios.create({ baseURL: '/api' })

// Projects
export const listProjects = () => api.get<Project[]>('/projects').then(r => r.data)
export const createProject = (data: { name: string; description?: string; llm_provider?: string; llm_model?: string; api_key?: string }) =>
  api.post<Project>('/projects', data).then(r => r.data)
export const getProject = (id: number) => api.get<Project>(`/projects/${id}`).then(r => r.data)
export const updateProject = (id: number, data: Partial<Project & { api_key: string }>) =>
  api.patch<Project>(`/projects/${id}`, data).then(r => r.data)
export const deleteProject = (id: number) => api.delete(`/projects/${id}`)

// Codebooks
export const listPresets = (projectId: number) =>
  api.get<PresetInfo[]>(`/projects/${projectId}/codebooks/presets`).then(r => r.data)
export const uploadCodebook = (projectId: number, data: { preset_name?: string; raw_json?: object }) =>
  api.post<Codebook>(`/projects/${projectId}/codebooks`, data).then(r => r.data)
export const listCodebooks = (projectId: number) =>
  api.get<Codebook[]>(`/projects/${projectId}/codebooks`).then(r => r.data)

export interface DimensionPrompt {
  dimension_name: string
  prompt: string
  version: string
  path: string
  error: string | null
}
export interface AutoPromptResponse {
  prompts: DimensionPrompt[]
}
export const autoGeneratePrompt = (projectId: number, codebookId: number, taskType: string = 'text_annotation') =>
  api.post<AutoPromptResponse>(
    `/projects/${projectId}/codebooks/${codebookId}/auto-prompt`,
    { task_type: taskType },
    { timeout: 180_000 },
  ).then(r => r.data)

// Datasets
export const uploadDataset = (projectId: number, file: File, isGold: boolean = false) => {
  const form = new FormData()
  form.append('file', file)
  form.append('is_gold', String(isGold))
  return api.post<Dataset>(`/projects/${projectId}/datasets`, form).then(r => r.data)
}
export const listDatasets = (projectId: number) =>
  api.get<Dataset[]>(`/projects/${projectId}/datasets`).then(r => r.data)

// Labeled-data schema validation + LLM auto-fix
export interface GoldSchema {
  name: string
  dimensions: { name: string; type: string; labels: string[] }[]
}
export interface GoldReport {
  ok: boolean
  n_items: number
  n_error_items: number
  summary: Record<string, number>
  issues: { row: number; severity: string; kind: string; dimension: string; value: any; message: string }[]
  unknown_label_values: Record<string, Record<string, number>>
  unknown_dimensions: Record<string, number>
}
export interface GoldValidation {
  filename: string
  file_type: string
  is_gold: boolean
  items: any[]
  report: GoldReport
  schema: GoldSchema
}
export interface GoldAutofix { items: any[]; trace: any[]; report: GoldReport }

export const getExpectedSchema = (projectId: number) =>
  api.get<GoldSchema>(`/projects/${projectId}/datasets/schema`).then(r => r.data)

export const validateLabeledUpload = (projectId: number, file: File, isGold: boolean = true) => {
  const form = new FormData()
  form.append('file', file)
  form.append('is_gold', String(isGold))
  return api.post<GoldValidation>(`/projects/${projectId}/datasets/validate`, form).then(r => r.data)
}

export const autofixLabeledData = (projectId: number, items: any[]) =>
  api.post<GoldAutofix>(`/projects/${projectId}/datasets/autofix`, { items }, { timeout: 180_000 })
    .then(r => r.data)

export const commitLabeledData = (
  projectId: number,
  payload: { name: string; is_gold: boolean; file_type: string; items: any[] },
) => api.post<Dataset>(`/projects/${projectId}/datasets/commit`, payload).then(r => r.data)
export const previewDataset = (projectId: number, datasetId: number) =>
  api.get<DatasetPreview>(`/projects/${projectId}/datasets/${datasetId}`).then(r => r.data)
export const deleteDataset = (projectId: number, datasetId: number) =>
  api.delete(`/projects/${projectId}/datasets/${datasetId}`)

// Pipelines
export const decomposePipeline = (projectId: number) =>
  api.post<Pipeline>(`/projects/${projectId}/pipelines/decompose`).then(r => r.data)
export const listPipelines = (projectId: number) =>
  api.get<Pipeline[]>(`/projects/${projectId}/pipelines`).then(r => r.data)
export const getPipeline = (projectId: number, pipelineId: number) =>
  api.get<Pipeline>(`/projects/${projectId}/pipelines/${pipelineId}`).then(r => r.data)
export const updatePipeline = (projectId: number, pipelineId: number, steps: object[]) =>
  api.put<Pipeline>(`/projects/${projectId}/pipelines/${pipelineId}`, { steps }).then(r => r.data)

// Jobs
export const startJob = (projectId: number, datasetId: number, pipelineId: number, source = 'annotation') =>
  api.post<Job>(`/projects/${projectId}/jobs`, { dataset_id: datasetId, pipeline_id: pipelineId, source }).then(r => r.data)
export const listJobs = (projectId: number) =>
  api.get<Job[]>(`/projects/${projectId}/jobs`).then(r => r.data)
export const getJob = (projectId: number, jobId: number) =>
  api.get<Job>(`/projects/${projectId}/jobs/${jobId}`).then(r => r.data)
export const cancelJob = (projectId: number, jobId: number) =>
  api.post<Job>(`/projects/${projectId}/jobs/${jobId}/cancel`).then(r => r.data)
export const pauseJob = (projectId: number, jobId: number) =>
  api.post<Job>(`/projects/${projectId}/jobs/${jobId}/pause`).then(r => r.data)
export const resumeJob = (projectId: number, jobId: number) =>
  api.post<Job>(`/projects/${projectId}/jobs/${jobId}/resume`).then(r => r.data)

// Results
export const getResults = (projectId: number, jobId: number, params?: { limit?: number; offset?: number; dimension?: string }) =>
  api.get<AnnotationResult[]>(`/projects/${projectId}/jobs/${jobId}/results`, { params }).then(r => r.data)
export const getMetrics = (projectId: number, jobId: number) =>
  api.get<DimensionMetrics[]>(`/projects/${projectId}/jobs/${jobId}/results/metrics`).then(r => r.data)
export const getConfusionMatrix = (projectId: number, jobId: number, dimension: string) =>
  api.get<{ classes: string[]; matrix: Record<string, Record<string, number>> }>(
    `/projects/${projectId}/jobs/${jobId}/results/confusion`, { params: { dimension } }
  ).then(r => r.data)
export interface FeedbackEvidence {
  result_id: number
  item_id: number
  content: string
  context: string
  gold_label: string
  predicted_label: string
  reasoning: string
  is_mismatch: boolean
  match_status?: 'missing' | 'match' | 'partial' | 'mismatch'
}
export const getFeedbackEvidence = (
  projectId: number,
  jobId: number,
  dimension: string,
  params?: { limit?: number; offset?: number; mismatches_only?: boolean },
) =>
  api.get<FeedbackEvidence[]>(`/projects/${projectId}/jobs/${jobId}/results/evidence`, {
    params: { dimension, ...(params || {}) },
  }).then(r => r.data)
export const exportResults = (projectId: number, jobId: number, format: 'csv' | 'json' = 'csv') =>
  api.get(`/projects/${projectId}/jobs/${jobId}/results/export`, { params: { format }, responseType: format === 'csv' ? 'blob' : 'json' })

// Seeds + backend config
export interface SeedDatasetInfo {
  id: string
  label: string
  filename: string
  role: 'gold' | 'reference' | string
  description: string
  available: boolean
  path: string
}
export const listSeedDatasets = (projectId: number) =>
  api.get<SeedDatasetInfo[]>(`/projects/${projectId}/datasets/seeds/available`).then(r => r.data)
export const loadSeedDataset = (projectId: number, seedId: string, isGold?: boolean) =>
  api.post<Dataset>(`/projects/${projectId}/datasets/seeds/load`, { seed_id: seedId, is_gold: isGold ?? null }).then(r => r.data)

export interface BackendConfig {
  openai_key_loaded: boolean
  anthropic_key_loaded: boolean
  max_concurrency: number
}
export const getBackendConfig = () => api.get<BackendConfig>('/config').then(r => r.data)

// CodebookAgent — drafts
export interface CodebookDraft {
  id: number
  source: 'upload' | 'paste' | 'preset' | 'scratch' | string
  source_filename: string
  source_bytes: number
  status: 'pending' | 'ingesting' | 'drafting' | 'ready' | 'failed' | string
  error_message: string
  draft_json: Record<string, any>
  warnings: string[]
  critic_flags: Array<{ severity: string; dim?: string; message: string }>
  has_cleaned_data: boolean
  cleaned_data_rows: number
  drafter_model: string
  accepted_for_project_id: number | null
  created_at: string | null
  updated_at: string | null
}

export const uploadCodebookDraft = async (projectId: number, file: File): Promise<CodebookDraft> => {
  const form = new FormData()
  form.append('file', file)
  form.append('project_id', String(projectId))
  const r = await api.post<CodebookDraft>('/codebook-drafts/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 240_000,
  })
  return r.data
}

export const pasteCodebookDraft = (projectId: number, text: string) =>
  api.post<CodebookDraft>('/codebook-drafts', { source: 'paste', project_id: projectId, text }, { timeout: 240_000 })
     .then(r => r.data)

export const presetCodebookDraft = (preset_name: string) =>
  api.post<CodebookDraft>('/codebook-drafts', { source: 'preset', preset_name })
     .then(r => r.data)

export const getCodebookDraft = (draftId: number) =>
  api.get<CodebookDraft>(`/codebook-drafts/${draftId}`).then(r => r.data)

export const deleteCodebookDraft = (draftId: number) =>
  api.delete(`/codebook-drafts/${draftId}`)

export const patchCodebookDraft = (draftId: number, draftJson: Record<string, any>) =>
  api.patch<CodebookDraft>(`/codebook-drafts/${draftId}`, { draft_json: draftJson })
     .then(r => r.data)

export const acceptCodebookDraft = (projectId: number, draftId: number) =>
  api.post<Codebook>(`/projects/${projectId}/codebooks/accept-draft`, { draft_id: draftId })
     .then(r => r.data)

export const artifactDownloadUrl = (draftId: number, filename: string) =>
  `/api/codebook-drafts/${draftId}/artifact/${filename}`

// Prompt optimization workbench
export interface OptimizerInfo {
  name: string
  label: string
  description: string
  role: 'method' | 'baseline' | string
}
export interface OptimizerRun {
  id: number
  project_id: number
  gold_dataset_id: number | null
  optimizer_name: string
  dimension_name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  budget: number
  train_frac: number
  initial_score: number
  final_score: number
  trajectory: any[]
  artifact: Record<string, any>
  optimized_prompt: string
  total_tokens: number
  error: string
  created_at: string | null
  updated_at: string | null
}
export const listAvailableOptimizers = (projectId: number) =>
  api.get<OptimizerInfo[]>(`/projects/${projectId}/optimizer-runs/available`).then(r => r.data)
export const listOptimizerRuns = (projectId: number) =>
  api.get<OptimizerRun[]>(`/projects/${projectId}/optimizer-runs`).then(r => r.data)
export const getOptimizerRun = (projectId: number, runId: number) =>
  api.get<OptimizerRun>(`/projects/${projectId}/optimizer-runs/${runId}`).then(r => r.data)
export const startOptimizerRun = (
  projectId: number,
  body: {
    optimizer_name: string
    dimension_name: string
    gold_dataset_id: number
    budget?: number
    train_frac?: number
    val_frac?: number
    test_frac?: number
  }
) => api.post<OptimizerRun>(`/projects/${projectId}/optimizer-runs`, body).then(r => r.data)
export const patchOptimizerRun = (
  projectId: number, runId: number,
  patch: { optimized_prompt?: string },
) => api.patch<OptimizerRun>(`/projects/${projectId}/optimizer-runs/${runId}`, patch).then(r => r.data)
export const deleteOptimizerRun = (projectId: number, runId: number) =>
  api.delete(`/projects/${projectId}/optimizer-runs/${runId}`)
export const cancelOptimizerRun = (projectId: number, runId: number) =>
  api.post(`/projects/${projectId}/optimizer-runs/${runId}/cancel`).then(r => r.data)

// Reflection memory (cumulative rules learned across reflect_agent sessions)
export interface MemoryRule {
  id?: string
  boundary?: string
  rule?: string
  target_labels?: string[]
  positive_cues?: string[]
  negative_cues?: string[]
  [k: string]: any
}
export interface MemoryVersion {
  id: number
  dimension_name: string
  version: number
  n_rules: number
  new_rules_count: number
  source_optimizer_run_id: number | null
  rules: MemoryRule[]
  feedback_text: string | null
  created_at: string | null
}
export const listMemoryVersions = (projectId: number, dimension?: string) => {
  const params = dimension ? { dimension } : {}
  return api.get<MemoryVersion[]>(`/projects/${projectId}/memory`, { params }).then(r => r.data)
}
export const submitMemoryFeedback = (projectId: number, dimensionName: string, feedback: string) =>
  api.post<MemoryVersion>(`/projects/${projectId}/memory/feedback`, { dimension_name: dimensionName, feedback }).then(r => r.data)
export const previewPrompt = (projectId: number, dimensionName: string) =>
  api.post<{ dimension_name: string; pipeline_id: number; memory_version: number; old_prompt: string; new_prompt: string }>(
    `/projects/${projectId}/memory/preview-prompt`, { dimension_name: dimensionName }
  ).then(r => r.data)
export const commitPrompt = (projectId: number, dimensionName: string, newPrompt: string) =>
  api.post<{ ok: boolean; pipeline_id: number; dimension_name: string }>(
    `/projects/${projectId}/memory/commit-prompt`, { dimension_name: dimensionName, new_prompt: newPrompt }
  ).then(r => r.data)
export const previewFeedbackBatch = (projectId: number, dimensionName: string, feedbacks: string[]) =>
  api.post<{
    dimension_name: string
    pipeline_id: number
    memory_version: number
    old_prompt: string
    new_prompt: string
    rules: MemoryRule[]
    feedback_text: string
  }>(`/projects/${projectId}/memory/preview-feedback-batch`, { dimension_name: dimensionName, feedbacks }).then(r => r.data)
export const commitFeedbackBatch = (
  projectId: number,
  dimensionName: string,
  feedbacks: string[],
  rules: MemoryRule[],
  newPrompt: string,
) =>
  api.post<{ ok: boolean; pipeline_id: number; dimension_name: string; memory: MemoryVersion }>(
    `/projects/${projectId}/memory/commit-feedback-batch`,
    { dimension_name: dimensionName, feedbacks, rules, new_prompt: newPrompt },
  ).then(r => r.data)
export const deleteMemoryVersion = (projectId: number, versionId: number) =>
  api.delete(`/projects/${projectId}/memory/${versionId}`)

export default api
