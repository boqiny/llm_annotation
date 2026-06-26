import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { TourProvider } from './components/tour/TourProvider'
import { APP_NAME } from './lib/brand'
import './index.css'

document.title = APP_NAME

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <TourProvider>
        <App />
      </TourProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
