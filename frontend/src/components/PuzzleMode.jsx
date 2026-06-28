import { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import { api } from '../api'
import { boardSquareStyles, customPieces, BOARD_ANIMATION_MS } from '../boardTheme'
import ExplanationBlocks from './ExplanationBlocks'
import { useBoardSize } from '../useBoardSize'
import { playStepSound, playIllegalSound } from '../sounds'
import BoardCoordinates, { BoardFileStrip } from './BoardCoordinates'
import PromotionDialog from './PromotionDialog'

export default function PuzzleMode() {
  const [searchParams] = useSearchParams()
  const themeFilter = searchParams.get('theme')
  const [puzzles, setPuzzles] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [state, setState] = useState('waiting')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [boardPosition, setBoardPosition] = useState('start')
  const [selectedSquare, setSelectedSquare] = useState(null)
  const [flipped, setFlipped] = useState(false)
  const [followUpIndex, setFollowUpIndex] = useState(-1)
  const [pendingPromotion, setPendingPromotion] = useState(null)
  const boardSize = useBoardSize()

  const loadPuzzles = useCallback(async (signal) => {
    setLoading(true)
    setLoadError(false)
    try {
      const themeQuery = themeFilter ? `&theme=${encodeURIComponent(themeFilter)}` : ''
      const res = await api.get(`/puzzles?limit=20${themeQuery}`, { signal })
      setPuzzles(res.data)
      setCurrentIndex(0)
      setState('waiting')
      setMessage('')
      setSelectedSquare(null)
      setPendingPromotion(null)
      if (res.data.length > 0) setBoardPosition(res.data[0].fen)
    } catch (e) {
      if (signal?.aborted || e.name === 'CanceledError' || e.code === 'ERR_CANCELED') return
      setLoadError(true)
    }
    if (!signal?.aborted) setLoading(false)
  }, [themeFilter])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => loadPuzzles(controller.signal), 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [loadPuzzles])

  const puzzle = puzzles[currentIndex]

  const legalMoves = useMemo(() => {
    if (!selectedSquare || !puzzle) return []
    try {
      return new Chess(boardPosition).moves({ square: selectedSquare, verbose: true })
    } catch {
      return []
    }
  }, [selectedSquare, boardPosition, puzzle])

  const squareStyles = useMemo(() => {
    const styles = {}
    if (selectedSquare) {
      styles[selectedSquare] = { backgroundColor: 'rgba(255, 255, 0, 0.4)' }
      try {
        const chess = new Chess(boardPosition)
        for (const move of legalMoves) {
          const targetPiece = chess.get(move.to)
          if (targetPiece) {
            styles[move.to] = {
              background: 'radial-gradient(transparent 51%, rgba(0,0,0,0.3) 51%)',
              borderRadius: '50%',
            }
          } else {
            styles[move.to] = {
              background: 'radial-gradient(rgba(0,0,0,0.25) 19%, transparent 20%)',
              cursor: 'pointer',
            }
          }
        }
      } catch { /* invalid fen */ }
    }
    return styles
  }, [selectedSquare, legalMoves, boardPosition])

  const isDone = state === 'solved' || state === 'revealed'

  const followUpPositions = useMemo(() => {
    if (!puzzle) return []
    const raw = Array.isArray(puzzle.follow_up_line) ? puzzle.follow_up_line : []
    if (!raw.length) return []
    const moves = raw[0] === puzzle.best_move ? raw.slice(1) : raw
    if (!moves.length) return []
    try {
      const chess = new Chess(puzzle.fen)
      chess.move(puzzle.best_move)
      const positions = []
      for (const san of moves) {
        const m = chess.move(san)
        if (!m) break
        positions.push({ san, fen: chess.fen() })
      }
      return positions
    } catch {
      return []
    }
  }, [puzzle])

  const solvedFen = useMemo(() => {
    if (!puzzle) return null
    try {
      const chess = new Chess(puzzle.fen)
      chess.move(puzzle.best_move)
      return chess.fen()
    } catch {
      return null
    }
  }, [puzzle])

  const playFollowUp = useCallback((index) => {
    if (index < 0) {
      if (solvedFen) setBoardPosition(solvedFen)
      setFollowUpIndex(-1)
    } else if (index < followUpPositions.length) {
      playStepSound(followUpPositions[index].san)
      setBoardPosition(followUpPositions[index].fen)
      setFollowUpIndex(index)
    }
  }, [followUpPositions, solvedFen])

  const goNext = useCallback(() => {
    if (currentIndex < puzzles.length - 1) {
      const nextIdx = currentIndex + 1
      setCurrentIndex(nextIdx)
      setState('waiting')
      setMessage('')
      setSelectedSquare(null)
      setFlipped(false)
      setFollowUpIndex(-1)
      setPendingPromotion(null)
      setBoardPosition(puzzles[nextIdx].fen)
    }
  }, [currentIndex, puzzles])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) {
      const prevIdx = currentIndex - 1
      setCurrentIndex(prevIdx)
      setState('waiting')
      setMessage('')
      setSelectedSquare(null)
      setFlipped(false)
      setFollowUpIndex(-1)
      setPendingPromotion(null)
      setBoardPosition(puzzles[prevIdx].fen)
    }
  }, [currentIndex, puzzles])

  const retryPuzzle = useCallback(() => {
    if (!puzzle) return
    setState('waiting')
    setMessage('')
    setSelectedSquare(null)
    setFollowUpIndex(-1)
    setPendingPromotion(null)
    setBoardPosition(puzzle.fen)
  }, [puzzle])

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      switch (e.key) {
        case 'ArrowRight':
          e.preventDefault()
          if (isDone) goNext()
          break
        case 'ArrowLeft':
          e.preventDefault()
          goPrev()
          break
        case 'f':
        case 'F':
          setFlipped(f => !f)
          break
        case 'r':
        case 'R':
          if (state !== 'waiting') retryPuzzle()
          break
        case 'Escape':
          setSelectedSquare(null)
          break
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isDone, state, goNext, goPrev, retryPuzzle])

  if (loading) return (
    <div className="puzzle-skeleton">
      <div className="skeleton skeleton-board" />
      <div className="skeleton-panel">
        <div className="skeleton skeleton-block" style={{ height: 80 }} />
        <div className="skeleton skeleton-line medium" />
        <div className="skeleton skeleton-line short" />
      </div>
    </div>
  )
  if (loadError) return (
    <div className="error-box">
      <p>Couldn't load puzzles</p>
      <p className="error-hint">Make sure the server is running, then try again</p>
      <button onClick={() => loadPuzzles()}>Try Again</button>
    </div>
  )
  if (!puzzles.length) {
    return (
      <div className="puzzle-empty">
        <h2>All Caught Up</h2>
        <p>No puzzles waiting. Analyze a game to generate new ones from your mistakes.</p>
        <p style={{ marginTop: 8, fontSize: 13, color: 'var(--text-muted)' }}>
          Solved puzzles come back for review after 1, 3, 7, 14, and 30 days.
        </p>
      </div>
    )
  }

  const baseOrientation = puzzle.side_to_move === 'White' ? 'white' : 'black'
  const orientation = flipped
    ? (baseOrientation === 'white' ? 'black' : 'white')
    : baseOrientation
  const completeMove = (from, to, promotion = 'q') => {
    const fenBefore = boardPosition
    const chess = new Chess(fenBefore)
    let move
    try {
      move = chess.move({ from, to, promotion })
    } catch {
      return false
    }
    if (!move) return false

    const fenAfter = chess.fen()
    playStepSound(move.san)

    if (move.san === puzzle.best_move) {
      setState('solved')
      setMessage('Correct!')
      setBoardPosition(fenAfter)
      setSelectedSquare(null)
      setPendingPromotion(null)
      api.post(`/puzzles/${puzzle.id}/attempt`, { solved: true })
      return true
    }

    if (state === 'waiting') {
      playIllegalSound()
      api.post(`/puzzles/${puzzle.id}/attempt`, { solved: false })
      setState('hint')
      const themes = puzzle.theme_tags || []
      setMessage(
        themes.length > 0
          ? `Not quite. Think about: ${themes.join(', ')}`
          : 'Not quite, keep looking.'
      )
    } else if (state === 'hint') {
      setState('revealed')
      setMessage(`The answer was ${puzzle.best_move}`)
    }
    setSelectedSquare(null)
    setPendingPromotion(null)
    return false
  }

  const needsPromotion = (from, to) => {
    try {
      const chess = new Chess(boardPosition)
      const piece = chess.get(from)
      if (!piece || piece.type !== 'p') return false
      const rank = to[1]
      return (piece.color === 'w' && rank === '8') || (piece.color === 'b' && rank === '1')
    } catch {
      return false
    }
  }

  const tryMove = (from, to) => {
    if (needsPromotion(from, to)) {
      const chess = new Chess(boardPosition)
      const piece = chess.get(from)
      setPendingPromotion({ from, to, color: piece.color })
      setSelectedSquare(null)
      return false
    }
    return completeMove(from, to, 'q')
  }

  const handleSquareClick = (square) => {
    if (isDone || pendingPromotion) return

    if (selectedSquare) {
      const isLegalTarget = legalMoves.some(m => m.to === square)
      if (isLegalTarget) {
        tryMove(selectedSquare, square)
        return
      }
    }

    try {
      const chess = new Chess(boardPosition)
      const piece = chess.get(square)
      const sideToMove = chess.turn() === 'w' ? 'White' : 'Black'
      if (piece && ((piece.color === 'w' && sideToMove === 'White') || (piece.color === 'b' && sideToMove === 'Black'))) {
        setSelectedSquare(square === selectedSquare ? null : square)
      } else {
        setSelectedSquare(null)
      }
    } catch {
      setSelectedSquare(null)
    }
  }

  const handlePieceDrop = (sourceSquare, targetSquare) => {
    if (isDone) return false
    setSelectedSquare(null)
    return tryMove(sourceSquare, targetSquare)
  }

  const statusColor = {
    waiting: '#888', hint: '#f39c12', solved: '#27ae60', revealed: '#e74c3c',
  }

  return (
    <div className="puzzle-page">
      <div className="puzzle-header">
        <h2>Puzzle {currentIndex + 1} / {puzzles.length}</h2>
        <span className="puzzle-side">{puzzle.side_to_move} to move</span>
        <span className="puzzle-from">Move {puzzle.move_number}</span>
      </div>
      {themeFilter && (
        <div className="puzzle-theme-banner">
          Practicing: <strong>{themeFilter}</strong>
          {' · '}
          <a href="/puzzles">Show all puzzles</a>
        </div>
      )}

      <div className="puzzle-layout">
        <div className="board-area" style={{ width: boardSize }}>
          <div className="player-bar top">
            <span className="player-name">
              {orientation === 'white' ? 'Black' : 'White'}
            </span>
          </div>
          <div className="board-frame">
            <div className="board-wrapper" style={{ width: boardSize, height: boardSize }}>
              <div className="board-layer-pieces">
                <Chessboard
                  id="puzzle-board"
                  position={boardPosition}
                  boardWidth={boardSize}
                  boardOrientation={orientation}
                  arePiecesDraggable={!isDone && !pendingPromotion}
                  onPieceDrop={handlePieceDrop}
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
                  onSelect={(piece) => {
                    completeMove(pendingPromotion.from, pendingPromotion.to, piece)
                    setPendingPromotion(null)
                  }}
                  onCancel={() => setPendingPromotion(null)}
                />
              )}
              <BoardCoordinates boardSize={boardSize} orientation={orientation} />
            </div>
            <BoardFileStrip boardSize={boardSize} orientation={orientation} />
          </div>
          <div className="player-bar bottom">
            <span className="player-name">
              {orientation === 'white' ? 'White' : 'Black'}
            </span>
          </div>
        </div>

        <div className="puzzle-side-panel" style={{ maxHeight: boardSize + 72 }}>
          <div className="puzzle-message" style={{ backgroundColor: `${statusColor[state]}12`, borderColor: `${statusColor[state]}30` }}>
            {state === 'waiting' && <p>Find the best move!</p>}
            {message && <p>{message}</p>}
          </div>

          {state === 'solved' && puzzle.explanation_blocks?.length > 0 && (
            <ExplanationBlocks blocks={puzzle.explanation_blocks} />
          )}

          {state === 'solved' && followUpPositions.length > 0 && (
            <div className="follow-up-controls">
              <p className="follow-up-label">Follow-up line</p>
              <div className="follow-up-buttons">
                <button type="button" onClick={() => playFollowUp(followUpIndex - 1)} disabled={followUpIndex < 0}>
                  ← Prev
                </button>
                <button type="button" onClick={() => playFollowUp(followUpIndex + 1)} disabled={followUpIndex >= followUpPositions.length - 1}>
                  Next →
                </button>
              </div>
            </div>
          )}

          {state !== 'waiting' && (
            <button type="button" className="retry-btn" onClick={retryPuzzle}>Try Again (R)</button>
          )}

          <div className="puzzle-nav">
            <button type="button" onClick={goPrev} disabled={currentIndex === 0}>← Previous</button>
            <button type="button" onClick={goNext} disabled={currentIndex >= puzzles.length - 1}>Next →</button>
          </div>
        </div>
      </div>
    </div>
  )
}
