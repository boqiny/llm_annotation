import { Routes, Route, Navigate, useParams } from 'react-router-dom'
import { Fragment, type ReactNode } from 'react'
import AppLayout from './components/layout/AppLayout'
import ProjectList from './pages/ProjectList'
import ProjectSetup from './pages/ProjectSetup'
import PipelineView from './pages/PipelineView'
import AnnotationMonitor from './pages/AnnotationMonitor'
import ResultsDashboard from './pages/ResultsDashboard'
import CodebookView from './pages/CodebookView'
import PromptLab from './pages/PromptLab'

/* Remount a project-scoped page whenever the project (or job) in the URL changes.
 * React reuses the same component instance across param-only navigations, so
 * without this a page would keep the previous project's in-memory state (prompts,
 * codebooks, pipelines, caches) — leaking content between projects. Keying on the
 * route params forces a clean remount, keeping every project fully independent. */
function Keyed({ children }: { children: ReactNode }) {
  const { id, jobId } = useParams<{ id: string; jobId: string }>()
  return <Fragment key={`${id ?? ''}:${jobId ?? ''}`}>{children}</Fragment>
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:id/setup" element={<Keyed><ProjectSetup /></Keyed>} />
        <Route path="/projects/:id/codebook" element={<Keyed><CodebookView /></Keyed>} />
        <Route path="/projects/:id/prompt-lab" element={<Keyed><PromptLab /></Keyed>} />
        <Route path="/projects/:id/pipeline" element={<Keyed><PipelineView /></Keyed>} />
        <Route path="/projects/:id/monitor/:jobId" element={<Keyed><AnnotationMonitor /></Keyed>} />
        <Route path="/projects/:id/results/:jobId" element={<Keyed><ResultsDashboard /></Keyed>} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
