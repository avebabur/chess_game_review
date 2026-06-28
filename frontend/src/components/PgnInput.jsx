import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Chess } from 'chess.js'
import { api } from '../api'

function validatePgn(text) {
  if (!text.trim()) return null
  try {
    const chess = new Chess()
    chess.loadPgn(text)
    const moves = chess.history()
    if (moves.length === 0) return { valid: false, error: 'No moves found in PGN' }
    const headers = chess.header()
    return {
      valid: true,
      moves: moves.length,
      white: headers.White || 'Unknown',
      black: headers.Black || 'Unknown',
    }
  } catch {
    return { valid: false, error: 'Invalid PGN format' }
  }
}

export default function PgnInput() {
  const [pgn, setPgn] = useState('')
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(null)
  const [progressDetail, setProgressDetail] = useState(null)
  const [recentGames, setRecentGames] = useState([])
  const navigate = useNavigate()
  const pollRef = useRef(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const pgnValidation = useMemo(() => validatePgn(pgn), [pgn])

  useEffect(() => {
    const controller = new AbortController()
    api.get('/games/recent?limit=5', { signal: controller.signal })
      .then(res => setRecentGames(res.data))
      .catch(() => {})
    return () => controller.abort()
  }, [])

  const handleAnalyze = async () => {
    if (!pgn.trim()) return
    setStatus('submitting')

    try {
      const res = await api.post('/analyze', { pgn })
      const statusId = res.data.status_id
      setStatus('analyzing')

      pollRef.current = setInterval(async () => {
        try {
          const s = await api.get(`/analyze/status/${statusId}`)
          const d = s.data
          if (d.status === 'complete') {
            clearInterval(pollRef.current)
            pollRef.current = null
            navigate(`/review/${d.game_id}`)
          } else if (d.status === 'error' || d.status === 'interrupted') {
            clearInterval(pollRef.current)
            pollRef.current = null
            setStatus('error')
            setProgress(
              d.error || 'Analysis interrupted (server restarted). Please analyze again.',
            )
            setProgressDetail(null)
          } else if (d.status === 'analyzing') {
            setProgressDetail({
              phase: d.phase || 'stockfish',
              progress: d.progress ?? 0,
              total: d.total ?? 0,
              moveCount: d.move_count ?? 0,
            })
            if (d.phase === 'coaching' || d.phase === 'explanations') {
              setProgress(`Building coaching notes ${d.progress} of ${d.total}…`)
            } else if (d.total > 0) {
              setProgress(`Stockfish: move ${d.progress} of ${d.total}`)
            } else {
              setProgress('Starting analysis…')
            }
          }
        } catch (err) {
          clearInterval(pollRef.current)
          pollRef.current = null
          setStatus('error')
          if (err.response?.status === 404) {
            setProgress('Analysis interrupted (server restarted). Please analyze again.')
          } else {
            setProgress(err.response?.data?.detail || 'Analysis could not complete')
          }
        }
      }, 1200)
    } catch (e) {
      setStatus('error')
      setProgress(e.response?.data?.detail || e.message)
    }
  }

  return (
    <div className="pgn-input-page">
      <h1>Analyze Your Game</h1>
      <p className="subtitle">Paste a PGN to see where you went wrong and what you missed</p>

      <textarea
        className="pgn-textarea"
        value={pgn}
        onChange={e => setPgn(e.target.value)}
        placeholder={`[Event "Live Chess"]\n[Site "Chess.com"]\n...\n\n1. e4 e5 2. Nf3 Nc6 ...`}
        rows={16}
      />

      {pgnValidation && (
        <div className={`pgn-validation ${pgnValidation.valid ? 'valid' : 'invalid'}`}>
          {pgnValidation.valid
            ? `${pgnValidation.white} vs ${pgnValidation.black} · ${pgnValidation.moves} moves`
            : pgnValidation.error
          }
        </div>
      )}

      <button
        className="analyze-btn"
        onClick={handleAnalyze}
        disabled={status === 'analyzing' || status === 'submitting' || !pgnValidation?.valid}
      >
        {status === 'analyzing' ? 'Analyzing...' : 'Analyze Game'}
      </button>

      {status === 'analyzing' && (
        <div className="progress-box">
          <div className="spinner" />
          <p>{progress || 'Starting analysis...'}</p>
          {progressDetail && progressDetail.total > 0 && (
            <>
              <div className="progress-bar-track">
                <div
                  className="progress-bar-fill"
                  style={{
                    width: `${(progressDetail.phase === 'coaching' || progressDetail.phase === 'explanations')
                      ? 85 + Math.round((progressDetail.progress / progressDetail.total) * 15)
                      : Math.round((progressDetail.progress / progressDetail.total) * 85)}%`,
                  }}
                />
              </div>
              <p className="progress-percent">
                {(progressDetail.phase === 'coaching' || progressDetail.phase === 'explanations')
                  ? `${85 + Math.round((progressDetail.progress / progressDetail.total) * 15)}%`
                  : `${Math.round((progressDetail.progress / progressDetail.total) * 85)}%`}
                {progressDetail.moveCount > 0 && progressDetail.phase === 'stockfish'
                  ? ` · ${progressDetail.moveCount} moves in game`
                  : ''}
              </p>
            </>
          )}
          <p className="progress-hint">Stockfish pass, then coaching notes for critical moments</p>
        </div>
      )}

      {status === 'error' && (
        <div className="error-box">
          <p>Analysis could not complete</p>
          <p className="error-hint">{progress || 'Make sure the server is running, then try again'}</p>
          <button onClick={() => { setStatus(null); setProgress(null) }}>Try Again</button>
        </div>
      )}

      {recentGames.length > 0 && (
        <div className="recent-games">
          <h3>Recent Analyses</h3>
          <div className="recent-games-list">
            {recentGames.map(game => (
              <Link key={game.id} to={`/review/${game.id}`} className="recent-game-card">
                <div className="recent-game-players">
                  <span className="recent-game-white">{game.white}</span>
                  <span className="recent-game-vs">vs</span>
                  <span className="recent-game-black">{game.black}</span>
                  <span className={`recent-game-result ${game.result === '1-0' ? 'win' : game.result === '0-1' ? 'loss' : 'draw'}`}>
                    {game.result}
                  </span>
                </div>
                <div className="recent-game-meta">
                  {game.opening && <span className="recent-game-opening">{game.opening}</span>}
                  {game.white_accuracy != null && (
                    <span className="recent-game-accuracy">
                      {game.white_accuracy}% / {game.black_accuracy}%
                    </span>
                  )}
                  {game.date && <span className="recent-game-date">{game.date}</span>}
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
