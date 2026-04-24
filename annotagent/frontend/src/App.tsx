import { Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import ProjectList from './pages/ProjectList'
import ProjectSetup from './pages/ProjectSetup'
import PipelineView from './pages/PipelineView'
import AnnotationMonitor from './pages/AnnotationMonitor'
import ResultsDashboard from './pages/ResultsDashboard'
import CodebookView from './pages/CodebookView'
import PromptLab from './pages/PromptLab'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:id/setup" element={<ProjectSetup />} />
        <Route path="/projects/:id/codebook" element={<CodebookView />} />
        <Route path="/projects/:id/prompt-lab" element={<PromptLab />} />
        <Route path="/projects/:id/pipeline" element={<PipelineView />} />
        <Route path="/projects/:id/monitor/:jobId" element={<AnnotationMonitor />} />
        <Route path="/projects/:id/results/:jobId" element={<ResultsDashboard />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
