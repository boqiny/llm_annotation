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
      <section className="max-w-3xl">
        <div className="font-mono-editorial text-stone-500 mb-5">
          Annotation workbench · for messy multi-label tasks
        </div>
        <h1 className="text-5xl sm:text-6xl font-medium tracking-tight leading-[1.05]">
          Label text the way<br />
          <span className="italic font-display font-normal">you'd label it</span> —
          using an LLM.
        </h1>
        <p className="mt-8 text-lg leading-relaxed text-stone-600">
          Bring a codebook (your label definitions) and AnnotAgent walks you through four steps:
          define what to label, let the system draft a starting prompt for each dimension,
          improve it with a few labeled examples, then annotate your data. No prompt engineering
          required.
        </p>
      </section>

      {/* How it works — 4-step workflow with figure slot */}
      <section className="border-t border-seam pt-10">
        <div className="font-mono-editorial text-stone-500 mb-3">How it works</div>
        <h2 className="text-3xl font-medium tracking-tight mb-8">From codebook to annotated data in four steps</h2>

        {/* Workflow figure — transparent PNG sits flush on the page background.
            Source: annotagent/assets/workflow_transparent.png. No wrapper fill
            so the cream page tone shows through any transparent areas. */}
        <figure className="mb-12">
          <img
            src="/workflow_0517.png"
            alt="AnnotAgent workflow: Define codebook → Auto-draft prompts → Improve from examples → Annotate dataset"
            className="w-2/3 h-auto mx-auto block"
            onError={(e) => { (e.currentTarget.style.display = 'none') }}
          />
        </figure>

      </section>

      {/* Projects band */}
      <section>
        <div className="flex items-end justify-between pb-4 mb-4">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">
              Total projects: {projects.length}
            </div>
            <h2 className="text-3xl font-medium tracking-tight">Your projects</h2>
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
                  placeholder="My annotation project"
                />
              </div>
              <div>
                <label className="block font-mono-editorial text-stone-500 mb-2">Description · optional</label>
                <input
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-base"
                  placeholder="What are you annotating, and why?"
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
            {projects.map(p => (
              <ProjectRow
                key={p.id}
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

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <li className="grid grid-cols-12 gap-4 list-none">
      <div className="col-span-2 font-mono-editorial text-stone-400 pt-1">{n}</div>
      <div className="col-span-10">
        <h3 className="text-xl font-medium tracking-tight mb-1.5">{title}</h3>
        <p className="text-sm text-stone-600 leading-relaxed">{body}</p>
      </div>
    </li>
  )
}

function formatDate(value: string | null) {
  if (!value) return '—'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }) + ' UTC'
}

function ProjectRow({
  project, onOpen, onDelete,
}: {
  project: Project
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
          {project.id.toString().padStart(3, '0')}
        </div>
        <div className="col-span-4">
          <div className="flex items-baseline gap-3">
            <h3 className="text-xl font-medium tracking-tight">{project.name}</h3>
            <span className={`font-mono-editorial ${statusTone}`}>· {project.status}</span>
          </div>
          {project.description && (
            <p className="mt-1 text-sm text-stone-600 leading-relaxed">{project.description}</p>
          )}
        </div>
        <div className="col-span-3 pt-1">
          <div className="font-mono-editorial text-stone-500 mb-1">Created</div>
          <div className="font-mono text-xs text-stone-700">
            {formatDate(project.created_at)}
          </div>
        </div>
        <div className="col-span-2 pt-1">
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
    <div className="border border-dashed border-seam py-20 text-center bg-paper/40">
      <div className="font-mono-editorial text-stone-500 mb-3">No projects yet</div>
      <p className="text-stone-600 max-w-md mx-auto mb-6">
        Start by creating a project — pick a preset codebook or upload your own.
      </p>
      <button onClick={onCreate} className="px-5 py-2.5 bg-ink text-cream text-sm font-medium">
        Create your first project →
      </button>
    </div>
  )
}
