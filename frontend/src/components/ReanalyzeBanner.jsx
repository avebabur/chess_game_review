import { useState, useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  loadReanalyzeSession,
  ensureReanalyzePolling,
  stopPolling,
  formatReanalyzeLabel,
} from '../reanalyzeSession'

export default function ReanalyzeBanner() {
  const location = useLocation()
  const [session, setSession] = useState(() => loadReanalyzeSession())
  const [progress, setProgress] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    const syncSession = () => setSession(loadReanalyzeSession())
    const onProgress = (e) => setProgress(e.detail)

    const kick = () => {
      syncSession()
      ensureReanalyzePolling(pollRef)
    }

    window.addEventListener('chess-reanalyze-session', kick)
    window.addEventListener('chess-reanalyze-progress', onProgress)
    kick()

    return () => {
      stopPolling(pollRef)
      window.removeEventListener('chess-reanalyze-session', kick)
      window.removeEventListener('chess-reanalyze-progress', onProgress)
    }
  }, [])

  const analyzing = progress?.status === 'analyzing'
  const pending = session && !progress
  const running = analyzing || pending
  const justFinished = !session && progress?.status === 'complete'

  if (justFinished) {
    return (
      <div className="reanalyze-banner reanalyze-banner-done">
        Re-analysis finished — refresh or reopen the game to see updated explanations.
      </div>
    )
  }

  if (!running) return null

  const label = formatReanalyzeLabel(session, progress) || 'Re-analyzing…'
  const onThisGame = session?.scope === 'one'
    && session.gameId
    && location.pathname === `/review/${session.gameId}`

  return (
    <div className="reanalyze-banner">
      <span className="reanalyze-banner-spinner" aria-hidden />
      <span>{label}</span>
      <span className="reanalyze-banner-hint">
        {onThisGame
          ? 'Progress updates below — you can stay on this page.'
          : 'Safe to switch pages — work continues on the server.'}
      </span>
      {session?.scope === 'one' && session.gameId && !onThisGame && (
        <Link to={`/review/${session.gameId}`} className="reanalyze-banner-link">
          Open game
        </Link>
      )}
      {session?.scope === 'all' && (
        <Link to="/games" className="reanalyze-banner-link">Games</Link>
      )}
    </div>
  )
}
