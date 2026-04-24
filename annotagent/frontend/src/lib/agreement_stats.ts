// Per-dimension inter-annotator agreement numbers derived from the dataset audit
// of data/raw/ (Fiona + Chang double annotations) on 2026-04-20.
// Surfaced in the Codebook browser to motivate the calibration-rule story.

export type DimStat = {
  dim: string
  raw_agreement: number | null   // 0..1, null when joint coverage too sparse to report
  n_joint: number                // number of quotes both annotators labeled this dim on
  n_agreed: number | null        // size of agreed subset usable for supervision
}

export type CodebookStats = {
  n_fiona: number
  n_chang: number
  n_dual: number
  n_agreed_any: number | null    // items with at least one dim of supervised agreement
  multi_label?: {
    theme: string
    exact_match: number
    mean_jaccard: number
    mean_cardinality: number
    multi_label_rate: number     // fraction of sentences with >=2 labels
  }[]
  dims: DimStat[]
}

const SELF_DISCLOSURE: CodebookStats = {
  n_fiona: 333,
  n_chang: 331,
  n_dual: 187,
  n_agreed_any: 169,
  dims: [
    { dim: 'Level of disclosure', raw_agreement: 0.686, n_joint: 185, n_agreed: 118 },
    { dim: 'Depth of disclosure', raw_agreement: 0.705, n_joint: 95, n_agreed: 62 },
    { dim: 'Disclosure as confession', raw_agreement: 0.599, n_joint: 182, n_agreed: 104 },
    { dim: 'Topic', raw_agreement: 0.246, n_joint: 187, n_agreed: 44 },
    { dim: 'Topic thematic category', raw_agreement: 0.540, n_joint: 187, n_agreed: 109 },
    { dim: 'Intimacy of self-disclosure', raw_agreement: null, n_joint: 2, n_agreed: 24 },
    { dim: 'Temporality', raw_agreement: 0.786, n_joint: 14, n_agreed: 12 },
  ],
}

const AI_BEHAVIOR: CodebookStats = {
  n_fiona: 343,
  n_chang: 340,
  n_dual: 123,
  n_agreed_any: null,   // agreed subset not yet computed — noted in UI
  multi_label: [
    { theme: 'Listening strategy', exact_match: 0.302, mean_jaccard: 0.367, mean_cardinality: 1.40, multi_label_rate: 0.357 },
    { theme: 'Support type', exact_match: 0.000, mean_jaccard: 0.000, mean_cardinality: 1.02, multi_label_rate: 0.019 },
    { theme: 'Interaction', exact_match: 0.000, mean_jaccard: 0.070, mean_cardinality: 1.39, multi_label_rate: 0.386 },
  ],
  dims: [
    { dim: 'Listening strategy', raw_agreement: 0.302, n_joint: 106, n_agreed: null },
    { dim: 'Support type', raw_agreement: 0.000, n_joint: 26, n_agreed: null },
    { dim: 'Interaction', raw_agreement: 0.000, n_joint: 64, n_agreed: null },
  ],
}

const LOOKUP: Record<string, CodebookStats> = {
  'Self-Disclosure Analysis': SELF_DISCLOSURE,
  'self_disclosure': SELF_DISCLOSURE,
  'Self-disclosure': SELF_DISCLOSURE,
  'AI Behavior (Multi-Label)': AI_BEHAVIOR,
  'ai_behavior': AI_BEHAVIOR,
  'AI behavior': AI_BEHAVIOR,
}

export function lookupStats(codebookName: string): CodebookStats | null {
  if (LOOKUP[codebookName]) return LOOKUP[codebookName]
  const lower = codebookName.toLowerCase()
  for (const key of Object.keys(LOOKUP)) {
    if (lower.includes(key.toLowerCase()) || key.toLowerCase().includes(lower)) {
      return LOOKUP[key]
    }
  }
  return null
}

export function findDimStat(stats: CodebookStats | null, dimName: string): DimStat | null {
  if (!stats) return null
  const lower = dimName.toLowerCase()
  for (const d of stats.dims) {
    if (d.dim.toLowerCase() === lower) return d
    if (d.dim.toLowerCase().includes(lower) || lower.includes(d.dim.toLowerCase())) return d
  }
  return null
}
