import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, createProject, deleteProject } from '../lib/api'
import type { Project } from '../types'

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const navigate = useNavigate()

  useEffect(() => { listProjects().then(setProjects) }, [])

  const handleCreate = async () => {
    if (!name.trim()) return
    const project = await createProject({ name, description })
    setProjects([project, ...projects])
    setShowCreate(false); setName(''); setDescription('')
    navigate(`/projects/${project.id}/setup`)
  }

  const handleDelete = async (id: number) => {
    await deleteProject(id)
    setProjects(projects.filter(p => p.id !== id))
  }

  return (
    <div className="space-y-16">
      {/* Hero */}
      <section className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-end">
        <div className="lg:col-span-8">
          <div className="font-mono-editorial text-stone-500 mb-5">
            Workbench · for subtle multi-dimensional annotation
          </div>
          <h1 className="text-5xl sm:text-6xl md:text-7xl font-medium tracking-tight leading-[1.05]">
            Turn adjudicated<br />
            <span className="italic font-display font-normal">annotator insight</span><br />
            into a calibrated LLM.
          </h1>
          <p className="mt-8 max-w-xl text-lg leading-relaxed text-stone-600">
            AnnotAgent distills the decisions two human annotators already made —
            codebook, gold subset, disagreement patterns — into an editable rule
            library that drives LLM annotation with before / after metrics.
          </p>
        </div>

        <div className="lg:col-span-4 lg:pl-6 lg:border-l border-seam">
          <div className="font-mono-editorial text-stone-500 mb-3">The dataset</div>
          <dl className="space-y-3 text-sm">
            <StatRow label="Self-disclosure" value="169 agreed" />
            <StatRow label="AI behavior" value="123 dual-annotated" />
            <StatRow label="Dimensions" value="5 single + 3 multi-label" />
            <StatRow label="Topic IAA" value="24.6% raw" muted />
            <StatRow label="Level IAA" value="68.6% raw" muted />
          </dl>
        </div>
      </section>

      {/* Projects band */}
      <section>
        <div className="flex items-end justify-between border-b border-seam pb-4 mb-8">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">
              № {projects.length.toString().padStart(2, '0')} · projects
            </div>
            <h2 className="text-3xl font-medium tracking-tight">All annotation projects</h2>
          </div>
          <button
            onClick={() => setShowCreate(v => !v)}
            className="group inline-flex items-center gap-2 px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors"
          >
            <span className="font-mono text-xs">+</span>
            <span>New project</span>
          </button>
        </div>

        {showCreate && (
          <div className="mb-8 border border-seam bg-white p-6">
            <div className="font-mono-editorial text-stone-500 mb-4">Create a new project</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className="block font-mono-editorial text-stone-500 mb-2">Name</label>
                <input
                  autoFocus
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-base font-medium"
                  placeholder="Self-disclosure · pilot"
                />
              </div>
              <div>
                <label className="block font-mono-editorial text-stone-500 mb-2">Description · optional</label>
                <input
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-base"
                  placeholder="e.g. 2-annotator pilot for calibration loop"
                />
              </div>
            </div>
            <div className="flex items-center gap-3 mt-6">
              <button
                onClick={handleCreate}
                disabled={!name.trim()}
                className="px-5 py-2 bg-ink text-cream text-sm font-medium disabled:opacity-40"
              >
                Create & go to Setup →
              </button>
              <button onClick={() => setShowCreate(false)} className="text-sm text-stone-500 hover:text-ink">
                Cancel
              </button>
            </div>
          </div>
        )}

        {projects.length === 0 ? (
          <EmptyState onCreate={() => setShowCreate(true)} />
        ) : (
          <ul className="divide-y divide-seam border-y border-seam">
            {projects.map((p, i) => (
              <ProjectRow
                key={p.id}
                index={i}
                project={p}
                onOpen={() => navigate(`/projects/${p.id}/setup`)}
                onDelete={() => handleDelete(p.id)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function StatRow({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 pb-2 border-b border-dotted border-seam">
      <dt className="font-mono-editorial text-stone-500">{label}</dt>
      <dd className={`font-mono text-sm ${muted ? 'text-stone-500' : 'text-ink font-medium'}`}>{value}</dd>
    </div>
  )
}

function ProjectRow({
  project, index, onOpen, onDelete,
}: {
  project: Project
  index: number
  onOpen: () => void
  onDelete: () => void
}) {
  const statusTone =
    project.status === 'completed' ? 'text-emerald-700' :
    project.status === 'running' ? 'text-blue-700' :
    'text-stone-500'

  return (
    <li className="group">
      <div
        onClick={onOpen}
        className="grid grid-cols-12 gap-6 py-6 px-2 cursor-pointer hover:bg-paper/60 transition-colors"
      >
        <div className="col-span-1 font-mono-editorial text-stone-400 pt-1">
          {(index + 1).toString().padStart(2, '0')}
        </div>
        <div className="col-span-6">
          <div className="flex items-baseline gap-3">
            <h3 className="text-xl font-medium tracking-tight">{project.name}</h3>
            <span className={`font-mono-editorial ${statusTone}`}>· {project.status}</span>
          </div>
          {project.description && (
            <p className="mt-1 text-sm text-stone-600 leading-relaxed">{project.description}</p>
          )}
        </div>
        <div className="col-span-3 pt-1">
          <div className="font-mono-editorial text-stone-500 mb-1">Model</div>
          <div className="font-mono text-xs text-stone-700 truncate">{project.llm_provider} / {project.llm_model}</div>
        </div>
        <div className="col-span-2 flex items-center justify-end gap-4 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={e => { e.stopPropagation(); onDelete() }}
            className="font-mono-editorial text-stone-400 hover:text-red-600"
          >
            Delete
          </button>
          <span className="text-stone-400 group-hover:text-ink transition-colors">→</span>
        </div>
      </div>
    </li>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="border border-dashed border-seam py-24 text-center bg-paper/40">
      <div className="font-mono-editorial text-stone-500 mb-3">No projects yet</div>
      <p className="text-stone-600 max-w-md mx-auto mb-6">
        Create a project to load the self-disclosure codebook and the agreed-subset
        ground truth.
      </p>
      <button onClick={onCreate} className="px-5 py-2.5 bg-ink text-cream text-sm font-medium">
        Start the first project →
      </button>
    </div>
  )
}
