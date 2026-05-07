import { useEffect, useState } from 'react'
import {
  uploadCodebookDraft, pasteCodebookDraft, presetCodebookDraft,
  acceptCodebookDraft, deleteCodebookDraft, patchCodebookDraft,
  artifactDownloadUrl,
  type CodebookDraft,
} from '../lib/api'
import type { PresetInfo } from '../types'

type Door = 'upload' | 'paste' | 'preset' | 'scratch'

export default function CodebookDraftWizard({
  projectId,
  presets,
  onAccepted,
}: {
  projectId: number
  presets: PresetInfo[]
  onAccepted: () => void
}) {
  const [door, setDoor] = useState<Door>('preset')            // Door C default
  const [draft, setDraft] = useState<CodebookDraft | null>(null)
  const [loading, setLoading] = useState<string>('')         // free-form status line
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState<string>('')

  // Door-specific inputs
  const [pasteText, setPasteText] = useState('')
  const [presetName, setPresetName] = useState(presets[0]?.name || 'self_disclosure')

  useEffect(() => {
    if (!presetName && presets.length > 0) setPresetName(presets[0].name)
  }, [presets, presetName])

  const resetAll = () => {
    setDraft(null); setError(''); setLoading(''); setPasteText('')
  }

  const clearDraft = async () => {
    if (draft?.id) { try { await deleteCodebookDraft(draft.id) } catch {} }
    resetAll()
  }

  const handleUpload = async (file: File) => {
    setLoading(`Ingesting ${file.name}…`); setError(''); setDraft(null)
    try {
      const d = await uploadCodebookDraft(file)
      setDraft(d)
      if (d.status !== 'ready') setError(d.error_message || 'Draft failed.')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Upload failed')
    } finally {
      setLoading('')
    }
  }

  const handlePaste = async () => {
    if (pasteText.trim().length < 20) {
      setError('Paste at least 20 characters.')
      return
    }
    setLoading('Agent reading your text…'); setError(''); setDraft(null)
    try {
      const d = await pasteCodebookDraft(pasteText)
      setDraft(d)
      if (d.status !== 'ready') setError(d.error_message || 'Draft failed.')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Draft failed')
    } finally {
      setLoading('')
    }
  }

  const handlePreset = async () => {
    setLoading('Loading preset…'); setError(''); setDraft(null)
    try {
      const d = await presetCodebookDraft(presetName)
      setDraft(d)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Preset load failed')
    } finally {
      setLoading('')
    }
  }

  const handleAccept = async (editedJson?: Record<string, any>) => {
    if (!draft) return
    setAccepting(true); setError('')
    try {
      // Persist user edits (if any) before accepting so the codebook row
      // committed to the project reflects the final state shown in the UI.
      if (editedJson) {
        await patchCodebookDraft(draft.id, editedJson)
      }
      await acceptCodebookDraft(projectId, draft.id)
      onAccepted()
    } catch (e: any) {
      setError(e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Accept failed')
    } finally {
      setAccepting(false)
    }
  }

  const inFlight = !!loading
  const hasDraft = draft && draft.status === 'ready'

  /* Render --------------------------------------------------------------- */
  return (
    <div className="space-y-6">
      {/* Door chooser */}
      {!hasDraft && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <DoorCard
            door="upload"
            active={door === 'upload'}
            onClick={() => setDoor('upload')}
            title="A · Upload a file"
            hint="PDF · DOCX · XLSX · CSV · JSON · TXT — agent parses + cleans"
          />
          <DoorCard
            door="paste"
            active={door === 'paste'}
            onClick={() => setDoor('paste')}
            title="B · Paste text"
            hint="Annotator notes, instructions, or an old draft — anything in text"
          />
          <DoorCard
            door="preset"
            active={door === 'preset'}
            onClick={() => setDoor('preset')}
            title="C · Use a preset"
            hint={`Self-disclosure · AI behavior · ${presets.length} available`}
            emphasized
          />
          <DoorCard
            door="scratch"
            active={door === 'scratch'}
            onClick={() => setDoor('scratch')}
            title="D · Describe it to me"
            hint="Conversational elicitor (Phase 3 — not yet available)"
            disabled
          />
        </div>
      )}

      {/* Door body */}
      {!hasDraft && (
        <div className="border border-seam bg-white p-6">
          {door === 'upload' && (
            <UploadForm onFile={handleUpload} busy={inFlight} />
          )}
          {door === 'paste' && (
            <PasteForm
              value={pasteText}
              onChange={setPasteText}
              onSubmit={handlePaste}
              busy={inFlight}
            />
          )}
          {door === 'preset' && (
            <PresetForm
              presets={presets}
              value={presetName}
              onChange={setPresetName}
              onSubmit={handlePreset}
              busy={inFlight}
            />
          )}
          {door === 'scratch' && (
            <p className="font-mono-editorial text-stone-400 text-center py-8">
              Coming in Phase 3 — use doors A, B, or C for now.
            </p>
          )}
        </div>
      )}

      {/* Status strip */}
      {inFlight && (
        <div className="flex items-center gap-3 text-sm text-stone-600 border-l-2 border-ink pl-4">
          <span className="inline-block w-2 h-2 rounded-full bg-ink animate-pulse" />
          <span>{loading}</span>
          <span className="font-mono-editorial text-stone-400 ml-auto">CodebookAgent</span>
        </div>
      )}

      {error && (
        <div className="border border-red-200 bg-red-50/60 text-red-800 p-4 text-sm">
          <div className="font-mono-editorial text-red-700 mb-1">Error</div>
          <div>{error}</div>
        </div>
      )}

      {/* Draft preview */}
      {draft && (
        <DraftPreview
          draft={draft}
          onAccept={handleAccept}
          onDiscard={clearDraft}
          accepting={accepting}
        />
      )}
    </div>
  )
}

