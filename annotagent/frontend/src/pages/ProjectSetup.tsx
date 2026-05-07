import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getProject, updateProject, listPresets, listCodebooks,
  uploadDataset, listDatasets, decomposePipeline,
  listSeedDatasets, loadSeedDataset, getBackendConfig,
  type SeedDatasetInfo, type BackendConfig,
} from '../lib/api'
import type { Project, Codebook, Dataset, PresetInfo } from '../types'
import CodebookDraftWizard from '../components/CodebookDraftWizard'

export default function ProjectSetup() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [presets, setPresets] = useState<PresetInfo[]>([])
  const [codebooks, setCodebooks] = useState<Codebook[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [seeds, setSeeds] = useState<SeedDatasetInfo[]>([])
  const [backendCfg, setBackendCfg] = useState<BackendConfig | null>(null)
  const [llmProvider, setLlmProvider] = useState('openai')
  const [llmModel, setLlmModel] = useState('gpt-5.4-mini')
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingSeed, setLoadingSeed] = useState<string | null>(null)
  const [wizardMode, setWizardMode] = useState(false)   // force-show wizard even when active codebook exists

  const loadData = useCallback(async () => {
    const [p, pr, cb, ds, sd, cfg] = await Promise.all([
      getProject(projectId),
      listPresets(projectId),
      listCodebooks(projectId),
      listDatasets(projectId),
      listSeedDatasets(projectId),
      getBackendConfig().catch(() => null),
    ])
    setProject(p); setPresets(pr); setCodebooks(cb); setDatasets(ds); setSeeds(sd); setBackendCfg(cfg)
    setLlmProvider(p.llm_provider); setLlmModel(p.llm_model)
  }, [projectId])

  useEffect(() => { loadData() }, [loadData])

  const handleDataUpload = async (e: React.ChangeEvent<HTMLInputElement>, isGold: boolean) => {
    const file = e.target.files?.[0]
    if (!file) return
    await uploadDataset(projectId, file, isGold)
    setDatasets(await listDatasets(projectId))
  }

  const handleLoadSeed = async (seedId: string) => {
    setLoadingSeed(seedId)
    try {
      await loadSeedDataset(projectId, seedId)
      setDatasets(await listDatasets(projectId))
    } finally {
      setLoadingSeed(null)
    }
  }

  const handleSaveLLM = async () => {
    const patch: Record<string, string> = { llm_provider: llmProvider, llm_model: llmModel }
    if (apiKey) patch.api_key = apiKey
    await updateProject(projectId, patch)
  }

  const handleGeneratePipeline = async () => {
    setLoading(true)
    try {
      await handleSaveLLM()
      await decomposePipeline(projectId)
      // Land on PromptLab — the LLM auto-generates an annotation prompt from the
      // codebook there, then the user iterates with the optimizer (if a gold
      // dataset is loaded). Pipeline page is reachable from the top nav once
      // the prompt is ready.
      navigate(`/projects/${projectId}/prompt-lab`)
    } finally {
      setLoading(false)
    }
  }

  if (!project) {
    return <div className="font-mono-editorial text-stone-400 py-24 text-center">Loading project…</div>
  }

  const activeCb = codebooks[codebooks.length - 1]
  const hasDataset = datasets.length > 0
  const keyOK = envKeyAvailable(backendCfg, llmProvider) || apiKey.length > 0
  // Dataset is optional — the LLM-driven auto-prompt step runs without one;
  // optimizers later require a gold dataset, but that gate is enforced on PromptLab.
  const canGenerate = !!activeCb && keyOK
  const missing: string[] = []
  if (!activeCb) missing.push('Codebook')
  if (!keyOK) missing.push(`${llmProvider === 'anthropic' ? 'Anthropic' : 'OpenAI'} API key`)

  return (
    <div className="space-y-14">
      {/* Masthead */}
      <header className="border-b border-seam pb-8">
        <div className="font-mono-editorial text-stone-500 mb-3">
          Project · {project.id.toString().padStart(3, '0')}
        </div>
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <h1 className="text-4xl sm:text-5xl font-medium tracking-tight leading-[1.05]">
            {project.name}
          </h1>
          <div className="font-mono-editorial text-stone-500">
            {project.description || 'No description'}
          </div>
        </div>
      </header>

      {/* Section 01 — Codebook */}
      <Section num="01" title="Codebook" hint="The label schema the LLM will follow. CodebookAgent parses any messy input into a structured schema.">
        {activeCb && !wizardMode ? (
          <div className="border border-seam bg-paper/50">
            <div className="flex items-start justify-between gap-4 p-5 border-b border-seam">
              <div>
                <div className="font-mono-editorial text-stone-500 mb-1">Active codebook</div>
                <h3 className="text-xl font-medium tracking-tight">{activeCb.name}</h3>
                <p className="text-sm text-stone-600 mt-1 max-w-2xl leading-relaxed">{activeCb.description}</p>
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                <Link
                  to={`/projects/${projectId}/codebook`}
                  className="px-4 py-2 text-sm font-medium text-ink border border-ink hover:bg-ink hover:text-cream transition-colors text-center"
                >
                  View codebook →
                </Link>
                <button
                  onClick={() => setWizardMode(true)}
                  className="px-4 py-2 text-sm font-medium text-stone-600 border border-seam hover:border-stone-400"
                >
                  Replace
                </button>
              </div>
            </div>
            <div className="divide-y divide-seam">
              {activeCb.dimensions.map((dim, i) => (
                <div key={dim.id} className="px-5 py-4 flex items-start gap-5">
                  <div className="font-mono-editorial text-stone-400 pt-0.5 w-8 shrink-0">
                    {(i + 1).toString().padStart(2, '0')}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-3 mb-1.5">
                      <span className="font-medium">{dim.name}</span>
                      <span className="font-mono-editorial text-stone-400">{dim.dim_type}</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {dim.labels.map(lbl => (
                        <span key={lbl.id} className="px-2 py-0.5 bg-white border border-seam text-stone-700 text-xs">
                          {lbl.name}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <>
            {activeCb && wizardMode && (
              <div className="mb-4 flex items-center justify-between text-sm border border-amber-200 bg-amber-50/60 px-4 py-3">
                <div>
                  <span className="font-mono-editorial text-amber-800 mr-2">Replacing</span>
                  <span className="text-stone-700">{activeCb.name}</span>
                </div>
                <button
                  onClick={() => setWizardMode(false)}
                  className="font-mono-editorial text-stone-500 hover:text-ink"
                >
                  cancel
                </button>
              </div>
            )}
            <CodebookDraftWizard
              projectId={projectId}
              presets={presets}
              onAccepted={() => {
                setWizardMode(false)
                loadData()   // refresh codebooks list
              }}
            />
          </>
        )}
      </Section>

      {/* Section 02 — Datasets */}
      <Section num="02" title="Datasets · optional" hint="Labeled examples drive the Improve step. You can skip and add them later.">
        {/* Seeds are repository-bundled gold sets specific to the self-disclosure
            codebook. Only surface them when the user picked that preset; for any
            other codebook they'd be misleading clutter. */}
        {seeds.length > 0 && isSelfDisclosure(activeCb) && (
          <>
            <SubLabel>
              Ground truth · for prompt tuning and calibration
            </SubLabel>
            <ul className="divide-y divide-seam border-y border-seam mb-8">
              {seeds.filter(s => s.role !== 'test').map(s => (
                <SeedRow
                  key={s.id}
                  s={s}
                  alreadyLoaded={datasets.some(d => d.name === s.label)}
                  loading={loadingSeed === s.id}
                  onLoad={() => handleLoadSeed(s.id)}
                />
              ))}
            </ul>
            <p className="text-xs text-stone-500 mb-8 -mt-4">
              Unseen test sets (v1 / v2) are loaded later, on the Pipeline page, once you're ready to annotate.
            </p>
          </>
        )}

        <SubLabel>Upload your own</SubLabel>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
          <Field label="Data (CSV/JSON)">
            <input type="file" accept=".csv,.json" onChange={e => handleDataUpload(e, false)} className="text-sm pt-2" />
          </Field>
          <Field label="Gold standard (CSV/JSON)">
            <input type="file" accept=".csv,.json" onChange={e => handleDataUpload(e, true)} className="text-sm pt-2" />
          </Field>
        </div>

        {datasets.length > 0 && (
          <>
            <SubLabel>Loaded in this project · {datasets.length}</SubLabel>
            <ul className="divide-y divide-seam border-y border-seam">
              {datasets.map(ds => (
                <li key={ds.id} className="py-3 grid grid-cols-12 gap-3 items-baseline">
                  <span className="col-span-7 font-medium truncate">{ds.name}</span>
                  <span className="col-span-2 font-mono text-sm">{ds.total_items.toLocaleString()} items</span>
                  <span className="col-span-2 font-mono-editorial text-stone-400">{ds.file_type}</span>
                  <span className="col-span-1 text-right">
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Section>

      {/* Section 03 — LLM */}
      <Section num="03" title="LLM configuration" hint="Backend loads keys from .env automatically — override per-project below.">
        {backendCfg && (
          <div className="flex items-center gap-2 mb-6">
            <EnvKeyBadge label="OpenAI" loaded={backendCfg.openai_key_loaded} />
            <EnvKeyBadge label="Anthropic" loaded={backendCfg.anthropic_key_loaded} />
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          <div className="md:col-span-3">
            <Field label="Provider">
              <select
                value={llmProvider}
                onChange={e => setLlmProvider(e.target.value)}
                className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium"
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </Field>
          </div>
          <div className="md:col-span-4">
            <Field label="Model">
              <input
                value={llmModel}
                onChange={e => setLlmModel(e.target.value)}
                className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm"
              />
            </Field>
          </div>
          <div className="md:col-span-5">
            <Field label={
              <>
                API Key
                {envKeyAvailable(backendCfg, llmProvider) && (
                  <span className="ml-2 text-emerald-700 font-normal normal-case tracking-normal text-[11px]">
                    · optional, env loaded
                  </span>
                )}
              </>
            }>
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm"
                placeholder={envKeyAvailable(backendCfg, llmProvider) ? 'using .env — leave blank' : 'sk-…'}
              />
            </Field>
            {envKeyAvailable(backendCfg, llmProvider) && !apiKey && (
              <p className="text-xs text-stone-500 mt-2">
                Backend has a <code className="font-mono text-[11px]">{llmProvider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY'}</code>. Leave blank or override here.
              </p>
            )}
          </div>
        </div>
      </Section>

      {/* Run row */}
      <section className="border-t border-seam pt-8">
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <div className="flex-1 min-w-[320px]">
            <div className="font-mono-editorial text-stone-500 mb-3">Ready check</div>
            <ul className="space-y-1.5">
              <Check ok={!!activeCb} label="Codebook loaded" />
              <Check ok={keyOK} label={`${llmProvider === 'anthropic' ? 'Anthropic' : 'OpenAI'} key available`} />
              <Check ok={hasDataset} label="Dataset loaded" optional optionalNote="for optimization" />
            </ul>
            {missing.length > 0 && (
              <p className="mt-3 text-sm text-stone-500">
                Still need: <span className="text-ink font-medium">{missing.join(' · ')}</span>
              </p>
            )}
          </div>

          <button
            onClick={handleGeneratePipeline}
            disabled={!canGenerate || loading}
            className="group inline-flex items-center gap-3 px-6 py-3.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <span>{loading ? 'Generating pipeline…' : 'Generate pipeline'}</span>
            <span className="transition-transform group-enabled:group-hover:translate-x-1">→</span>
          </button>
        </div>
      </section>
    </div>
  )
}

/* ---------- Editorial layout primitives ---------- */

function Section({
  num, title, hint, children,
}: { num: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-12 gap-8">
      <header className="lg:col-span-3 lg:border-r lg:border-seam lg:pr-6">
        <div className="font-mono-editorial text-stone-400 mb-2">№ {num}</div>
        <h2 className="text-2xl font-medium tracking-tight">{title}</h2>
        {hint && <p className="text-sm text-stone-500 mt-3 leading-relaxed">{hint}</p>}
      </header>
      <div className="lg:col-span-9">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="font-mono-editorial text-stone-500 block mb-1">{label}</span>
      {children}
    </label>
  )
}

function SubLabel({ children }: { children: React.ReactNode }) {
  return <div className="font-mono-editorial text-stone-500 mb-3">{children}</div>
}

function SeedRow({
  s, alreadyLoaded, loading, onLoad,
}: {
  s: SeedDatasetInfo
  alreadyLoaded: boolean
  loading: boolean
  onLoad: () => void
}) {
  const tagTone =
    s.role === 'gold' ? 'text-amber-700' :
    s.role === 'test' ? 'text-blue-700' :
    'text-stone-400'

  return (
    <li className={`grid grid-cols-12 gap-4 py-4 items-center ${s.available ? '' : 'opacity-50'}`}>
      <div className="col-span-7">
        <div className="flex items-baseline gap-3">
          <span className="font-medium">{s.label}</span>
          {s.role === 'test' && <span className="font-mono-editorial text-blue-700">Unseen</span>}
        </div>
        <p className="text-sm text-stone-600 mt-0.5">{s.description}</p>
        <p className="font-mono text-[11px] text-stone-400 mt-1 truncate">{s.path}</p>
      </div>
      <div className={`col-span-3 font-mono-editorial ${tagTone}`}>
        {s.role}
      </div>
      <div className="col-span-2 text-right">
        {!s.available ? (
          <span className="font-mono-editorial text-stone-400">file missing</span>
        ) : alreadyLoaded ? (
          <span className="font-mono-editorial text-emerald-700">loaded ✓</span>
        ) : (
          <button
            onClick={onLoad}
            disabled={loading}
            className="px-3 py-1.5 text-xs font-medium text-ink border border-ink hover:bg-ink hover:text-cream disabled:opacity-50 transition-colors"
          >
            {loading ? 'Loading…' : 'Load'}
          </button>
        )}
      </div>
    </li>
  )
}

function InlineEmpty({ hint }: { hint: string }) {
  return (
    <div className="border border-dashed border-seam bg-paper/40 py-10 text-center">
      <div className="font-mono-editorial text-stone-500 mb-1">No codebook yet</div>
      <p className="text-stone-600 text-sm">{hint}</p>
    </div>
  )
}

function Check({
  ok, label, optional, optionalNote,
}: { ok: boolean; label: string; optional?: boolean; optionalNote?: string }) {
  return (
    <li className="flex items-center gap-3 text-sm">
      <span
        className={`inline-flex items-center justify-center w-4 h-4 rounded-full border font-mono text-[10px] ${
          ok ? 'bg-ink text-cream border-ink' : optional ? 'border-stone-300 text-stone-300 bg-white' : 'border-seam text-stone-400 bg-white'
        }`}
      >
        {ok ? '✓' : optional ? '·' : ''}
      </span>
      <span className={ok ? 'text-ink' : 'text-stone-500'}>{label}</span>
      {optional && !ok && (
        <span className="font-mono-editorial text-stone-400 text-xs">
          optional{optionalNote ? ` · ${optionalNote}` : ''}
        </span>
      )}
    </li>
  )
}

function envKeyAvailable(cfg: BackendConfig | null, provider: string): boolean {
  if (!cfg) return false
  return provider === 'anthropic' ? cfg.anthropic_key_loaded : cfg.openai_key_loaded
}

function isSelfDisclosure(cb: Codebook | undefined | null): boolean {
  if (!cb) return false
  const n = (cb.name || '').toLowerCase()
  return n.includes('self-disclosure') || n.includes('self_disclosure') || n.includes('self disclosure')
}

function EnvKeyBadge({ label, loaded }: { label: string; loaded: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 border text-[11px] font-mono tracking-wider uppercase ${
        loaded
          ? 'border-emerald-300 bg-emerald-50/60 text-emerald-800'
          : 'border-seam bg-paper text-stone-400'
      }`}
      title={loaded ? `${label} key loaded from backend .env` : `${label} key not configured`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${loaded ? 'bg-emerald-500' : 'bg-stone-300'}`} />
      {label} · {loaded ? '.env' : 'off'}
    </span>
  )
}
