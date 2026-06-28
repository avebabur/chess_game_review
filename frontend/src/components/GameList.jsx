import { useState, useEffect, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api'
import {
  saveReanalyzeSession,
  clearReanalyzeSession,
  loadReanalyzeSession,
} from '../reanalyzeSession'

export default function GameList() {
  const location = useLocation()
  const [games, setGames] = useState([])
  const [weaknessSummary, setWeaknessSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [reanalyzeStatus, setReanalyzeStatus] = useState(null)
  const [reanalyzeProgress, setReanalyzeProgress] = useState(null)

  const loadGames = useCallback((signal) => {
    setLoading(true)
    setError(false)
    Promise.all([
      api.get('/games/recent?limit=100', { signal }),
      api.get('/weakness-summary', { signal }),
    ]).then(([gamesRes, weaknessRes]) => {
      setGames(gamesRes.data)
      setWeaknessSummary(weaknessRes.data)
      setLoading(false)
    }).catch((e) => {
      if (
        signal?.aborted
        || e.name === 'CanceledError'
        || e.code === 'ERR_CANCELED'
      ) {
        return
      }
      setError(true)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    const sync = () => {
      const session = loadReanalyzeSession()
      if (session?.scope === 'all') setReanalyzeStatus('running')
    }
    const onProgress = (data) => {
      if (data.status === 'analyzing') {
        const session = loadReanalyzeSession()
        if (!session || session.scope === 'all') {
          setReanalyzeStatus('running')
          setReanalyzeProgress({
            progress: data.game_index ?? data.progress,
            total: data.total_games ?? data.total,
          })
        }
      } else if (data.status === 'complete') {
        setReanalyzeStatus('done')
        setReanalyzeProgress(null)
        loadGames()
      } else if (data.status === 'error') {
        setReanalyzeStatus('error')
        setReanalyzeProgress(null)
      }
    }
    const onProgressEvent = (e) => onProgress(e.detail)

    window.addEventListener('chess-reanalyze-session', sync)
    window.addEventListener('chess-reanalyze-progress', onProgressEvent)
    sync()

    return () => {
      window.removeEventListener('chess-reanalyze-session', sync)
      window.removeEventListener('chess-reanalyze-progress', onProgressEvent)
    }
  }, [loadGames])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => loadGames(controller.signal), 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [location.pathname, loadGames])

  const isReanalyzeRunning = reanalyzeStatus === 'running'

  const handleReanalyzeAll = async () => {
    if (isReanalyzeRunning) return
    if (!window.confirm(
      'Re-analyze all games with the latest engine and coaching templates?\n\n'
      + 'This may take a while. You can leave this page while it runs.',
    )) {
      return
    }
    setReanalyzeStatus('running')
    setReanalyzeProgress({ progress: 0, total: games.length })

    try {
      const res = await api.post('/games/reanalyze-all')
      const { status_id: statusId, total } = res.data
      if (!statusId) {
        setReanalyzeStatus(null)
        return
      }
      saveReanalyzeSession({ statusId, scope: 'all', total })
    } catch {
      clearReanalyzeSession()
      setReanalyzeStatus('error')
    }
  }

  const handleDeleteGame = async (e, gameId, label) => {
    e.preventDefault()
    e.stopPropagation()
    if (!window.confirm(`Delete this game?\n\n${label}\n\nThis removes the review and any puzzles from it.`)) {
      return
    }
    try {
      await api.delete(`/games/${gameId}`)
      setGames(prev => prev.filter(g => g.id !== gameId))
    } catch (err) {
      const status = err.response?.status
      if (status === 405) {
        window.alert('Delete is not supported by the running server. Restart the app (./stop.sh then ./start-native.sh) and try again.')
      } else {
        window.alert('Could not delete the game. Is the server running?')
      }
    }
  }

  if (loading) return (
    <div className="dashboard-skeleton">
      <div className="skeleton skeleton-line short" style={{ height: 28, marginBottom: 24 }} />
      {[1, 2, 3].map(i => <div key={i} className="skeleton skeleton-block" />)}
    </div>
  )

  if (error) return (
    <div className="error-box">
      <p>Couldn't load your games</p>
      <p className="error-hint">Make sure the server is running, then try again</p>
      <button onClick={() => window.location.reload()}>Try Again</button>
    </div>
  )

  if (!games.length) {
    return (
      <div className="game-list-empty">
        <h2>No Games Yet</h2>
        <p>Go to the <Link to="/">Analyze</Link> page to review your first game.</p>
      </div>
    )
  }

  const progressLabel = reanalyzeProgress
    ? `Re-analyzing ${reanalyzeProgress.progress}/${reanalyzeProgress.total}…`
    : 'Re-analyzing…'

  const recentMisses = weaknessSummary?.recent_misses || []

  return (
    <div className="game-list">
      <div className="game-list-header">
        <h1>Your Games</h1>
        <button
          type="button"
          className="reanalyze-all-btn"
          onClick={handleReanalyzeAll}
          disabled={isReanalyzeRunning}
        >
          {isReanalyzeRunning ? progressLabel : 'Re-analyze all games'}
        </button>
      </div>
      {recentMisses.length > 0 && (
        <div className="weakness-summary-card">
          <h2 className="weakness-summary-title">Your patterns (last 30 days)</h2>
          <ul className="weakness-summary-list">
            {recentMisses.map(item => (
              <li key={item.motif} className="weakness-summary-item">
                <div className="weakness-summary-row">
                  <span className="weakness-summary-motif">{item.motif}</span>
                  <span className="weakness-summary-count">
                    missed {item.count}× in {item.games} game{item.games !== 1 ? 's' : ''}
                  </span>
                </div>
                {item.tip && <p className="weakness-summary-tip">{item.tip}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {reanalyzeStatus === 'done' && (
        <p className="reanalyze-hint">All games updated with latest engine analysis.</p>
      )}
      {reanalyzeStatus === 'error' && (
        <p className="reanalyze-hint error">Re-analyze failed. Check the server is running.</p>
      )}
      <div className="games-table">
        {games.map(g => (
          <div key={g.id} className="game-row">
            <Link to={`/review/${g.id}`} className="game-row-link">
              <div className="game-row-main">
                <span className="game-players">{g.white} vs {g.black}</span>
                <span className={`game-result-badge ${g.result === '1-0' ? 'win' : g.result === '0-1' ? 'loss' : 'draw'}`}>
                  {g.result}
                </span>
              </div>
              <div className="game-row-meta">
                {g.opening && <span className="game-opening">{g.opening}</span>}
                {g.white_accuracy != null && (
                  <span className="game-accuracy">{g.white_accuracy}% / {g.black_accuracy}%</span>
                )}
                <span className="game-date">{g.date}</span>
              </div>
            </Link>
            <button
              type="button"
              className="game-delete-btn"
              title="Delete game"
              aria-label={`Delete ${g.white} vs ${g.black}`}
              onClick={(e) => handleDeleteGame(e, g.id, `${g.white} vs ${g.black}`)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
