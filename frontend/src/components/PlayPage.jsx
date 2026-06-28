import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import { api } from '../api'
import { boardSquareStyles, customPieces, BOARD_ANIMATION_MS } from '../boardTheme'
import { useBoardSize } from '../useBoardSize'
import { classificationLabel, formatEval } from '../reviewUtils'
import { playStepSound, playIllegalSound } from '../sounds'
import BoardCoordinates, { BoardFileStrip } from './BoardCoordinates'
import PromotionDialog from './PromotionDialog'
import ExplanationBlocks from './ExplanationBlocks'
import EvalBar from './EvalBar'
import MoveNotation from './MoveNotation'

const LEVELS = [800, 1000, 1100, 1200, 1400, 1600, 1800, 2000]

function buildPgn(sans, userColor, opponentName, result) {
  const today = new Date()
  const date = `${today.getFullYear()}.${String(today.getMonth() + 1).padStart(2, '0')}.${String(today.getDate()).padStart(2, '0')}`
  const headers = [
    '[Event "Training Game"]',
    '[Site "Chess Review"]',
    `[Date "${date}"]`,
    `[White "${userColor === 'white' ? 'You' : opponentName}"]`,
    `[Black "${userColor === 'black' ? 'You' : opponentName}"]`,
    `[Result "${result}"]`,
  ]
  const body = []
  for (let i = 0; i < sans.length; i += 2) {
    const num = Math.floor(i / 2) + 1
    body.push(`${num}. ${sans[i]}${sans[i + 1] ? ` ${sans[i + 1]}` : ''}`)
  }
  return `${headers.join('\n')}\n\n${body.join(' ')} ${result}`
}

function resultString(gameState, userColor, resigned) {
  if (resigned) return userColor === 'white' ? '0-1' : '1-0'
  if (!gameState?.over) return '*'
  if (gameState.result === 'checkmate') {
    return gameState.winner === 'White' ? '1-0' : '0-1'
  }
  return '1/2-1/2'
}

