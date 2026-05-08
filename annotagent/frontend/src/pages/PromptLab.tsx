import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import api, {
  listAvailableOptimizers, listOptimizerRuns, startOptimizerRun, getOptimizerRun,
  listCodebooks, listDatasets, autoGeneratePrompt, patchOptimizerRun,
  listMemoryVersions, deleteOptimizerRun, cancelOptimizerRun,
  type OptimizerInfo, type OptimizerRun, type AutoPromptResponse, type MemoryVersion,
} from '../lib/api'
import type { Codebook, Dataset } from '../types'

function fmtError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return String(d.message)
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg)
  return e?.message || 'Unknown error'
}

// Toggling Researcher mode flips ALL technical surface (optimizer dropdown,
// split sliders, budget knob, algorithmic labels) at once. Default is off so a
// non-CS user sees one button. Persisted across reloads so reviewers don't
// have to re-toggle every visit.
const RESEARCHER_KEY = 'annotagent.researcher_mode'

export default function PromptLab() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)

  const [researcherMode, setResearcherMode] = useState<boolean>(() => {
    try { return localStorage.getItem(RESEARCHER_KEY) === '1' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem(RESEARCHER_KEY, researcherMode ? '1' : '0') } catch {}
  }, [researcherMode])

  const [optimizers, setOptimizers] = useState<OptimizerInfo[]>([])
  const [codebooks, setCodebooks] = useState<Codebook[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<OptimizerRun[]>([])

  // form
  const [selectedOpt, setSelectedOpt] = useState<string>('reflect_agent')
  const [selectedDim, setSelectedDim] = useState<string>('')
  const [selectedGold, setSelectedGold] = useState<number | null>(null)
  const [budget, setBudget] = useState<number>(5)
  // 3-way split as integer percentages (easier for humans). Defaults per design:
  // small train, large val, large held-out test. Sum must equal 100.
  const [trainPct, setTrainPct] = useState<number>(15)
  const [valPct, setValPct]     = useState<number>(42)
  const [testPct, setTestPct]   = useState<number>(43)
  const [launching, setLaunching] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [selectedRun, setSelectedRun] = useState<OptimizerRun | null>(null)
  const [launchError, setLaunchError] = useState<string>('')
  const [goldLabelKeys, setGoldLabelKeys] = useState<Set<string>>(new Set())
  const [goldLabelCounts, setGoldLabelCounts] = useState<Record<string, number>>({})

  // Auto-generated annotation prompt (PR #1's LLM-driven path). Cached per
  // (project, codebook) so it doesn't refire on every visit and burn tokens.
  const [autoPrompt, setAutoPrompt] = useState<AutoPromptResponse | null>(null)
  const [autoPromptLoading, setAutoPromptLoading] = useState(false)
  const [autoPromptError, setAutoPromptError] = useState<string>('')

  // Cross-session reflection memory (cumulative rule library, versioned per
  // (project, dimension)). Re-fetched whenever runs list updates so a freshly
  // completed reflect_agent run pulls in its new memory version.
  const [memory, setMemory] = useState<MemoryVersion[]>([])
  useEffect(() => {
    listMemoryVersions(projectId).then(setMemory).catch(() => setMemory([]))
  }, [projectId, runs.length, runs.map(r => r.status).join(',')])

  useEffect(() => {
    Promise.all([
      listAvailableOptimizers(projectId),
      listCodebooks(projectId),
      listDatasets(projectId),
      listOptimizerRuns(projectId),
    ]).then(([opts, cbs, dss, rs]) => {
      setOptimizers(opts)
      setCodebooks(cbs)
      setDatasets(dss)
      setRuns(rs)
      if (cbs.length > 0 && cbs[cbs.length - 1].dimensions[0]) {
        setSelectedDim(cbs[cbs.length - 1].dimensions[0].name)
      }
      // Default-select an is_gold dataset if any (most reliable for the loop);
      // fall back to whatever's loaded so user lands on something usable.
      const def = dss.find(d => d.is_gold) ?? dss[0]
      if (def) setSelectedGold(def.id)
    })
  }, [projectId])

  // Poll in-flight runs for status
  useEffect(() => {
    const hasInFlight = runs.some(r => r.status === 'running' || r.status === 'pending')
    if (!hasInFlight) return
    const iv = setInterval(() => {
      listOptimizerRuns(projectId).then(setRuns)
    }, 3000)
    return () => clearInterval(iv)
  }, [runs, projectId])

  useEffect(() => {
    if (selectedRunId) {
      getOptimizerRun(projectId, selectedRunId).then(setSelectedRun)
    } else {
      setSelectedRun(null)
    }
  }, [selectedRunId, projectId])

  // Live-poll the selected run while it's still in flight so the user watches
  // the trajectory grow round by round instead of staring at a spinner.
  useEffect(() => {
    if (!selectedRunId) return
    const status = selectedRun?.status
    if (status !== 'running' && status !== 'pending') return
    const iv = setInterval(() => {
      getOptimizerRun(projectId, selectedRunId).then(r => {
        setSelectedRun(r)
        // Keep the list row in sync too so status badge flips when done
        setRuns(prev => prev.map(x => x.id === r.id ? r : x))
      }).catch(() => { /* swallow transient errors */ })
    }, 2000)
    return () => clearInterval(iv)
  }, [selectedRunId, selectedRun?.status, projectId])

  // Peek at the gold dataset to learn which dimensions actually have labels —
  // so we can warn the user BEFORE launching with a dim that has zero gold coverage.
  useEffect(() => {
    if (!selectedGold) { setGoldLabelKeys(new Set()); setGoldLabelCounts({}); return }
    (async () => {
      try {
        const resp = await api.get(`/projects/${projectId}/datasets/${selectedGold}`, {
          params: { limit: 500, offset: 0 },
        })
        const items: any[] = resp.data?.items || []
        const keys = new Set<string>()
        const counts: Record<string, number> = {}
        for (const it of items) {
          const g = it.gold_labels || {}
          for (const k of Object.keys(g)) {
            if (g[k] != null && g[k] !== '') {
              keys.add(k)
              counts[k] = (counts[k] || 0) + 1
            }
          }
        }
        setGoldLabelKeys(keys)
        setGoldLabelCounts(counts)
      } catch {
        setGoldLabelKeys(new Set())
        setGoldLabelCounts({})
      }
    })()
  }, [selectedGold, projectId])

  // Replicate backend split logic so the UI preview matches what
  // _execute_run will actually do (api/optimizers.py:268–298).
  const computeSplit = (n: number, trainPctV: number, valPctV: number, testPctV: number) => {
    if (n <= 0) return { n_train: 0, n_val: 0, n_test: 0 }
    let n_train = Math.max(5, Math.round((trainPctV / 100) * n))
    let n_val   = Math.max(5, Math.round((valPctV   / 100) * n))
    let n_test  = Math.max(0, n - n_train - n_val)
    if (n_test < 3 && n_train > 5) {
      const steal = Math.min(3 - n_test, n_train - 5)
      n_train -= steal
      n_test  += steal
    }
    return { n_train, n_val, n_test }
  }

  const activeCb = codebooks[codebooks.length - 1]
  // All datasets are eligible as "labeled examples" — Fiona / Chang seeds
  // carry an annotator's labels even though only the intersection is flagged
  // is_gold. The pre-flight + per-dim availability counter rejects rows that
  // don't have labels for the picked dimension.
  const goldDatasets = datasets

  // Auto-prompt cache key. Stored in localStorage so the LLM call only fires
  // once per (project, codebook); the user explicitly re-runs via the button.
  const autoPromptCacheKey = activeCb ? `annotagent.autoPrompt.${projectId}.${activeCb.id}` : null

  useEffect(() => {
    if (!activeCb || !autoPromptCacheKey) return
    if (autoPrompt) return
    try {
      const cached = localStorage.getItem(autoPromptCacheKey)
      if (cached) {
        const parsed = JSON.parse(cached)
        // Validate shape — old single-prompt cache should be discarded so the
        // user gets the new per-dimension result on the next visit.
        if (parsed && Array.isArray(parsed.prompts)) {
          setAutoPrompt(parsed); return
        }
        localStorage.removeItem(autoPromptCacheKey)
      }
    } catch { /* ignore */ }
    // Fire once per (project, codebook). User can force a re-run via the button.
    setAutoPromptLoading(true)
    setAutoPromptError('')
    autoGeneratePrompt(projectId, activeCb.id)
      .then(resp => {
        setAutoPrompt(resp)
        try { localStorage.setItem(autoPromptCacheKey, JSON.stringify(resp)) } catch { /* ignore */ }
      })
      .catch(e => setAutoPromptError(fmtError(e)))
      .finally(() => setAutoPromptLoading(false))
  }, [activeCb, autoPromptCacheKey, autoPrompt, projectId])

  const handleRegeneratePrompt = async () => {
    if (!activeCb || !autoPromptCacheKey) return
    setAutoPromptLoading(true)
    setAutoPromptError('')
    try {
      const resp = await autoGeneratePrompt(projectId, activeCb.id)
      setAutoPrompt(resp)
      try { localStorage.setItem(autoPromptCacheKey, JSON.stringify(resp)) } catch { /* ignore */ }
    } catch (e: any) {
      setAutoPromptError(fmtError(e))
    } finally {
      setAutoPromptLoading(false)
    }
  }

  // Pre-flight validation — tell the user WHY before they launch
  const splitTotal = trainPct + valPct + testPct
  const preflightIssues: string[] = []
  if (!activeCb) preflightIssues.push('No codebook loaded. Go to Setup.')
  if (goldDatasets.length === 0) preflightIssues.push('No labeled dataset loaded. Load one on Setup.')
  if (!selectedDim) preflightIssues.push('Pick a dimension.')
  if (!selectedGold) preflightIssues.push('Pick a gold dataset.')
  if (selectedDim && goldLabelKeys.size > 0 && !goldLabelKeys.has(selectedDim)) {
    preflightIssues.push(
      `The selected gold dataset has no labels for "${selectedDim}". ` +
      `Available dimensions in this gold set: ${[...goldLabelKeys].join(', ') || '(none)'}.`
    )
  }
  if (researcherMode) {
    if (splitTotal !== 100) {
      preflightIssues.push(`Train + Val + Test must sum to 100 (current: ${splitTotal}).`)
    }
    if (trainPct < 5)  preflightIssues.push('Train < 5% is unstable. Bump it up.')
    if (testPct < 10)  preflightIssues.push('Test < 10% gives a noisy held-out score. Bump it up.')
  }

  const canLaunch = preflightIssues.length === 0 && !launching

  const handleLaunch = async () => {
    if (!selectedGold) return
    setLaunching(true)
    setLaunchError('')
    // In default mode the user never sees optimizer/split/budget knobs, so
    // launch with safe defaults regardless of any state a previous Researcher-
    // mode session might have left behind.
    const launchOpt    = researcherMode ? selectedOpt : 'reflect_agent'
    const launchBudget = researcherMode ? budget      : 5
    const launchTrain  = researcherMode ? trainPct    : 15
    const launchVal    = researcherMode ? valPct      : 42
    const launchTest   = researcherMode ? testPct     : 43
    try {
      const run = await startOptimizerRun(projectId, {
        optimizer_name: launchOpt,
        dimension_name: selectedDim,
        gold_dataset_id: selectedGold,
        budget: launchBudget,
        train_frac: launchTrain / 100,
        val_frac:   launchVal   / 100,
        test_frac:  launchTest  / 100,
      })
      setRuns([run, ...runs])
      setSelectedRunId(run.id)
    } catch (e: any) {
      setLaunchError(fmtError(e))
    } finally {
      setLaunching(false)
    }
  }

  const method = optimizers.find(o => o.role === 'method')
  const baselines = optimizers.filter(o => o.role === 'baseline')

  return (
    <div className="space-y-12">
      {/* Masthead */}
      <header className="border-b border-seam pb-6">
        <div className="flex items-start justify-between gap-6">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">
              {researcherMode ? 'Prompt optimization workbench' : 'Improve from examples'}
            </div>
            {researcherMode ? (
              <>
                <h1 className="text-4xl sm:text-5xl font-medium tracking-tight leading-[1.05]">
                  Distil a prompt.<br />
                  Compare optimizers head-to-head.
                </h1>
                <p className="mt-5 max-w-2xl text-stone-600 leading-relaxed">
                  Pick any optimizer, target one codebook dimension, and the gold subset you've loaded. Runs execute in the background. ReflectAgent is our method; the other three are post-2023 SOTA baselines.
                </p>
              </>
            ) : (
              <>
                <h1 className="text-4xl sm:text-5xl font-medium tracking-tight leading-[1.05]">
                  Find and fix annotation<br />
                  mistakes from your examples.
                </h1>
                <p className="mt-5 max-w-2xl text-stone-600 leading-relaxed">
                  Pick the dimension you want to improve and the labeled examples to learn from.
                  We review the cases the system gets wrong, write plain-English guidance,
                  double-check on examples it hasn't seen, and quietly roll back any guidance
                  that hurts accuracy.
                </p>
              </>
            )}
          </div>
          <ResearcherToggle on={researcherMode} onChange={setResearcherMode} />
        </div>
      </header>

      {/* Section 00 — Current prompt per dimension (optimized if one exists,
          otherwise the LLM-drafted starting prompt).
          Each dimension gets its own LLM-written prompt so the optimizer can
          tune them independently. Generation is parallel across dimensions. */}
      <Section
        num="00"
        title="Current prompts"
        hint="The active annotation prompt per dimension. Defaults to the optimized version when one exists; toggle to see the original LLM-drafted starting prompt for comparison."
      >
        {!activeCb ? (
          <div className="font-mono-editorial text-stone-400">
            Load a codebook on the Setup page first.
          </div>
        ) : autoPromptLoading && !autoPrompt ? (
          <div className="border border-seam bg-paper/40 px-5 py-8 text-center">
            <div className="font-mono-editorial text-stone-500 mb-1">Generating…</div>
            <p className="text-sm text-stone-600">
              Drafting a prompt for each of the {activeCb.dimensions.length} dimensions in parallel.
            </p>
          </div>
        ) : autoPromptError ? (
          <div className="border border-red-200 bg-red-50/60 px-5 py-4 text-sm">
            <div className="font-mono-editorial text-red-700 mb-1">Generation failed</div>
            <p className="text-stone-700">{autoPromptError}</p>
            <button
              onClick={handleRegeneratePrompt}
              className="mt-3 px-3 py-1.5 text-xs font-medium text-ink border border-ink hover:bg-ink hover:text-cream"
            >
              Try again
            </button>
          </div>
        ) : autoPrompt && autoPrompt.prompts.length > 0 ? (
          <div>
            <div className="flex items-baseline justify-between gap-4 mb-3">
              <div className="font-mono-editorial text-stone-500">
                {autoPrompt.prompts.length} prompts · generated from {activeCb.name}
              </div>
              <button
                onClick={handleRegeneratePrompt}
                disabled={autoPromptLoading}
                className="font-mono-editorial text-stone-500 hover:text-ink disabled:opacity-50"
              >
                {autoPromptLoading ? 're-generating…' : 're-generate all'}
              </button>
            </div>
            <div className="space-y-3">
              {autoPrompt.prompts.map(p => {
                // Latest completed reflect_agent run for this dim, if any.
                const completed = runs
                  .filter(r => r.dimension_name === p.dimension_name
                    && r.optimizer_name === 'reflect_agent'
                    && r.status === 'completed')
                  .sort((a, b) => b.id - a.id)[0]
                return (
                  <DimensionPromptCard
                    key={p.dimension_name}
                    dp={p}
                    optimizedRun={completed}
                    onJumpToRun={completed ? () => {
                      setSelectedRunId(completed.id)
                      // Scroll into view after the detail mounts.
                      setTimeout(() => {
                        const el = document.getElementById('section-runs')
                        el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                      }, 50)
                    } : undefined}
                  />
                )
              })}
            </div>
          </div>
        ) : (
          <button
            onClick={handleRegeneratePrompt}
            className="px-4 py-2 text-sm font-medium text-ink border border-ink hover:bg-ink hover:text-cream"
          >
            Generate prompts
          </button>
        )}
      </Section>

      {/* Section 01 — Pick an optimizer (Researcher mode only) */}
      {researcherMode && (
        <Section num="01" title="Optimizer" hint="ReflectAgent is our method. The three baselines are the current SOTA we compare against.">
          {optimizers.length === 0 ? (
            <div className="font-mono-editorial text-stone-400">Loading…</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {method && (
                <OptimizerCard
                  opt={method}
                  selected={selectedOpt === method.name}
                  onSelect={() => setSelectedOpt(method.name)}
                  emphasized
                />
              )}
              {baselines.map(opt => (
                <OptimizerCard
                  key={opt.name}
                  opt={opt}
                  selected={selectedOpt === opt.name}
                  onSelect={() => setSelectedOpt(opt.name)}
                />
              ))}
            </div>
          )}
        </Section>
      )}

      {/* Section 02 — Target */}
      <Section
        num={researcherMode ? '02' : '01'}
        title={researcherMode ? 'Target' : 'What to improve'}
        hint={
          researcherMode
            ? 'Which codebook dimension to optimize, and which gold subset to score against.'
            : 'Pick the dimension you want to improve and the labeled examples to learn from.'
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          <div className={researcherMode ? 'md:col-span-5' : 'md:col-span-6'}>
            <Field label="Dimension">
              {activeCb ? (
                <select
                  value={selectedDim}
                  onChange={e => setSelectedDim(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium"
                >
                  {activeCb.dimensions.map(d => (
                    <option key={d.id} value={d.name}>
                      {researcherMode
                        ? `${d.name} (${d.labels.length} labels · ${d.dim_type})`
                        : `${d.name} (${d.labels.length} labels)`}
                    </option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-stone-500">No codebook loaded. Go to Setup.</p>
              )}
            </Field>
          </div>
          <div className={researcherMode ? 'md:col-span-5' : 'md:col-span-6'}>
            <Field label={researcherMode ? 'Gold dataset' : 'Labeled examples'}>
              {goldDatasets.length > 0 ? (
                <select
                  value={selectedGold ?? ''}
                  onChange={e => setSelectedGold(Number(e.target.value))}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium"
                >
                  {goldDatasets.map(d => (
                    <option key={d.id} value={d.id}>{d.name} ({d.total_items} items)</option>
                  ))}
                </select>
              ) : (
                <p className="text-sm text-stone-500">No labeled examples loaded. Go to Setup.</p>
              )}
            </Field>
          </div>
          {researcherMode && (
            <div className="md:col-span-2">
              <Field label="Budget · rounds">
                <input
                  type="number" min={1} max={20}
                  value={budget}
                  onChange={e => setBudget(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm"
                />
              </Field>
            </div>
          )}
        </div>

        {/* Per-dimension sample availability + split preview.
            Counts come from the gold dataset peek; split percentages match
            what the backend will actually use (researcher mode = current
            sliders, default mode = 15/42/43). */}
        {selectedGold && selectedDim && (() => {
          const n = goldLabelCounts[selectedDim] ?? 0
          const tp = researcherMode ? trainPct : 15
          const vp = researcherMode ? valPct   : 42
          const xp = researcherMode ? testPct  : 43
          const split = computeSplit(n, tp, vp, xp)
          return (
            <div className="mt-6 border border-seam bg-paper/40 p-4 max-w-3xl">
              <div className="flex items-baseline justify-between gap-4 mb-3">
                <div className="font-mono-editorial text-stone-500">
                  Sample availability for "{selectedDim}"
                </div>
                <div className="font-mono text-sm text-ink">{n.toLocaleString()} labeled</div>
              </div>
              {n < 15 ? (
                <div className="font-mono-editorial text-amber-700">
                  Need at least 15 labeled items for this dimension; gold has {n}. Optimizer will refuse to start.
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <SplitTile
                      label="train" count={split.n_train} pct={tp}
                      hint="failures → rules (the optimizer reads these)"
                    />
                    <SplitTile
                      label="val" count={split.n_val} pct={vp}
                      hint="governor signal · accept/rollback each round"
                    />
                    <SplitTile
                      label="test" count={split.n_test} pct={xp}
                      hint="held out · scored once at the end · never seen by optimizer"
                      accent
                    />
                  </div>
                  <p className="mt-3 font-mono-editorial text-stone-500 leading-relaxed">
                    Train + val are used during optimization. Test is held out — it gives the honest "Before / After" number on the run results.
                  </p>
                </>
              )}
            </div>
          )
        })()}

        {/* 3-way split — Researcher mode only */}
        {researcherMode && (
        <div className="mt-8 border border-seam bg-paper/40 p-5">
          <div className="flex items-baseline justify-between mb-4">
            <div>
              <div className="font-mono-editorial text-stone-500 mb-1">Gold subset split</div>
              <div className="text-sm text-stone-700">
                Optimizer sees <span className="font-medium">train + val</span> only.
                The <span className="font-medium">test set is held out</span> — we score the final prompt on it after optimization ends, which is the honest number reported.
              </div>
            </div>
            <div className={`font-mono text-sm ${splitTotal === 100 ? 'text-emerald-700' : 'text-red-700'}`}>
              {trainPct} / {valPct} / {testPct} = {splitTotal}%
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <SplitField label="Train" hint="failure cases → rules" value={trainPct} onChange={setTrainPct} range="10–20%" />
            <SplitField label="Val" hint="governor signal" value={valPct} onChange={setValPct} range="40–45%" />
            <SplitField label="Test" hint="held out · honest score" value={testPct} onChange={setTestPct} range="40–45%" accent />
          </div>
          <div className="mt-3 flex items-center justify-between gap-4 text-xs">
            <span className="font-mono-editorial text-stone-500">Leakage guard · dev and test items never enter the prompt</span>
            <button
              onClick={() => { setTrainPct(15); setValPct(42); setTestPct(43) }}
              className="font-mono-editorial text-stone-500 hover:text-ink"
            >
              reset defaults
            </button>
          </div>
        </div>
        )}

        {/* Pre-flight + error banner */}
        {(preflightIssues.length > 0 || launchError) && (
          <div className="mt-8 space-y-3">
            {launchError && (
              <div className="border border-red-200 bg-red-50/60 text-red-800 p-4 text-sm">
                <div className="font-mono-editorial text-red-700 mb-1">Launch failed</div>
                <div className="whitespace-pre-wrap">{launchError}</div>
              </div>
            )}
            {preflightIssues.length > 0 && (
              <div className="border border-amber-200 bg-amber-50/50 text-amber-900 p-4 text-sm">
                <div className="font-mono-editorial text-amber-800 mb-2">Ready check</div>
                <ul className="space-y-1">
                  {preflightIssues.map((msg, i) => (
                    <li key={i} className="leading-relaxed">· {msg}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="mt-8 flex items-end justify-between gap-6 flex-wrap">
          <p className="text-xs text-stone-500 max-w-md leading-relaxed">
            {researcherMode
              ? `Optimizer runs in background on train + val; held-out test is scored after. Expect a few minutes with ${budget} rounds.`
              : 'Runs in the background. Expect a few minutes — you can leave this page and come back.'}
          </p>
          <button
            onClick={handleLaunch}
            disabled={!canLaunch}
            title={!canLaunch && preflightIssues.length > 0 ? preflightIssues.join(' · ') : ''}
            className="group inline-flex items-center gap-3 px-6 py-3 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <span>
              {launching
                ? (researcherMode ? 'Launching…' : 'Starting…')
                : (researcherMode ? 'Launch optimizer run' : 'Improve from examples')}
            </span>
            <span className="transition-transform group-enabled:group-hover:translate-x-1">→</span>
          </button>
        </div>
      </Section>

      {/* Section 03 — Runs */}
      <div id="section-runs" className="scroll-mt-20" />
      <Section
        num={researcherMode ? '03' : '02'}
        title={researcherMode ? 'Runs' : 'Recent improvements'}
        hint={
          researcherMode
            ? 'Select a run to inspect its trajectory, final prompt, and rule library (ReflectAgent only).'
            : 'Click any improvement to see what changed and how the accuracy moved.'
        }
      >
        {runs.length === 0 ? (
          <div className="border border-dashed border-seam bg-paper/40 py-10 text-center">
            <div className="font-mono-editorial text-stone-500 mb-1">
              {researcherMode ? 'No runs yet' : 'Nothing here yet'}
            </div>
            <p className="text-sm text-stone-600">
              {researcherMode ? 'Launch the first one above.' : 'Try the button above.'}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-seam border-y border-seam">
            {runs.map(r => (
              <RunRow
                key={r.id}
                run={r}
                isSelected={r.id === selectedRunId}
                onSelect={() => setSelectedRunId(r.id === selectedRunId ? null : r.id)}
                onDelete={async () => {
                  try {
                    await deleteOptimizerRun(projectId, r.id)
                    setRuns(prev => prev.filter(x => x.id !== r.id))
                    if (selectedRunId === r.id) setSelectedRunId(null)
                  } catch (e: any) {
                    alert(`Delete failed: ${fmtError(e)}`)
                  }
                }}
                onCancel={async () => {
                  try {
                    await cancelOptimizerRun(projectId, r.id)
                    // Status flips to 'cancelled' once the worker observes the
                    // cancellation; the polling loop will pick that up.
                  } catch (e: any) {
                    alert(`Cancel failed: ${fmtError(e)}`)
                  }
                }}
                researcherMode={researcherMode}
              />
            ))}
          </ul>
        )}

        {selectedRun && (
          <div className="mt-10">
            <RunDetail
              run={selectedRun}
              researcherMode={researcherMode}
              onUpdate={(updated) => {
                setSelectedRun(updated)
                setRuns(prev => prev.map(x => x.id === updated.id ? updated : x))
              }}
              projectId={projectId}
            />
          </div>
        )}
      </Section>

      {/* Section 04 — Memory (cross-session reflect_agent rule library).
          Only meaningful for ReflectAgent runs; other optimizers don't
          produce a rule library. The next run on the same dimension seeds
          from the latest version listed here. */}
      <Section
        num={researcherMode ? '04' : '03'}
        title="Memory"
        hint="Rules learned across reflect_agent runs accumulate here, versioned per dimension. The next run on a dimension seeds from its latest version, so this is what carries between sessions."
      >
        <MemoryPanel memory={memory} onRefresh={() =>
          listMemoryVersions(projectId).then(setMemory).catch(() => {})
        } />
      </Section>
    </div>
  )
}

/* ─── Memory panel ──────────────────────────────────────────── */

function MemoryPanel({
  memory, onRefresh,
}: { memory: MemoryVersion[]; onRefresh: () => void }) {
  if (memory.length === 0) {
    return (
      <div className="border border-dashed border-seam bg-paper/40 py-10 text-center">
        <div className="font-mono-editorial text-stone-500 mb-1">No memory yet</div>
        <p className="text-sm text-stone-600 max-w-md mx-auto">
          Memory is written when a reflect_agent run completes. Run one above and the rule library will appear here, ready to seed the next run on the same dimension.
        </p>
      </div>
    )
  }

  // Group by dimension. Versions arrive ordered (dim, version DESC) from the API.
  const byDim: Record<string, MemoryVersion[]> = {}
  for (const v of memory) {
    if (!byDim[v.dimension_name]) byDim[v.dimension_name] = []
    byDim[v.dimension_name].push(v)
  }
  const dims = Object.keys(byDim).sort()

  return (
    <div>
      <div className="flex items-center justify-between mb-3 font-mono-editorial text-stone-500">
        <span>{memory.length} version{memory.length === 1 ? '' : 's'} across {dims.length} dimension{dims.length === 1 ? '' : 's'}</span>
        <button onClick={onRefresh} className="hover:text-ink">refresh</button>
      </div>
      <div className="space-y-6">
        {dims.map(d => (
          <DimensionMemory key={d} dimension={d} versions={byDim[d]} />
        ))}
      </div>
    </div>
  )
}

function DimensionMemory({
  dimension, versions,
}: { dimension: string; versions: MemoryVersion[] }) {
  const latest = versions[0]
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 pb-2 border-b border-seam mb-2">
        <h3 className="text-lg font-medium tracking-tight">{dimension}</h3>
        <div className="font-mono-editorial text-stone-500">
          latest · v{String(latest.version).padStart(3, '0')} · {latest.n_rules} rules
        </div>
      </div>
      <ul className="divide-y divide-seam">
        {versions.map(v => <MemoryVersionRow key={v.id} v={v} />)}
      </ul>
    </div>
  )
}

function MemoryVersionRow({ v }: { v: MemoryVersion }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full grid grid-cols-12 gap-3 py-2.5 px-1 text-left hover:bg-paper/60"
      >
        <span className="col-span-1 font-mono-editorial text-stone-400">{open ? '−' : '+'}</span>
        <span className="col-span-2 font-mono text-sm">v{String(v.version).padStart(3, '0')}</span>
        <span className="col-span-2 font-mono text-sm text-stone-700">{v.n_rules} rules</span>
        <span className="col-span-2 font-mono-editorial text-stone-500">
          {v.new_rules_count > 0 ? `+${v.new_rules_count} new` : 'no new'}
        </span>
        <span className="col-span-3 font-mono-editorial text-stone-500">
          {v.source_optimizer_run_id !== null ? `from run ${String(v.source_optimizer_run_id).padStart(4, '0')}` : 'manual'}
        </span>
        <span className="col-span-2 font-mono-editorial text-stone-400 text-right">
          {v.created_at ? new Date(v.created_at).toLocaleDateString() : '—'}
        </span>
      </button>
      {open && (
        <div className="px-1 pb-4 space-y-3">
          {v.rules.length === 0 ? (
            <div className="font-mono-editorial text-stone-400 text-sm">no rules</div>
          ) : (
            v.rules.map((r, i) => (
              <div key={i} className="pl-4 border-l-2 border-violet-300">
                <div className="font-mono-editorial text-stone-400 mb-0.5">
                  {(i + 1).toString().padStart(2, '0')} · {r.id || 'unnamed'}
                  {r.target_labels?.length ? ` · ${r.target_labels.join(' / ')}` : ''}
                </div>
                <div className="text-sm font-medium">{r.boundary || r.rule || '(no boundary)'}</div>
                {r.rule && r.boundary && r.rule !== r.boundary && (
                  <div className="text-sm text-stone-600 mt-0.5 leading-relaxed">{r.rule}</div>
                )}
                {(r.positive_cues?.length || r.negative_cues?.length) ? (
                  <div className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-xs">
                    {r.positive_cues && r.positive_cues.length > 0 && (
                      <span>
                        <span className="font-mono-editorial text-emerald-700 mr-2">+ cues</span>
                        <span className="text-stone-700">{r.positive_cues.map(c => `"${c}"`).join(', ')}</span>
                      </span>
                    )}
                    {r.negative_cues && r.negative_cues.length > 0 && (
                      <span>
                        <span className="font-mono-editorial text-red-700 mr-2">− cues</span>
                        <span className="text-stone-700">{r.negative_cues.map(c => `"${c}"`).join(', ')}</span>
                      </span>
                    )}
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      )}
    </li>
  )
}

function ResearcherToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      title={on
        ? 'Researcher mode on — exposes optimizer choice (ReflectAgent / GEPA / MIPROv2 / OPRO), 3-way split sliders, and round budget.'
        : 'Default mode — one button, no jargon. Click to switch to Researcher mode for optimizer choice and split controls.'}
      className={`shrink-0 inline-flex items-center gap-2 px-3 py-1.5 border text-xs font-medium transition-colors ${
        on
          ? 'border-ink bg-ink text-cream hover:bg-stone-800'
          : 'border-seam text-stone-600 hover:border-stone-400 hover:text-ink'
      }`}
    >
      <span className={`inline-block w-2 h-2 rounded-full ${on ? 'bg-cream' : 'bg-stone-400'}`} />
      <span>Researcher mode</span>
      <span className="font-mono-editorial">{on ? 'on' : 'off'}</span>
    </button>
  )
}

/* ---------- Primitives (shared with ProjectSetup) ---------- */

function SplitTile({
  label, count, pct, hint, accent = false,
}: { label: string; count: number; pct: number; hint: string; accent?: boolean }) {
  return (
    <div className={`p-3 bg-white border ${accent ? 'border-ink' : 'border-seam'}`}>
      <div className="flex items-baseline justify-between mb-1">
        <span className={`text-sm font-medium ${accent ? 'text-ink' : 'text-stone-800'}`}>{label}</span>
        <span className="font-mono-editorial text-stone-400">{pct}%</span>
      </div>
      <div className="font-mono text-2xl font-medium text-ink">{count}</div>
      <div className="font-mono-editorial text-stone-500 mt-1 leading-relaxed">{hint}</div>
    </div>
  )
}

function Section({ num, title, hint, children }: { num: string; title: string; hint?: string; children: React.ReactNode }) {
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

function SplitField({
  label, hint, value, onChange, range, accent = false,
}: {
  label: string
  hint: string
  value: number
  onChange: (v: number) => void
  range: string
  accent?: boolean
}) {
  return (
    <label className={`block border p-3 bg-white ${accent ? 'border-ink' : 'border-seam'}`}>
      <div className="flex items-baseline justify-between mb-1">
        <span className={`text-sm font-medium ${accent ? 'text-ink' : 'text-stone-800'}`}>
          {label}
        </span>
        <span className="font-mono-editorial text-stone-400">{range}</span>
      </div>
      <div className="flex items-baseline gap-1">
        <input
          type="number" min={0} max={100}
          value={value}
          onChange={e => onChange(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
          className="w-full px-0 py-0.5 bg-transparent border-0 font-mono text-2xl font-medium focus:outline-none"
        />
        <span className="font-mono text-sm text-stone-500">%</span>
      </div>
      <div className="font-mono-editorial text-stone-500 mt-1">{hint}</div>
    </label>
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

function DimensionPromptCard({
  dp, optimizedRun, onJumpToRun,
}: {
  dp: { dimension_name: string; prompt: string; version: string; path: string; error: string | null }
  optimizedRun?: OptimizerRun
  onJumpToRun?: () => void
}) {
  const [open, setOpen] = useState(false)
  // When an optimized version exists, two views are available: the original
  // LLM draft and the optimizer's rule-augmented version. Default to the
  // optimized (best) version when available — that's what the user actually
  // ships; the starting prompt is reference only.
  const [view, setView] = useState<'starting' | 'optimized'>(optimizedRun ? 'optimized' : 'starting')
  const test = (optimizedRun?.artifact as any)?.test as { final_score?: number } | undefined
  const score = test?.final_score ?? optimizedRun?.final_score
  const optimizedPrompt = optimizedRun?.optimized_prompt || ''

  return (
    <div className="border border-seam bg-paper/40">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-3 px-5 py-3 hover:bg-paper text-left"
      >
        <div className="flex items-baseline gap-3">
          <span className="font-mono-editorial text-stone-400">{open ? '−' : '+'}</span>
          <span className="font-medium">{dp.dimension_name}</span>
          <span className={`font-mono-editorial ${optimizedRun ? 'text-violet-700' : 'text-stone-400'}`}>
            {optimizedRun
              ? `optimized · run ${optimizedRun.id.toString().padStart(4, '0')}${typeof score === 'number' ? ` · ${(score * 100).toFixed(1)}%` : ''}`
              : dp.version}
          </span>
        </div>
        <div className="flex items-baseline gap-3">
          {dp.error
            ? <span className="font-mono-editorial text-red-700">failed</span>
            : <span className="font-mono-editorial text-stone-500">
                {(optimizedRun ? optimizedPrompt.length : dp.prompt.length).toLocaleString()} chars
              </span>
          }
        </div>
      </button>
      {open && (
        dp.error ? (
          <div className="px-5 py-4 text-sm text-red-700 border-t border-seam">{dp.error}</div>
        ) : (
          <div className="border-t border-seam">
            {optimizedRun && (
              <div className="px-5 py-2 flex items-center gap-3 border-b border-seam bg-paper/60">
                <button
                  type="button"
                  onClick={() => setView('starting')}
                  className={`font-mono-editorial text-xs ${view === 'starting' ? 'text-ink underline' : 'text-stone-500 hover:text-ink'}`}
                >
                  starting
                </button>
                <span className="text-stone-300">·</span>
                <button
                  type="button"
                  onClick={() => setView('optimized')}
                  className={`font-mono-editorial text-xs ${view === 'optimized' ? 'text-violet-700 underline' : 'text-stone-500 hover:text-ink'}`}
                >
                  optimized
                </button>
                {onJumpToRun && (
                  <button
                    type="button"
                    onClick={onJumpToRun}
                    className="ml-auto font-mono-editorial text-xs text-stone-500 hover:text-ink"
                  >
                    open run →
                  </button>
                )}
              </div>
            )}
            <pre className="px-5 py-4 text-xs text-stone-800 whitespace-pre-wrap font-mono leading-relaxed max-h-[420px] overflow-auto">
              {view === 'optimized' ? optimizedPrompt : dp.prompt}
            </pre>
          </div>
        )
      )}
    </div>
  )
}

function OptimizerCard({
  opt, selected, onSelect, emphasized = false,
}: {
  opt: OptimizerInfo
  selected: boolean
  onSelect: () => void
  emphasized?: boolean
}) {
  const ringCls = selected ? 'border-ink shadow-[4px_4px_0_0_rgba(11,11,10,0.08)]' : 'border-seam hover:border-stone-400'
  const roleTone = opt.role === 'method' ? 'text-violet-800' : 'text-stone-500'
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`text-left p-5 bg-white border transition-all ${ringCls} ${emphasized ? 'md:col-span-2' : ''}`}
    >
      <div className="flex items-baseline justify-between gap-2 mb-2">
        <div className="font-mono-editorial text-stone-400">
          {opt.name}
        </div>
        <div className={`font-mono-editorial ${roleTone}`}>
          {opt.role}
        </div>
      </div>
      <div className="text-lg font-medium tracking-tight mb-1">{opt.label}</div>
      <p className="text-sm text-stone-600 leading-relaxed">{opt.description}</p>
    </button>
  )
}

function RunRow({
  run, isSelected, onSelect, onDelete, onCancel, researcherMode,
}: {
  run: OptimizerRun
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
  onCancel: () => void
  researcherMode: boolean
}) {
  const canDelete = run.status !== 'running' && run.status !== 'pending'
  const canCancel = run.status === 'running' || run.status === 'pending'
  const statusTone =
    run.status === 'completed' ? 'text-emerald-700' :
    run.status === 'running' ? 'text-blue-700' :
    run.status === 'failed' ? 'text-red-700' :
    'text-stone-500'

  const friendlyStatus =
    run.status === 'completed' ? 'done' :
    run.status === 'running'   ? 'in progress' :
    run.status === 'pending'   ? 'queued' :
    run.status === 'failed'    ? 'failed' :
    run.status

  // Held-out test score is the user-meaningful number. Fall back to val score
  // for in-flight runs that haven't reached the test eval yet.
  const test = (run.artifact as any)?.test as { final_score?: number; delta?: number } | undefined
  const showScore = run.status === 'completed'
    ? (test?.final_score ?? run.final_score)
    : null
  const showDelta = run.status === 'completed'
    ? (test?.delta ?? (run.final_score - run.initial_score))
    : null

  return (
    <li
      onClick={onSelect}
      className={`group grid grid-cols-12 gap-4 py-4 items-baseline cursor-pointer transition-colors ${isSelected ? 'bg-paper' : 'hover:bg-paper/60'}`}
    >
      <div className="col-span-1 font-mono text-xs text-stone-400">
        {run.id.toString().padStart(4, '0')}
      </div>
      <div className="col-span-3">
        <div className="font-medium">
          {researcherMode ? run.optimizer_name : run.dimension_name}
        </div>
        <div className="font-mono-editorial text-stone-400 mt-0.5">
          {researcherMode ? run.dimension_name : 'improve from examples'}
        </div>
      </div>
      <div className="col-span-2">
        <div className={`font-mono-editorial ${statusTone}`}>
          {researcherMode ? run.status : friendlyStatus}
        </div>
      </div>
      <div className="col-span-2 text-right">
        <div className="font-mono text-sm">
          {showScore !== null ? `${(showScore * 100).toFixed(1)}%` : '—'}
        </div>
        {showDelta !== null && (
          <div className={`font-mono-editorial ${showDelta >= 0 ? 'text-emerald-700' : 'text-red-600'}`}>
            {showDelta >= 0 ? '+' : ''}{(showDelta * 100).toFixed(1)}pp
          </div>
        )}
      </div>
      <div className="col-span-2 text-right font-mono text-xs text-stone-600">
        {researcherMode ? `$${run.total_cost.toFixed(4)}` : ''}
      </div>
      <div className="col-span-2 flex items-center justify-end gap-3 text-stone-400">
        {canCancel && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (window.confirm(`Stop run ${run.id.toString().padStart(4, '0')} (${run.dimension_name})? Partial progress will be discarded.`)) {
                onCancel()
              }
            }}
            className="opacity-0 group-hover:opacity-100 hover:opacity-100 font-mono-editorial text-stone-400 hover:text-amber-700 text-xs transition-opacity"
            title="Cancel this run"
          >
            stop
          </button>
        )}
        {canDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (window.confirm(`Delete run ${run.id.toString().padStart(4, '0')} (${run.dimension_name})? This cannot be undone.`)) {
                onDelete()
              }
            }}
            className="opacity-0 group-hover:opacity-100 hover:opacity-100 font-mono-editorial text-stone-400 hover:text-red-600 text-xs transition-opacity"
            title="Delete this run"
          >
            delete
          </button>
        )}
        <span>{isSelected ? '↑' : '↓'}</span>
      </div>
    </li>
  )
}

function RunDetail({
  run, researcherMode, onUpdate, projectId,
}: {
  run: OptimizerRun
  researcherMode: boolean
  onUpdate: (updated: OptimizerRun) => void
  projectId: number
}) {
  const ruleLib: any[] = Array.isArray(run.artifact?.rule_library) ? run.artifact.rule_library : []
  const delta = run.final_score - run.initial_score

  // Held-out test info (set after optimization finishes on a set the optimizer never saw)
  const test = (run.artifact as any)?.test as
    | { initial_score: number; final_score: number; delta: number; n: number; cost_usd: number }
    | undefined
  const splits = (run.artifact as any)?.splits as
    | { n_train: number; n_val: number; n_test: number; seed?: number }
    | undefined

  const isRunning = run.status === 'running' || run.status === 'pending'
  const budget = run.budget || 1
  // Find the highest explicit round number seen in the trajectory so the
  // progress bar reflects what the optimizer has actually done.
  let currentRound = 0
  for (const t of (run.trajectory || [])) {
    const r = (t as any)?.round
    if (typeof r === 'number' && r > currentRound) currentRound = r
  }
  const progressPct = isRunning
    ? Math.max(4, Math.min(100, (currentRound / budget) * 100))
    : 100

  const statusTone =
    run.status === 'completed' ? 'text-emerald-700 border-emerald-400' :
    run.status === 'running'   ? 'text-blue-700    border-blue-400'    :
    run.status === 'pending'   ? 'text-stone-600   border-stone-400'   :
    run.status === 'failed'    ? 'text-red-700     border-red-400'     :
                                 'text-stone-600   border-stone-300'

  return (
    <div className="border border-seam bg-white">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-seam">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-1 flex items-baseline gap-3">
            <span title={researcherMode ? '' : `optimizer: ${run.optimizer_name}`}>
              {researcherMode
                ? `Run № ${run.id.toString().padStart(4, '0')} · ${run.optimizer_name}`
                : `Improvement № ${run.id.toString().padStart(4, '0')}`}
            </span>
            <span className={`font-mono-editorial px-2 py-0.5 border ${statusTone}`}>
              {run.status}{isRunning ? ' · live' : ''}
            </span>
          </div>
          <h3 className="text-xl font-medium tracking-tight">{run.dimension_name}</h3>
        </div>
        <div className="flex gap-6 text-right items-start">
          {test ? (
            researcherMode ? (
              <>
                <Metric label="Test · initial" value={`${(test.initial_score * 100).toFixed(1)}%`} />
                <Metric
                  label="Test · final (held-out)"
                  value={`${(test.final_score * 100).toFixed(1)}%`}
                  tone={test.delta >= 0 ? 'text-emerald-700' : 'text-red-700'}
                />
                <Metric
                  label="Test · Δ"
                  value={`${test.delta >= 0 ? '+' : ''}${(test.delta * 100).toFixed(1)}pp`}
                  tone={test.delta > 0 ? 'text-emerald-700' : test.delta < 0 ? 'text-red-700' : 'text-stone-500'}
                />
                <Metric label="Val · final (dev)" value={`${(run.final_score * 100).toFixed(1)}%`} tone="text-stone-500" />
                <Metric label="Cost" value={`$${run.total_cost.toFixed(4)}`} />
              </>
            ) : (
              <>
                <Metric label="Before" value={`${(test.initial_score * 100).toFixed(1)}%`} />
                <Metric
                  label="After"
                  value={`${(test.final_score * 100).toFixed(1)}%`}
                  tone={test.delta >= 0 ? 'text-emerald-700' : 'text-red-700'}
                />
                <Metric
                  label="Change"
                  value={`${test.delta >= 0 ? '+' : ''}${(test.delta * 100).toFixed(1)}pp`}
                  tone={test.delta > 0 ? 'text-emerald-700' : test.delta < 0 ? 'text-red-700' : 'text-stone-500'}
                />
              </>
            )
          ) : (
            researcherMode ? (
              <>
                <Metric label="Val · initial" value={`${(run.initial_score * 100).toFixed(1)}%`} />
                <Metric label="Val · final (dev)" value={`${(run.final_score * 100).toFixed(1)}%`}
                        tone={delta >= 0 ? 'text-emerald-700' : 'text-red-700'} />
                <Metric label="Δ" value={`${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}pp`}
                        tone={delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-red-700' : 'text-stone-500'} />
                <Metric label="Cost" value={`$${run.total_cost.toFixed(4)}`} />
              </>
            ) : (
              <>
                <Metric label="Before" value={`${(run.initial_score * 100).toFixed(1)}%`} />
                <Metric label="So far" value={`${(run.final_score * 100).toFixed(1)}%`}
                        tone={delta >= 0 ? 'text-emerald-700' : 'text-red-700'} />
                <Metric label="Change" value={`${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}pp`}
                        tone={delta > 0 ? 'text-emerald-700' : delta < 0 ? 'text-red-700' : 'text-stone-500'} />
              </>
            )
          )}
        </div>
      </div>

      {/* Live progress strip */}
      <div className="px-6 py-3 border-b border-seam bg-paper/30">
        <div className="flex items-center justify-between font-mono-editorial text-stone-500 mb-1.5">
          <span>
            {isRunning ? 'Live · round' : 'Done · round'} {currentRound} / {budget}
          </span>
          {researcherMode && (
            <span>
              {(run.trajectory?.length || 0)} trajectory entries · {run.total_tokens.toLocaleString()} tokens
            </span>
          )}
        </div>
        <div className="w-full h-[3px] bg-seam overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${isRunning ? 'bg-blue-600' : 'bg-ink'}`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
        {splits && researcherMode && (
          <div className="mt-2 flex items-center justify-between font-mono-editorial text-stone-500">
            <span>
              Split · train {splits.n_train} · val {splits.n_val} · test {splits.n_test}
              {splits.seed !== undefined && <span className="ml-3">seed {splits.seed}</span>}
            </span>
            <span className="text-emerald-700">test held out (not seen by optimizer)</span>
          </div>
        )}
        {splits && !researcherMode && (
          <div className="mt-2 font-mono-editorial text-stone-500">
            <span>
              {splits.n_train} examples to learn from · {splits.n_val} to verify · {splits.n_test} held out for the honest score
            </span>
          </div>
        )}
      </div>

      {run.error && (
        <div className="px-6 py-4 border-b border-seam bg-red-50/50 text-sm text-red-800">
          <div className="font-mono-editorial text-red-700 mb-1">Error</div>
          <pre className="whitespace-pre-wrap font-mono text-xs">{run.error}</pre>
        </div>
      )}

      {/* Trajectory · per-round progress log */}
      {run.trajectory?.length > 0 && (
        <div className="px-6 py-4 border-b border-seam">
          <div className="font-mono-editorial text-stone-500 mb-3">
            {researcherMode ? 'Trajectory' : 'Round-by-round progress'}
          </div>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="border-b border-seam">
                <th className="px-2 py-2 text-left text-stone-500">Round</th>
                <th className="px-2 py-2 text-right text-stone-500">
                  {researcherMode ? 'Val acc' : 'Accuracy'}
                </th>
                <th className="px-2 py-2 text-left text-stone-500">
                  {researcherMode ? 'Action' : 'Outcome'}
                </th>
                <th className="px-2 py-2 text-right text-stone-500">
                  {researcherMode ? 'Rules' : 'Notes'}
                </th>
                <th className="px-2 py-2 text-right text-stone-500">
                  {researcherMode ? 'Failures' : 'Mistakes'}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-seam">
              {run.trajectory.map((t: any, i: number) => (
                <tr key={i}>
                  <td className="px-2 py-2 text-stone-700">{t.round ?? i}</td>
                  <td className="px-2 py-2 text-right">
                    {typeof t.val_acc === 'number' ? (t.val_acc * 100).toFixed(1) + '%' : '—'}
                  </td>
                  <td className="px-2 py-2">
                    <span
                      title={researcherMode ? '' : `internal action: ${t.action ?? '—'}`}
                      className={
                        t.action === 'accept' ? 'text-emerald-700' :
                        t.action === 'rollback' ? 'text-amber-700' :
                        t.action === 'improve' ? 'text-emerald-700' :
                        t.action === 'reject' ? 'text-stone-500' :
                        'text-stone-700'
                      }
                    >
                      {researcherMode
                        ? (t.action ?? '—')
                        : ({ accept: 'kept', rollback: 'rolled back', improve: 'kept',
                             reject: 'discarded', skipped: 'no change' } as Record<string, string>)[t.action] ?? (t.action ?? '—')}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right text-stone-600">{t.n_rules ?? '—'}</td>
                  <td className="px-2 py-2 text-right text-stone-600">{t.n_failures ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Trajectory chart — visual companion to the table above */}
      {(run.trajectory?.length || 0) > 1 && (
        <div className="px-6 py-4 border-b border-seam">
          <div className="font-mono-editorial text-stone-500 mb-3">
            {researcherMode ? 'Validation accuracy & macro F1 by round' : 'Accuracy & F1 by round'}
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={(run.trajectory || []).map((t: any) => ({
                  round: t.round,
                  acc: typeof t.val_acc === 'number' ? t.val_acc * 100 : null,
                  f1:  typeof t.val_macro_f1 === 'number' ? t.val_macro_f1 * 100 : null,
                }))}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="2 4" stroke="#E5E2D9" />
                <XAxis dataKey="round" tick={{ fontSize: 11, fill: '#9A968F' }} stroke="#D6D2C8" />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#9A968F' }} stroke="#D6D2C8"
                       tickFormatter={(v) => `${v}%`} />
                <Tooltip
                  contentStyle={{ fontSize: 12, background: '#FAF7F0', border: '1px solid #E5E2D9' }}
                  formatter={(v: any) => typeof v === 'number' ? `${v.toFixed(1)}%` : '—'}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="acc" name="Val accuracy" stroke="#0B0B0A" strokeWidth={2}
                      dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls />
                <Line type="monotone" dataKey="f1"  name="Val macro F1" stroke="#6E4FBE" strokeWidth={2}
                      strokeDasharray="4 3" dot={{ r: 3 }} activeDot={{ r: 5 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Per-class metrics — only present when test eval finished */}
      {test && (test as any).final_metrics && (
        <PerClassMetricsBlock
          initial={(test as any).initial_metrics}
          final={(test as any).final_metrics}
          researcherMode={researcherMode}
        />
      )}

      {/* Rule library (ReflectAgent only) — shown as "Guidance notes" in default mode */}
      {ruleLib.length > 0 && (
        <div className="px-6 py-4 border-b border-seam">
          <div className="flex items-baseline gap-3 mb-4">
            <div
              className="font-mono-editorial text-stone-500"
              title={researcherMode ? '' : 'Rule library — the editable, versioned ReflectAgent artifact.'}
            >
              {researcherMode ? 'Rule library' : 'Guidance notes'}
            </div>
            <div className="font-mono-editorial text-violet-700">
              {researcherMode
                ? `${ruleLib.length} rules · ReflectAgent artifact`
                : `${ruleLib.length} ${ruleLib.length === 1 ? 'note' : 'notes'} learned from your examples`}
            </div>
          </div>
          <ul className="space-y-4">
            {ruleLib.map((r: any, i: number) => (
              <li key={i} className="pl-4 border-l-2 border-violet-300">
                <div className="font-mono-editorial text-stone-400 mb-1">
                  {(i + 1).toString().padStart(2, '0')} · {r.id || 'unnamed'}
                  {r.target_labels?.length ? ` · ${r.target_labels.join(' / ')}` : ''}
                </div>
                <div className="text-sm font-medium">{r.boundary}</div>
                {r.rule && r.rule !== r.boundary && (
                  <div className="text-sm text-stone-600 mt-1 leading-relaxed">{r.rule}</div>
                )}
                {(r.positive_cues?.length || r.negative_cues?.length) ? (
                  <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs">
                    {r.positive_cues?.length > 0 && (
                      <span>
                        <span className="font-mono-editorial text-emerald-700 mr-2">+ cues</span>
                        <span className="text-stone-700">{r.positive_cues.map((c: string) => `"${c}"`).join(', ')}</span>
                      </span>
                    )}
                    {r.negative_cues?.length > 0 && (
                      <span>
                        <span className="font-mono-editorial text-red-700 mr-2">− cues</span>
                        <span className="text-stone-700">{r.negative_cues.map((c: string) => `"${c}"`).join(', ')}</span>
                      </span>
                    )}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Final prompt — editable when the run has finished */}
      {run.optimized_prompt && (
        <EditablePromptBlock
          run={run}
          researcherMode={researcherMode}
          projectId={projectId}
          onUpdate={onUpdate}
        />
      )}
    </div>
  )
}

function EditablePromptBlock({
  run, researcherMode, projectId, onUpdate,
}: {
  run: OptimizerRun
  researcherMode: boolean
  projectId: number
  onUpdate: (updated: OptimizerRun) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(run.optimized_prompt)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string>('')

  // If the parent loads a different run, reset the local draft.
  const [trackedRunId, setTrackedRunId] = useState(run.id)
  if (trackedRunId !== run.id) {
    setTrackedRunId(run.id)
    setDraft(run.optimized_prompt)
    setEditing(false); setErr('')
  }

  const dirty = draft !== run.optimized_prompt
  const editable = run.status === 'completed' || run.status === 'failed'

  const save = async () => {
    setSaving(true); setErr('')
    try {
      const updated = await patchOptimizerRun(projectId, run.id, { optimized_prompt: draft })
      onUpdate(updated)
      setEditing(false)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="px-6 py-4">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <div className="font-mono-editorial text-stone-500">
          {researcherMode ? 'Optimized prompt' : 'Updated instructions'}
          {dirty && <span className="ml-2 text-amber-700">unsaved edits</span>}
        </div>
        <div className="flex items-center gap-3">
          {!editing && editable && (
            <button
              onClick={() => setEditing(true)}
              className="font-mono-editorial text-stone-500 hover:text-ink"
            >
              edit
            </button>
          )}
          {editing && (
            <>
              <button
                onClick={() => { setDraft(run.optimized_prompt); setEditing(false); setErr('') }}
                disabled={saving}
                className="font-mono-editorial text-stone-500 hover:text-ink"
              >
                cancel
              </button>
              <button
                onClick={save}
                disabled={saving || !dirty}
                className="px-3 py-1 text-xs font-medium bg-ink text-cream hover:bg-stone-800 disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          )}
        </div>
      </div>
      {editing ? (
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          rows={Math.min(28, Math.max(10, draft.split('\n').length + 1))}
          className="w-full bg-white border border-seam focus:border-ink focus:outline-none p-4 font-mono text-xs leading-relaxed text-stone-800 resize-y"
        />
      ) : (
        <pre className="bg-paper/50 border border-seam p-4 font-mono text-xs leading-relaxed max-h-80 overflow-auto whitespace-pre-wrap text-stone-800">
          {run.optimized_prompt}
        </pre>
      )}
      {err && (
        <div className="mt-2 text-xs text-red-700">{err}</div>
      )}
    </div>
  )
}

function PerClassMetricsBlock({
  initial, final, researcherMode,
}: { initial: any; final: any; researcherMode: boolean }) {
  const labels: string[] = (final?.classes ?? Object.keys(final?.per_class || {})).slice().sort()
  const headerLine = (
    <div className="flex items-baseline gap-6 flex-wrap font-mono text-xs">
      <span><span className="font-mono-editorial text-stone-500 mr-1.5">Macro F1</span>
            <span className="text-stone-700">{(initial.macro_f1 * 100).toFixed(1)}%</span>
            <span className="text-stone-400 mx-1">→</span>
            <span className={final.macro_f1 >= initial.macro_f1 ? 'text-emerald-700' : 'text-red-600'}>
              {(final.macro_f1 * 100).toFixed(1)}%
            </span></span>
      <span><span className="font-mono-editorial text-stone-500 mr-1.5">Weighted F1</span>
            <span className="text-stone-700">{(initial.weighted_f1 * 100).toFixed(1)}%</span>
            <span className="text-stone-400 mx-1">→</span>
            <span className={final.weighted_f1 >= initial.weighted_f1 ? 'text-emerald-700' : 'text-red-600'}>
              {(final.weighted_f1 * 100).toFixed(1)}%
            </span></span>
      <span><span className="font-mono-editorial text-stone-500 mr-1.5">Macro precision</span>
            <span className="text-stone-700">{(initial.macro_precision * 100).toFixed(1)}%</span>
            <span className="text-stone-400 mx-1">→</span>
            <span className="text-stone-700">{(final.macro_precision * 100).toFixed(1)}%</span></span>
      <span><span className="font-mono-editorial text-stone-500 mr-1.5">Macro recall</span>
            <span className="text-stone-700">{(initial.macro_recall * 100).toFixed(1)}%</span>
            <span className="text-stone-400 mx-1">→</span>
            <span className="text-stone-700">{(final.macro_recall * 100).toFixed(1)}%</span></span>
    </div>
  )

  return (
    <div className="px-6 py-4 border-b border-seam">
      <div className="font-mono-editorial text-stone-500 mb-3">
        {researcherMode ? 'Held-out test metrics · per-class' : 'Per-label scores on the held-out set'}
      </div>
      <div className="mb-4">{headerLine}</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-seam">
              <th className="px-2 py-2 text-left text-stone-500">Label</th>
              <th className="px-2 py-2 text-right text-stone-500">Support</th>
              <th className="px-2 py-2 text-right text-stone-500">Precision</th>
              <th className="px-2 py-2 text-right text-stone-500">Recall</th>
              <th className="px-2 py-2 text-right text-stone-500">F1 (initial → final)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-seam">
            {labels.map(lbl => {
              const i = initial?.per_class?.[lbl]
              const f = final?.per_class?.[lbl]
              const f1Delta = (f?.f1 ?? 0) - (i?.f1 ?? 0)
              return (
                <tr key={lbl}>
                  <td className="px-2 py-2 text-stone-800">{lbl}</td>
                  <td className="px-2 py-2 text-right text-stone-600">{f?.support ?? 0}</td>
                  <td className="px-2 py-2 text-right text-stone-600">
                    {f != null ? `${(f.precision * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-2 py-2 text-right text-stone-600">
                    {f != null ? `${(f.recall * 100).toFixed(1)}%` : '—'}
                  </td>
                  <td className="px-2 py-2 text-right text-stone-700">
                    {i != null ? `${(i.f1 * 100).toFixed(1)}%` : '—'}
                    <span className="text-stone-400 mx-1">→</span>
                    <span className={f1Delta > 0 ? 'text-emerald-700' : f1Delta < 0 ? 'text-red-600' : 'text-stone-700'}>
                      {f != null ? `${(f.f1 * 100).toFixed(1)}%` : '—'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Metric({ label, value, tone = 'text-ink' }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="font-mono-editorial text-stone-500">{label}</div>
      <div className={`font-mono text-sm mt-0.5 ${tone}`}>{value}</div>
    </div>
  )
}
