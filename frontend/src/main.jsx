import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/tokens.css'
import ReviewApp from './apps/review/ReviewApp.jsx'
import { preloadSounds } from './sounds'

preloadSounds()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ReviewApp />
  </StrictMode>,
)