/* ─── Door cards ───────────────────────────────────────────── */

function DoorCard({
  door, title, hint, active, onClick, emphasized = false, disabled = false,
}: {
  door: Door
  title: string
  hint: string
  active: boolean
  onClick: () => void
  emphasized?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`text-left p-5 bg-white border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
        active
          ? 'border-ink shadow-[4px_4px_0_0_rgba(11,11,10,0.08)]'
          : 'border-seam hover:border-stone-400'
      } ${emphasized ? 'ring-1 ring-offset-0 ring-indigo-200' : ''}`}
    >
      <div className="font-mono-editorial text-stone-500 mb-2">
        Door {door.toUpperCase()}
        {emphasized && <span className="ml-2 text-indigo-700">· default</span>}
      </div>
      <div className="text-lg font-medium tracking-tight mb-1">{title}</div>
      <p className="text-sm text-stone-600 leading-relaxed">{hint}</p>
    </button>
  )
}

/* ─── Door forms ───────────────────────────────────────────── */

function UploadForm({ onFile, busy }: { onFile: (f: File) => void; busy: boolean }) {
  const [drag, setDrag] = useState(false)
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-3">
        Upload · 16 MB max · pdf · docx · xlsx · csv · json · txt
      </div>
      <label
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => {
          e.preventDefault()
          setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f) onFile(f)
        }}
        className={`block border-2 border-dashed p-10 text-center cursor-pointer transition-colors ${
          drag ? 'border-ink bg-paper' : 'border-seam bg-paper/40 hover:border-stone-400'
        }`}
      >
        <input
          type="file"
          accept=".pdf,.docx,.xlsx,.csv,.json,.txt,.md"
          className="hidden"
          disabled={busy}
          onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }}
        />
        <div className="font-mono-editorial text-stone-500 mb-2">
          {busy ? 'uploading…' : 'click or drag a file here'}
        </div>
        <p className="text-sm text-stone-600">
          Dropping raw annotator XLSX auto-produces both a codebook and a cleaned <code className="font-mono text-[11px]">cleaned_data.json</code>.
        </p>
      </label>
    </div>
  )
}

