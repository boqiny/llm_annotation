import { Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import ProjectList from './pages/ProjectList'
import ProjectSetup from './pages/ProjectSetup'
import PipelineView from './pages/PipelineView'
import AnnotationMonitor from './pages/AnnotationMonitor'
import ResultsDashboard from './pages/ResultsDashboard'
import CodebookView from './pages/CodebookView'
import PromptLab from './pages/PromptLab'

import PromptLabV2 from './pages/v2/PromptLab'
import ProjectSetupV2 from './pages/v2/ProjectSetup'

import { getUiVersion } from './hooks/useUiVersion'

export default function App() {
  // Resolved once at mount. Toggle reloads the page so new components attach.
  const v = getUiVersion()
  const Setup    = v === 'v2' ? ProjectSetupV2 : ProjectSetup
  const Improve  = v === 'v2' ? PromptLabV2    : PromptLab

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:id/setup" element={<Setup />} />
        <Route path="/projects/:id/codebook" element={<CodebookView />} />
        <Route path="/projects/:id/prompt-lab" element={<Improve />} />
        <Route path="/projects/:id/pipeline" element={<PipelineView />} />
        <Route path="/projects/:id/monitor/:jobId" element={<AnnotationMonitor />} />
        <Route path="/projects/:id/results/:jobId" element={<ResultsDashboard />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