export default function PlayPage() {
  // setup | playing
  const [phase, setPhase] = useState('setup')
  const [userColor, setUserColor] = useState(() => localStorage.getItem('play_color') || 'white')
  const [opponent, setOpponent] = useState(() => localStorage.getItem('play_opp') || 'maia')
  const [level, setLevel] = useState(() => Number(localStorage.getItem('play_level')) || 1100)

  const [sans, setSans] = useState([])
  const [coach, setCoach] = useState(null)         // latest coach payload (your last move)
  const [coachLoading, setCoachLoading] = useState(false)
  const [oppThinking, setOppThinking] = useState(false)
  const [verdicts, setVerdicts] = useState({})     // half-move index -> classification
  const [gameOver, setGameOver] = useState(null)   // {result, winner} | {resigned}
  const [evalScore, setEvalScore] = useState(0.2)
  const [pendingPromotion, setPendingPromotion] = useState(null)
  const [selectedSquare, setSelectedSquare] = useState(null)
  const [analyzeStatus, setAnalyzeStatus] = useState(null)
  const [error, setError] = useState('')

  const boardSize = useBoardSize()
  const navigate = useNavigate()
  const coachAbort = useRef(null)
  const oppTimer = useRef(null)
  const pollRef = useRef(null)
  const sansRef = useRef([])
  useEffect(() => { sansRef.current = sans }, [sans])

  const fen = useMemo(() => {
    const chess = new Chess()
    for (const san of sans) {
      try { chess.move(san) } catch { break }
    }
    return chess.fen()
  }, [sans])

  const chessNow = useMemo(() => new Chess(fen), [fen])
  const userTurn = phase === 'playing' && !gameOver
    && ((chessNow.turn() === 'w') === (userColor === 'white'))

  useEffect(() => { localStorage.setItem('play_color', userColor) }, [userColor])
  useEffect(() => { localStorage.setItem('play_opp', opponent) }, [opponent])
  useEffect(() => { localStorage.setItem('play_level', String(level)) }, [level])

  useEffect(() => () => {
    coachAbort.current?.abort()
    window.clearTimeout(oppTimer.current)
    if (pollRef.current) window.clearInterval(pollRef.current)
  }, [])

  const opponentName = `${opponent === 'maia' ? 'Maia' : 'Stockfish'} ${level}`

  const checkGameOver = useCallback((chess) => {
    if (chess.isCheckmate()) {
      return { over: true, result: 'checkmate', winner: chess.turn() === 'w' ? 'Black' : 'White' }
    }
    if (chess.isStalemate()) return { over: true, result: 'stalemate', winner: null }
    if (chess.isInsufficientMaterial()) return { over: true, result: 'insufficient material', winner: null }
    if (chess.isThreefoldRepetition()) return { over: true, result: 'threefold repetition', winner: null }
    if (chess.isDraw()) return { over: true, result: 'draw', winner: null }
    return null
  }, [])

  const requestOpponentMove = useCallback(async (fenForOpp) => {
    setOppThinking(true)
    try {
      const res = await api.post('/play/engine-move', {
        fen: fenForOpp, opponent, level,
      })
      const san = res.data.san
      // Small delay so the reply feels played, not teleported.
      oppTimer.current = window.setTimeout(() => {
        // Ignore stale replies after takeback / new game.
        const chess = new Chess()
        for (const s of sansRef.current) {
          try { chess.move(s) } catch { return }
        }
        if (chess.fen() !== fenForOpp) return
        let move
        try { move = chess.move(san) } catch { setOppThinking(false); return }
        if (!move) { setOppThinking(false); return }
        playStepSound(move.san)
        setSans(prev => [...prev, move.san])
        setOppThinking(false)
        const end = checkGameOver(chess)
        if (end) setGameOver(end)
      }, 550)
    } catch {
      setOppThinking(false)
      setError('The opponent engine is not responding — try again or start a new game.')
    }
  }, [opponent, level, checkGameOver])

  const requestCoach = useCallback(async (fenBefore, san, context, halfIndex) => {
    coachAbort.current?.abort()
    const controller = new AbortController()
    coachAbort.current = controller
    setCoachLoading(true)
    try {
      const res = await api.post('/play/coach', {
        fen: fenBefore, move: san, elo: level, context_moves: context,
      }, { signal: controller.signal })
      if (controller.signal.aborted) return
      setCoach(res.data)
      setEvalScore(res.data.eval_after ?? 0)
      setVerdicts(v => ({ ...v, [halfIndex]: res.data.classification }))
    } catch (e) {
      if (controller.signal.aborted || e.code === 'ERR_CANCELED') return
      setCoach(null)
    }
    if (!controller.signal.aborted) setCoachLoading(false)
  }, [level])

  const startGame = (color) => {
    coachAbort.current?.abort()
    window.clearTimeout(oppTimer.current)
    const finalColor = color === 'random' ? (Math.random() < 0.5 ? 'white' : 'black') : color
    setUserColor(finalColor)
    setSans([])
    setCoach(null)
    setVerdicts({})
    setGameOver(null)
    setEvalScore(0.2)
    setError('')
    setAnalyzeStatus(null)
    setPhase('playing')
    if (finalColor === 'black') {
      requestOpponentMove(new Chess().fen())
    }
  }

  const completeMove = (from, to, promotion = 'q') => {
    if (!userTurn || oppThinking) return false
    const chess = new Chess(fen)
    let move
    try { move = chess.move({ from, to, promotion }) } catch { return false }
    if (!move) return false

    playStepSound(move.san)
    setSelectedSquare(null)
    setPendingPromotion(null)
    const context = sans.slice(-4).join(' ')
    const fenBefore = fen
    const halfIndex = sans.length
    setSans(prev => [...prev, move.san])

    // Game-over needs full move history (repetition); replay from the start.
    const full = new Chess()
    for (const s of [...sans, move.san]) {
      try { full.move(s) } catch { break }
    }
    const end = checkGameOver(full)
    if (end) {
      setGameOver(end)
    } else {
      requestOpponentMove(chess.fen())
    }
    requestCoach(fenBefore, move.san, context, halfIndex)
    return true
  }

  const needsPromotion = (from, to) => {
    const piece = chessNow.get(from)
    if (!piece || piece.type !== 'p') return false
    const rank = to[1]
    return (piece.color === 'w' && rank === '8') || (piece.color === 'b' && rank === '1')
  }

  const tryMove = (from, to) => {
    if (!userTurn || oppThinking) return false
    if (needsPromotion(from, to)) {
      const piece = chessNow.get(from)
      const probe = new Chess(fen)
      let legal
      try { legal = probe.move({ from, to, promotion: 'q' }) } catch { legal = null }
      if (!legal) return false
      setPendingPromotion({ from, to, color: piece.color })
      setSelectedSquare(null)
      return false
    }
    return completeMove(from, to, 'q')
  }

  const legalTargets = useMemo(() => {
    if (!selectedSquare) return []
    try {
      return chessNow.moves({ square: selectedSquare, verbose: true }).map(m => m.to)
    } catch {
      return []
    }
  }, [selectedSquare, chessNow])

  const handleSquareClick = (square) => {
    if (!userTurn || pendingPromotion) return
    if (selectedSquare && legalTargets.includes(square)) {
      tryMove(selectedSquare, square)
      return
    }
    const piece = chessNow.get(square)
    if (piece && piece.color === chessNow.turn()) {
      setSelectedSquare(square === selectedSquare ? null : square)
    } else {
      setSelectedSquare(null)
      if (selectedSquare) playIllegalSound()
    }
  }

  const squareStyles = useMemo(() => {
    const styles = {}
    if (selectedSquare) {
      styles[selectedSquare] = { backgroundColor: 'rgba(255, 255, 0, 0.4)' }
      for (const to of legalTargets) {
        styles[to] = chessNow.get(to)
          ? { background: 'radial-gradient(transparent 51%, rgba(0,0,0,0.3) 51%)', borderRadius: '50%' }
          : { background: 'radial-gradient(rgba(0,0,0,0.25) 19%, transparent 20%)', cursor: 'pointer' }
      }
    }
    return styles
  }, [selectedSquare, legalTargets, chessNow])

  const takeback = () => {
    if (!sans.length) return
    coachAbort.current?.abort()
    window.clearTimeout(oppTimer.current)
    setCoachLoading(false)
    setOppThinking(false)
    setGameOver(null)
    // Remove moves until it's the user's turn again (opponent reply + yours).
    const userIsWhite = userColor === 'white'
    let cut = sans.length
    do { cut -= 1 } while (cut > 0 && ((cut % 2 === 0) !== userIsWhite))
    const kept = sans.slice(0, cut)
    setSans(kept)
    setCoach(null)
    setVerdicts(v => {
      const next = {}
      for (const [k, val] of Object.entries(v)) {
        if (Number(k) < cut) next[k] = val
      }
      return next
    })
    // Playing Black and cutting to the start: White (the engine) must move.
    if ((cut % 2 === 0) !== userIsWhite) {
      const chess = new Chess()
      for (const s of kept) {
        try { chess.move(s) } catch { return }
      }
      requestOpponentMove(chess.fen())
    }
  }

  const resign = () => {
    if (gameOver) return
    setGameOver({ over: true, result: 'resignation', winner: userColor === 'white' ? 'Black' : 'White', resigned: true })
  }

  const analyzeGame = async () => {
    if (!sans.length || analyzeStatus === 'running') return
    setAnalyzeStatus('running')
    const result = resultString(
      gameOver?.resigned ? null : gameOver, userColor, Boolean(gameOver?.resigned),
    )
    const pgn = buildPgn(sans, userColor, opponentName, result)
    try {
      const res = await api.post('/analyze', { pgn })
      const statusId = res.data.status_id
      pollRef.current = window.setInterval(async () => {
        try {
          const s = await api.get(`/analyze/status/${statusId}`)
          if (s.data.status === 'complete') {
            window.clearInterval(pollRef.current)
            navigate(`/review/${s.data.game_id}`)
          } else if (s.data.status === 'error' || s.data.status === 'interrupted') {
            window.clearInterval(pollRef.current)
            setAnalyzeStatus('error')
          }
        } catch {
          window.clearInterval(pollRef.current)
          setAnalyzeStatus('error')
        }
      }, 1200)
    } catch {
      setAnalyzeStatus('error')
    }
  }

  const orientation = userColor
  const lastVerdict = coach?.classification
  const moment = coach?.moment

  if (phase === 'setup') {
    return (
      <div className="play-setup">
        <h2>Training Game</h2>
        <p className="play-setup-sub">
          Play with a coach at your side — every move you make gets explained,
          and the finished game can go straight into review.
        </p>

        <div className="play-setup-grid">
          <div className="play-setup-block">
            <h3>Opponent</h3>
            <label className={`play-opt ${opponent === 'maia' ? 'active' : ''}`}>
              <input
                type="radio"
                name="opp"
                checked={opponent === 'maia'}
                onChange={() => setOpponent('maia')}
              />
              <div>
                <strong>Maia (human-like)</strong>
                <span>A neural net trained on real games at your level — makes human mistakes, not engine-weird ones.</span>
              </div>
            </label>
            <label className={`play-opt ${opponent === 'stockfish' ? 'active' : ''}`}>
              <input
                type="radio"
                name="opp"
                checked={opponent === 'stockfish'}
                onChange={() => setOpponent('stockfish')}
              />
              <div>
                <strong>Stockfish (skill-limited)</strong>
                <span>The engine dialed down — steadier, punishes tactics more reliably.</span>
              </div>
            </label>
          </div>

          <div className="play-setup-block">
            <h3>Strength</h3>
            <div className="play-levels">
              {LEVELS.map(v => (
                <button
                  key={v}
                  type="button"
                  className={`play-level-btn ${level === v ? 'active' : ''}`}
                  onClick={() => setLevel(v)}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>

          <div className="play-setup-block">
            <h3>Your color</h3>
            <div className="play-colors">
              <button type="button" className="play-color-btn" onClick={() => startGame('white')}>
                Play White
              </button>
              <button type="button" className="play-color-btn" onClick={() => startGame('random')}>
                Random
              </button>
              <button type="button" className="play-color-btn" onClick={() => startGame('black')}>
                Play Black
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="play-page">
      <div className="play-header">
        <h2>You vs {opponentName}</h2>
        <div className="play-header-actions">
          <button type="button" onClick={takeback} disabled={!sans.length || Boolean(gameOver?.resigned)}>
            ⌫ Takeback
          </button>
          <button type="button" onClick={resign} disabled={Boolean(gameOver)}>
            Resign
          </button>
          <button type="button" onClick={() => setPhase('setup')}>
            New game
          </button>
        </div>
      </div>

      {error && <p className="play-error">{error}</p>}

      <div className="play-layout">
        <div className="play-board-row">
          <div className="eval-bar-column">
            <EvalBar eval={evalScore} flipped={userColor === 'black'} height={boardSize} />
          </div>

          <div className="board-area" style={{ width: boardSize }}>
          <div className="player-bar top">
            <span className="player-name">{opponentName}</span>
            {oppThinking && <span className="play-thinking">thinking…</span>}
          </div>
          <div className="board-frame">
            <div className="board-wrapper" style={{ width: boardSize, height: boardSize }}>
              <div className="board-layer-pieces">
                <Chessboard
                  id="play-board"
                  position={fen}
                  boardWidth={boardSize}
                  boardOrientation={orientation}
                  arePiecesDraggable={userTurn && !pendingPromotion}
                  onPieceDrop={(from, to) => tryMove(from, to)}
                  onSquareClick={handleSquareClick}
                  animationDuration={BOARD_ANIMATION_MS}
                  customSquareStyles={squareStyles}
                  customPieces={customPieces}
                  {...boardSquareStyles}
                />
              </div>
              {pendingPromotion && (
                <PromotionDialog
                  color={pendingPromotion.color}
                  onSelect={(piece) => completeMove(pendingPromotion.from, pendingPromotion.to, piece)}
                  onCancel={() => setPendingPromotion(null)}
                />
              )}
              <BoardCoordinates boardSize={boardSize} orientation={orientation} />
            </div>
            <BoardFileStrip boardSize={boardSize} orientation={orientation} />
          </div>
          <div className="player-bar bottom">
            <span className="player-name">You</span>
            {gameOver && (
              <span className="play-result">
                {gameOver.result}
                {gameOver.winner ? ` — ${gameOver.winner} wins` : ''}
              </span>
            )}
          </div>
          </div>
        </div>

        <div className="play-coach-panel" style={{ maxHeight: boardSize + 72 }}>
          {gameOver && (
            <div className="play-gameover">
              <h3>
                {gameOver.result === 'checkmate' || gameOver.resigned
                  ? (gameOver.winner === (userColor === 'white' ? 'White' : 'Black')
                    ? 'You won!'
                    : 'You lost')
                  : 'Draw'}
                {' '}
                <span className="play-gameover-how">({gameOver.result})</span>
              </h3>
              <button
                type="button"
                className="play-analyze-btn"
                onClick={analyzeGame}
                disabled={analyzeStatus === 'running'}
              >
                {analyzeStatus === 'running' ? 'Analyzing…'
                  : analyzeStatus === 'error' ? 'Analysis failed — retry'
                    : 'Full review of this game'}
              </button>
            </div>
          )}

          <div className="play-coach-content">
            {coachLoading && (
              <div className="play-coach-loading">
                <div className="skeleton skeleton-line" style={{ width: '60%' }} />
                <div className="skeleton skeleton-line" style={{ width: '85%' }} />
                <p className="rep-loading-hint">Coach is checking your move…</p>
              </div>
            )}

            {!coachLoading && coach && (
              <>
                <div className="play-verdict-row">
                  <span className={`classification-badge cls-${lastVerdict || 'good'}`}>
                    {classificationLabel(lastVerdict)}
                  </span>
                  <MoveNotation san={coach.played} size="md" />
                  <span className="play-eval-now">{formatEval(coach.eval_after)}</span>
                </div>

                {coach.human?.played_pct != null && coach.classification !== 'book' && (
                  <p className="play-human-line">
                    {coach.human.played_pct >= 1
                      ? `About ${coach.human.played_pct}% of ~${coach.human.elo} players choose ${coach.played}.`
                      : `Almost nobody at ~${coach.human.elo} plays ${coach.played}.`}
                    {moment && coach.human.best_pct != null && coach.best_move !== coach.played && (
                      coach.human.best_pct <= 10
                        ? ` Only ${coach.human.best_pct}% find ${coach.best_move} — a hard move to see.`
                        : ` ${coach.human.best_pct}% find ${coach.best_move}.`
                    )}
                  </p>
                )}

                {moment?.explanation_blocks?.length > 0 && (
                  <ExplanationBlocks blocks={moment.explanation_blocks} interactive={false} />
                )}

                {!moment && coach.coach_line && (
                  <p className="play-coach-line">{coach.coach_line}</p>
                )}
                {!moment && !coach.coach_line && coach.classification === 'book' && (
                  <p className="play-coach-line">Book move — still in known opening territory.</p>
                )}
              </>
            )}

            {!coachLoading && !coach && !gameOver && (
              <p className="play-coach-line play-coach-idle">
                {sans.length === 0 && userTurn
                  ? 'Your move. The coach will comment on every move you make.'
                  : oppThinking
                    ? `${opponentName} is thinking…`
                    : 'Make a move to hear from the coach.'}
              </p>
            )}
          </div>

          <div className="play-movelist">
            {sans.map((san, i) => {
              const verdict = verdicts[i]
              return (
                <span key={`${i}-${san}`} className="play-move">
                  {i % 2 === 0 && <span className="play-move-num">{Math.floor(i / 2) + 1}.</span>}
                  <span className={verdict ? `play-move-v v-${verdict}` : ''}>
                    <MoveNotation san={san} size="sm" />
                  </span>
                </span>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