function PasteForm({
  value, onChange, onSubmit, busy,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
}) {
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-3">
        Paste annotator notes, an old codebook, or any structured text
      </div>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={10}
        className="w-full px-3 py-3 border border-seam bg-white focus:border-ink focus:outline-none font-mono text-xs leading-relaxed"
        placeholder="Example:&#10;&#10;Annotate user messages on three dimensions:&#10;1. Level of disclosure — High / Low / No&#10;2. Topic — causal, emotional, advice, intimate...&#10;3. Confession — yes / no&#10;&#10;Paste as much detail as you have; the agent will structure it."
      />
      <div className="mt-4 flex items-center justify-between">
        <div className="font-mono text-xs text-stone-500">
          {value.length.toLocaleString()} chars {value.length < 20 && '· need ≥ 20'}
        </div>
        <button
          onClick={onSubmit}
          disabled={busy || value.trim().length < 20}
          className="px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {busy ? 'Drafting…' : 'Draft with agent →'}
        </button>
      </div>
    </div>
  )
}

function PresetForm({
  presets, value, onChange, onSubmit, busy,
}: {
  presets: PresetInfo[]
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
}) {
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-3">
        Choose a preset — instant load, no LLM drafting
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        {presets.map(p => (
          <label
            key={p.name}
            className={`flex items-start gap-3 p-4 border cursor-pointer transition-colors ${
              value === p.name ? 'border-ink bg-paper' : 'border-seam hover:border-stone-400'
            }`}
          >
            <input
              type="radio"
              name="preset"
              value={p.name}
              checked={value === p.name}
              onChange={() => onChange(p.name)}
              className="mt-1"
            />
            <div>
              <div className="font-medium">{p.name}</div>
              <div className="text-xs text-stone-500 mt-0.5">{p.dimensions} dimensions</div>
              {p.description && (
                <div className="text-sm text-stone-600 mt-1 leading-relaxed">{p.description}</div>
              )}
            </div>
          </label>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          onClick={onSubmit}
          disabled={busy || !value}
          className="px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {busy ? 'Loading…' : 'Load preset →'}
        </button>
      </div>
    </div>
  )
}

/* ─── Draft preview (editable) ──────────────────────────────── */

function DraftPreview({
  draft, onAccept, onDiscard, accepting,
}: {
  draft: CodebookDraft
  onAccept: (editedJson?: Record<string, any>) => void
  onDiscard: () => void
  accepting: boolean
}) {
  // Local working copy. Reset whenever we get a new draft from the server.
  const [working, setWorking] = useState<any>(() => structuredClone(draft.draft_json || {}))
  const [draftId, setDraftId] = useState<number>(draft.id)
  if (draft.id !== draftId) {
    setDraftId(draft.id)
    setWorking(structuredClone(draft.draft_json || {}))
  }

  const dirty = JSON.stringify(working) !== JSON.stringify(draft.draft_json || {})
  const dimensions: any[] = Array.isArray(working.dimensions) ? working.dimensions : []
  const rationalePerDim: Record<string, string> =
    (draft.draft_json || {})._rationale_per_dim || {}

  const flags = draft.critic_flags || []
  const errorFlags = flags.filter(f => f.severity === 'error')
  const warnFlags = flags.filter(f => f.severity === 'warn')
  const infoFlags = flags.filter(f => f.severity === 'info')

  const updateDim = (i: number, patch: Partial<any>) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims[i] = { ...dims[i], ...patch }
      return { ...w, dimensions: dims }
    })
  }
  const updateLabel = (i: number, j: number, patch: Partial<any>) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || [])]
      labels[j] = { ...labels[j], ...patch }
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  const removeLabel = (i: number, j: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || [])]
      labels.splice(j, 1)
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  const addLabel = (i: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || []), { name: 'new_label', definition: '', examples: [] }]
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  const removeDim = (i: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims.splice(i, 1)
      return { ...w, dimensions: dims }
    })
  }

  const handleAccept = () => onAccept(dirty ? working : undefined)

  const ActionBar = () => (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div className="font-mono-editorial text-stone-500">
        {dirty ? <span className="text-amber-700">unsaved edits</span> : <span>no edits</span>}
        <span className="text-stone-400 mx-2">·</span>
        {dimensions.length} dimensions ·{' '}
        {dimensions.reduce((n, d) => n + (d.labels?.length || 0), 0)} labels
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onDiscard}
          disabled={accepting}
          className="px-4 py-2 text-sm font-medium text-stone-600 border border-seam hover:border-stone-400"
        >
          Discard
        </button>
        <button
          onClick={handleAccept}
          disabled={accepting || errorFlags.length > 0}
          title={errorFlags.length > 0 ? 'Resolve critic errors first' : ''}
          className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {accepting ? 'Accepting…' : dirty ? 'Save & load →' : 'Accept & load →'}
        </button>
      </div>
    </div>
  )

  return (
    <div className="border border-seam bg-white">
      {/* TOP: editable header + action bar */}
      <div className="p-5 border-b border-seam space-y-4">
        <div className="font-mono-editorial text-stone-500">
          Draft · №{draft.id.toString().padStart(4, '0')} · {draft.source}
          {draft.source_filename && ` · ${draft.source_filename}`}
        </div>
        <input
          value={working.name || ''}
          onChange={e => setWorking((w: any) => ({ ...w, name: e.target.value }))}
          className="w-full px-0 py-1 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-2xl font-medium tracking-tight"
          placeholder="Codebook name"
        />
        <textarea
          value={working.description || ''}
          onChange={e => setWorking((w: any) => ({ ...w, description: e.target.value }))}
          rows={2}
          className="w-full px-0 py-1 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-sm text-stone-700 leading-relaxed resize-none"
          placeholder="One-line description of what this codebook annotates"
        />
        <ActionBar />
      </div>

      {/* Split: schema | rationale */}
      <div className="grid grid-cols-1 lg:grid-cols-3">
        <div className="lg:col-span-2 divide-y divide-seam">
          {dimensions.map((dim: any, i: number) => (
            <div key={i} className="p-5 flex gap-5">
              <div className="font-mono-editorial text-stone-400 w-8 shrink-0 pt-2">
                {(i + 1).toString().padStart(2, '0')}
              </div>
              <div className="flex-1 min-w-0 space-y-2.5">
                <div className="flex items-baseline gap-3 flex-wrap">
                  <input
                    value={dim.name || ''}
                    onChange={e => updateDim(i, { name: e.target.value })}
                    className="px-0 py-0.5 bg-transparent border-0 border-b border-transparent hover:border-seam focus:border-ink focus:outline-none text-lg font-medium min-w-0 flex-1"
                    placeholder="Dimension name"
                  />
                  <select
                    value={dim.type || 'single_label'}
                    onChange={e => updateDim(i, { type: e.target.value })}
                    className={`font-mono-editorial bg-transparent border-0 border-b border-transparent hover:border-seam focus:border-ink focus:outline-none ${
                      (dim.type || '').includes('multi') ? 'text-violet-700' : 'text-indigo-700'
                    }`}
                  >
                    <option value="single_label">single_label</option>
                    <option value="multi_label">multi_label</option>
                    <option value="binary">binary</option>
                    <option value="ordinal">ordinal</option>
                  </select>
                  <span className="font-mono-editorial text-stone-400">
                    {(dim.labels || []).length} labels
                  </span>
                  <button
                    onClick={() => removeDim(i)}
                    className="ml-auto font-mono-editorial text-stone-400 hover:text-red-600 text-xs"
                  >
                    remove dimension
                  </button>
                </div>
                <textarea
                  value={dim.instructions || ''}
                  onChange={e => updateDim(i, { instructions: e.target.value })}
                  rows={2}
                  className="w-full px-2 py-1.5 bg-paper/40 border border-transparent hover:border-seam focus:border-ink focus:outline-none text-xs text-stone-700 italic leading-relaxed resize-y"
                  placeholder="Annotation instructions for this dimension (optional)"
                />
                <div className="space-y-1">
                  {(dim.labels || []).map((lbl: any, j: number) => (
                    <LabelEditor
                      key={j}
                      lbl={lbl}
                      onChange={(patch) => updateLabel(i, j, patch)}
                      onRemove={() => removeLabel(i, j)}
                    />
                  ))}
                  <button
                    onClick={() => addLabel(i)}
                    className="text-xs px-2 py-1 border border-dashed border-seam hover:border-ink text-stone-500 hover:text-ink"
                  >
                    + add label
                  </button>
                </div>
                {rationalePerDim[dim.name] && (
                  <p className="text-xs text-stone-500 italic leading-relaxed border-l-2 border-stone-200 pl-3 mt-3">
                    {rationalePerDim[dim.name]}
                  </p>
                )}
              </div>
            </div>
          ))}
          {dimensions.length === 0 && (
            <div className="p-10 text-center font-mono-editorial text-stone-400">
              No dimensions in draft.
            </div>
          )}
        </div>

        <div className="border-t lg:border-t-0 lg:border-l border-seam bg-paper/30 p-5 space-y-5">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">Source</div>
            <div className="text-sm text-stone-700">{draft.source_filename || '(inline)'}</div>
            {draft.source_bytes > 0 && (
              <div className="font-mono text-[11px] text-stone-400 mt-0.5">
                {(draft.source_bytes / 1024).toFixed(1)} KB
              </div>
            )}
            <div className="font-mono text-[11px] text-stone-400 mt-0.5">
              Drafter model: {draft.drafter_model || 'n/a'}
            </div>
          </div>

          {draft.has_cleaned_data && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">
                Cleaned data · {draft.cleaned_data_rows.toLocaleString()} rows
              </div>
              <div className="flex gap-2">
                <a
                  href={artifactDownloadUrl(draft.id, 'cleaned_data.json')}
                  className="text-xs px-3 py-1.5 border border-seam hover:border-ink transition-colors"
                >
                  download .json
                </a>
                <a
                  href={artifactDownloadUrl(draft.id, 'cleaned_data.csv')}
                  className="text-xs px-3 py-1.5 border border-seam hover:border-ink transition-colors"
                >
                  download .csv
                </a>
              </div>
            </div>
          )}

          {draft.warnings?.length > 0 && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">Ingestor warnings</div>
              <ul className="space-y-1 text-xs text-stone-700">
                {draft.warnings.map((w, i) => (
                  <li key={i} className="leading-relaxed">· {w}</li>
                ))}
              </ul>
            </div>
          )}

          {errorFlags.length + warnFlags.length + infoFlags.length > 0 && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">Critic flags</div>
              <ul className="space-y-2 text-xs">
                {[...errorFlags, ...warnFlags, ...infoFlags].map((f, i) => (
                  <li key={i} className="leading-relaxed">
                    <span className={`font-mono-editorial mr-2 ${
                      f.severity === 'error' ? 'text-red-700' :
                      f.severity === 'warn' ? 'text-amber-700' :
                      'text-stone-500'
                    }`}>
                      {f.severity}
                    </span>
                    {f.dim && <span className="text-stone-500">[{f.dim}] </span>}
                    <span className="text-stone-700">{f.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* BOTTOM: duplicate action bar so users find it after scrolling */}
      <div className="p-5 border-t border-seam">
        <ActionBar />
      </div>
    </div>
  )
}

function LabelEditor({
  lbl, onChange, onRemove,
}: {
  lbl: any
  onChange: (patch: Partial<any>) => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-seam bg-paper/40">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className="font-mono-editorial text-stone-400 hover:text-ink text-xs w-4 shrink-0"
          title="Toggle definition"
        >
          {open ? '−' : '+'}
        </button>
        <input
          value={lbl.name || ''}
          onChange={e => onChange({ name: e.target.value })}
          className="px-1 py-0.5 bg-transparent border-0 focus:outline-none focus:bg-white text-xs text-stone-800 flex-1 min-w-0"
          placeholder="label name"
        />
        <button
          onClick={onRemove}
          className="font-mono-editorial text-stone-400 hover:text-red-600 text-xs px-1"
          title="Remove label"
        >
          ×
        </button>
      </div>
      {open && (
        <textarea
          value={lbl.definition || ''}
          onChange={e => onChange({ definition: e.target.value })}
          rows={2}
          className="w-full px-3 py-2 border-t border-seam bg-white text-xs text-stone-700 leading-relaxed focus:outline-none resize-y"
          placeholder="What does this label mean? (definition, edge cases)"
        />
      )}
    </div>
  )
}

