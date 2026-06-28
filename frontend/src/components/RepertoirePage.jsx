import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { Chessboard } from 'react-chessboard'
import { Chess } from 'chess.js'
import { api } from '../api'
import { boardSquareStyles, customPieces, BOARD_ANIMATION_MS } from '../boardTheme'
import { useBoardSize } from '../useBoardSize'
import { formatEval } from '../reviewUtils'
import { playStepSound, playIllegalSound } from '../sounds'
import BoardCoordinates, { BoardFileStrip } from './BoardCoordinates'
import MoveNotation from './MoveNotation'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const ELO_CHOICES = [800, 1000, 1100, 1200, 1400, 1600, 1800, 2000]

const VERDICT_META = {
  best: { label: 'Best', color: '#27ae60' },
  solid: { label: 'Solid', color: '#3a9bdc' },
  inaccuracy: { label: 'Inaccuracy', color: '#f39c12' },
  mistake: { label: 'Mistake', color: '#e74c3c' },
  unknown: { label: '—', color: '#888' },
}

/** SAN list -> uci arrow [from, to] on `fen`, or null. */
function sanToArrow(fen, san) {
  try {
    const chess = new Chess(fen)
    const move = chess.move(san)
    return move ? [move.from, move.to] : null
  } catch {
    return null
  }
}

function HumanBar({ pct }) {
  if (pct == null) return <span className="rep-human-none">–</span>
  return (
    <span className="rep-human">
      <span className="rep-human-bar" style={{ width: `${Math.min(100, pct)}%` }} />
      <span className="rep-human-pct">{pct}%</span>
    </span>
  )
}

export default function RepertoirePage() {
  const [moves, setMoves] = useState([])
  const [color, setColor] = useState(() => localStorage.getItem('rep_color') || 'white')
  const [elo, setElo] = useState(() => Number(localStorage.getItem('rep_elo')) || 1100)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [hoverSan, setHoverSan] = useState(null)
  const [savedLines, setSavedLines] = useState([])
  const [drill, setDrill] = useState(null) // {line, sans, idx, fails, status, hint}
  const [selectedSquare, setSelectedSquare] = useState(null)
  const boardSize = useBoardSize()
  const drillTimer = useRef(null)

  const fen = useMemo(() => {
    const chess = new Chess()
    for (const san of moves) {
      try { chess.move(san) } catch { break }
    }
    return chess.fen()
  }, [moves])

  const drillFen = useMemo(() => {
    if (!drill) return START_FEN
    const chess = new Chess()
    for (const san of drill.sans.slice(0, drill.idx)) {
      try { chess.move(san) } catch { break }
    }
    return chess.fen()
  }, [drill])

  const displayFen = drill ? drillFen : fen

  useEffect(() => { localStorage.setItem('rep_elo', String(elo)) }, [elo])
  useEffect(() => { localStorage.setItem('rep_color', color) }, [color])

  // Explore the current position (skipped while drilling).
  useEffect(() => {
    if (drill) return undefined
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setLoadError(false)
      try {
        const res = await api.get('/repertoire/explore', {
          params: { fen, elo },
          signal: controller.signal,
        })
        setData(res.data)
      } catch (e) {
        if (controller.signal.aborted || e.code === 'ERR_CANCELED') return
        setLoadError(true)
      }
      if (!controller.signal.aborted) setLoading(false)
    }, 120)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [fen, elo, drill])

  const loadSavedLines = useCallback(async () => {
    try {
      const res = await api.get('/repertoire/lines')
      setSavedLines(res.data)
    } catch { /* panel just stays empty */ }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => loadSavedLines(), 0)
    return () => window.clearTimeout(timer)
  }, [loadSavedLines])

  useEffect(() => () => window.clearTimeout(drillTimer.current), [])

  const playMove = useCallback((san) => {
    const chess = new Chess(fen)
    let move
    try { move = chess.move(san) } catch { return false }
    if (!move) return false
    playStepSound(move.san)
    setHoverSan(null)
    setMoves(m => [...m, move.san])
    return true
  }, [fen])

  const tryBoardMove = (from, to) => {
    setSelectedSquare(null)
    const chess = new Chess(displayFen)
    let move
    try { move = chess.move({ from, to, promotion: 'q' }) } catch { return false }
    if (!move) return false
    if (drill) return handleDrillMove(move.san)
    chess.undo()
    return playMove(move.san)
  }

  const legalTargets = useMemo(() => {
    if (!selectedSquare) return []
    try {
      return new Chess(displayFen).moves({ square: selectedSquare, verbose: true }).map(m => m.to)
    } catch {
      return []
    }
  }, [selectedSquare, displayFen])

  const handleSquareClick = (square) => {
    if (drill && drill.status !== 'your-turn') return
    if (selectedSquare && legalTargets.includes(square)) {
      tryBoardMove(selectedSquare, square)
      return
    }
    const chess = new Chess(displayFen)
    const piece = chess.get(square)
    if (piece && piece.color === chess.turn()) {
      setSelectedSquare(square === selectedSquare ? null : square)
    } else {
      setSelectedSquare(null)
    }
  }

  const squareStyles = useMemo(() => {
    const styles = {}
    if (selectedSquare) {
      styles[selectedSquare] = { backgroundColor: 'rgba(255, 255, 0, 0.4)' }
      const chess = new Chess(displayFen)
      for (const to of legalTargets) {
        styles[to] = chess.get(to)
          ? { background: 'radial-gradient(transparent 51%, rgba(0,0,0,0.3) 51%)', borderRadius: '50%' }
          : { background: 'radial-gradient(rgba(0,0,0,0.25) 19%, transparent 20%)', cursor: 'pointer' }
      }
    }
    return styles
  }, [selectedSquare, legalTargets, displayFen])

  // --- Drill: reproduce your side of a saved line ---
  const advanceOpponent = useCallback((sans, idx, lineColor) => {
    // Auto-play opponent moves until it's the user's turn (or line ends).
    let i = idx
    const userIsWhite = lineColor === 'white'
    const play = () => {
      if (i >= sans.length) {
        setDrill(d => (d ? { ...d, idx: i, status: 'done' } : d))
        return
      }
      const whiteToMove = i % 2 === 0
      if (whiteToMove === userIsWhite) {
        setDrill(d => (d ? { ...d, idx: i, status: 'your-turn' } : d))
        return
      }
      playStepSound(sans[i])
      i += 1
      setDrill(d => (d ? { ...d, idx: i } : d))
      drillTimer.current = window.setTimeout(play, 450)
    }
    play()
  }, [])

  const startDrill = useCallback((line) => {
    window.clearTimeout(drillTimer.current)
    const sans = line.moves_san.split(' ')
    setDrill({ line, sans, idx: 0, fails: 0, status: 'your-turn', hint: false })
    drillTimer.current = window.setTimeout(
      () => advanceOpponent(sans, 0, line.color), 350,
    )
  }, [advanceOpponent])

  const stopDrill = useCallback(() => {
    window.clearTimeout(drillTimer.current)
    setDrill(null)
  }, [])

  const handleDrillMove = (san) => {
    if (!drill || drill.status !== 'your-turn') return false
    const expected = drill.sans[drill.idx]
    if (san === expected) {
      playStepSound(san)
      const nextIdx = drill.idx + 1
      const done = nextIdx >= drill.sans.length
      setDrill(d => (d ? { ...d, idx: nextIdx, hint: false, status: done ? 'done' : d.status } : d))
      if (!done) {
        drillTimer.current = window.setTimeout(
          () => advanceOpponent(drill.sans, nextIdx, drill.line.color), 350,
        )
      }
      return true
    }
    playIllegalSound()
    setDrill(d => (d ? { ...d, fails: d.fails + 1, hint: d.fails + 1 >= 2 } : d))
    return false
  }

  // Record the drill once, whoever finished it (your move or the auto-played
  // opponent tail), then refresh the saved-lines panel's drill counts.
  useEffect(() => {
    if (drill?.status === 'done') {
      api.post(`/repertoire/lines/${drill.line.id}/drill`, { solved: drill.fails === 0 })
        .then(loadSavedLines)
        .catch(() => {})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drill?.status])

  const saveCurrentLine = async () => {
    if (!moves.length) return
    const defaultName = data?.opening?.name || `${moves.slice(0, 3).join(' ')}…`
    const name = window.prompt('Name this line:', defaultName)
    if (name == null) return
    try {
      await api.post('/repertoire/lines', {
        color,
        name: name.trim() || defaultName,
        moves_san: moves.join(' '),
      })
      loadSavedLines()
    } catch {
      window.alert('Could not save the line — is the server running?')
    }
  }

  const deleteLine = async (id) => {
    try {
      await api.delete(`/repertoire/lines/${id}`)
      setSavedLines(ls => ls.filter(l => l.id !== id))
    } catch { /* leave list as is */ }
  }

  const loadLine = (line) => {
    stopDrill()
    setMoves(line.moves_san.split(' '))
    setColor(line.color)
  }

  const arrows = useMemo(() => {
    if (drill) {
      if (drill.hint && drill.status === 'your-turn') {
        const arrow = sanToArrow(drillFen, drill.sans[drill.idx])
        return arrow ? [[...arrow, '#c9a86c']] : []
      }
      return []
    }
    if (hoverSan) {
      const arrow = sanToArrow(fen, hoverSan)
      return arrow ? [[...arrow, '#c9a86c']] : []
    }
    return []
  }, [hoverSan, fen, drill, drillFen])

  const orientation = color
  const candidates = data?.candidates || []
  const openingName = data?.opening?.name
  const sideToMove = displayFen.split(' ')[1] === 'w' ? 'White' : 'Black'
  const moveWord = moves.length === 1 ? 'move' : 'moves'
  const yourTurnToSave = sideToMove.toLowerCase() !== color
    ? `${moves.length} ${moveWord} — opponent to move`
    : `${moves.length} ${moveWord}`

  return (
    <div className="repertoire-page">
      <div className="rep-header">
        <h2>Opening Repertoire</h2>
        <div className="rep-controls">
          <label className="rep-control">
            I play
            <select value={color} onChange={e => { setColor(e.target.value) }}>
              <option value="white">White</option>
              <option value="black">Black</option>
            </select>
          </label>
          <label className="rep-control">
            My level
            <select value={elo} onChange={e => setElo(Number(e.target.value))}>
              {ELO_CHOICES.map(v => <option key={v} value={v}>~{v}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="repertoire-layout">
        <div className="rep-saved-panel" style={{ maxHeight: boardSize + 96 }}>
          <h3>Your lines</h3>
          {savedLines.length === 0 && (
            <p className="rep-saved-empty">
              Explore moves on the board, then save lines you want to remember.
              Drill them until they're automatic.
            </p>
          )}
          <ul className="rep-saved-list">
            {savedLines.map(line => (
              <li key={line.id} className="rep-saved-item">
                <div className="rep-saved-main">
                  <button
                    type="button"
                    className="rep-saved-name"
                    onClick={() => loadLine(line)}
                    title={line.moves_san}
                  >
                    <span className={`rep-color-dot ${line.color}`} />
                    {line.name}
                  </button>
                  <span className="rep-saved-meta">
                    {line.moves_san.split(' ').length} moves
                    {line.drill_count > 0 && ` · drilled ${line.drill_count}×`}
                  </span>
                </div>
                <div className="rep-saved-actions">
                  <button type="button" onClick={() => startDrill(line)} title="Drill this line">▶</button>
                  <button type="button" onClick={() => deleteLine(line.id)} title="Delete">✕</button>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="board-area" style={{ width: boardSize }}>
          <div className="rep-breadcrumb">
            <button
              type="button"
              className="rep-crumb-btn rep-crumb-reset"
              onClick={() => { stopDrill(); setMoves([]) }}
              disabled={!moves.length && !drill}
              title="Back to the starting position"
            >
              ⟲ Start
            </button>
            {(drill ? drill.sans.slice(0, drill.idx) : moves).map((san, i) => (
              <button
                key={`${i}-${san}`}
                type="button"
                className="rep-crumb-btn"
                onClick={() => !drill && setMoves(m => m.slice(0, i + 1))}
                disabled={Boolean(drill)}
              >
                {i % 2 === 0 && <span className="rep-crumb-num">{Math.floor(i / 2) + 1}.</span>}
                <MoveNotation san={san} size="sm" />
              </button>
            ))}
            {!drill && moves.length > 0 && (
              <button
                type="button"
                className="rep-crumb-btn rep-crumb-undo"
                onClick={() => setMoves(m => m.slice(0, -1))}
                title="Take back the last move"
              >
                ⌫
              </button>
            )}
          </div>

          <div className="board-frame">
            <div className="board-wrapper" style={{ width: boardSize, height: boardSize }}>
              <div className="board-layer-pieces">
                <Chessboard
                  id="repertoire-board"
                  position={displayFen}
                  boardWidth={boardSize}
                  boardOrientation={orientation}
                  arePiecesDraggable={!drill || drill.status === 'your-turn'}
                  onPieceDrop={(from, to) => tryBoardMove(from, to)}
                  onSquareClick={handleSquareClick}
                  animationDuration={BOARD_ANIMATION_MS}
                  customArrows={arrows}
                  customSquareStyles={squareStyles}
                  customPieces={customPieces}
                  {...boardSquareStyles}
                />
              </div>
              <BoardCoordinates boardSize={boardSize} orientation={orientation} />
            </div>
            <BoardFileStrip boardSize={boardSize} orientation={orientation} />
          </div>

          {!drill && (
            <div className="rep-board-footer">
              <span className="rep-eval">{data ? formatEval(data.eval) : '…'}</span>
              <span className="rep-board-status">{yourTurnToSave}</span>
              <button
                type="button"
                className="rep-save-btn"
                onClick={saveCurrentLine}
                disabled={!moves.length}
                title="Save this move sequence to your repertoire"
              >
                ★ Save line
              </button>
            </div>
          )}
        </div>

        <div className="rep-panel" style={{ maxHeight: boardSize + 96 }}>
          {drill ? (
            <div className="rep-drill-panel">
              <h3>Drilling: {drill.line.name}</h3>
              {drill.status === 'your-turn' && (
                <p className="rep-drill-msg">
                  Your move {Math.floor(drill.idx / 2) + 1} — play the line for
                  {' '}{drill.line.color === 'white' ? 'White' : 'Black'}.
                  {drill.fails === 1 && ' Not that one — try again.'}
                  {drill.hint && (
                    <>
                      {' '}Hint: <MoveNotation san={drill.sans[drill.idx]} size="sm" />
                    </>
                  )}
                </p>
              )}
              {drill.status === 'done' && (
                <p className="rep-drill-msg rep-drill-done">
                  {drill.fails === 0
                    ? 'Perfect — the whole line from memory. ✓'
                    : `Line complete, with ${drill.fails} slip${drill.fails > 1 ? 's' : ''}. Run it again until it's clean.`}
                </p>
              )}
              <div className="rep-drill-actions">
                {drill.status === 'done' && (
                  <button type="button" onClick={() => startDrill(drill.line)}>Again</button>
                )}
                <button type="button" onClick={stopDrill}>Exit drill</button>
              </div>
            </div>
          ) : (
            <>
              <div className="rep-opening-name">
                {openingName
                  ? <><strong>{openingName}</strong>{data?.opening?.eco ? ` · ${data.opening.eco}` : ''}</>
                  : moves.length === 0 ? 'Starting position' : 'Out of book'}
              </div>

              {loadError && (
                <p className="rep-error">Couldn't reach the engine — check the server, then click a move to retry.</p>
              )}

              {loading && (
                <div className="rep-loading">
                  <div className="skeleton skeleton-line" style={{ width: '70%' }} />
                  <div className="skeleton skeleton-line" style={{ width: '85%' }} />
                  <div className="skeleton skeleton-line" style={{ width: '60%' }} />
                  <p className="rep-loading-hint">Maia + Stockfish are thinking…</p>
                </div>
              )}

              {!loading && !loadError && candidates.length > 0 && (
                <div className="rep-candidates">
                  <div className="rep-cand-head">
                    <span>{sideToMove} to move</span>
                    <span className="rep-cand-head-right">~{elo} plays · engine says</span>
                  </div>
                  <ul className="rep-cand-list">
                    {candidates.map(c => {
                      const meta = VERDICT_META[c.verdict] || VERDICT_META.unknown
                      return (
                        <li
                          key={c.san}
                          className="rep-cand"
                          onMouseEnter={() => setHoverSan(c.san)}
                          onMouseLeave={() => setHoverSan(s => (s === c.san ? null : s))}
                        >
                          <button
                            type="button"
                            className="rep-cand-row"
                            onClick={() => playMove(c.san)}
                            title={`Play ${c.san}`}
                          >
                            <MoveNotation san={c.san} size="md" className="rep-cand-san" />
                            <HumanBar pct={c.human_pct} />
                            <span className="rep-cand-eval">
                              {c.eval != null ? formatEval(c.eval) : '—'}
                            </span>
                            <span className="rep-verdict" style={{ color: meta.color, borderColor: `${meta.color}55` }}>
                              {meta.label}
                            </span>
                          </button>
                          {c.why && <p className="rep-cand-why">{c.why}</p>}
                          {c.trap && <p className="rep-cand-trap">⚠ {c.trap}</p>}
                        </li>
                      )
                    })}
                  </ul>
                  {!data?.maia_available && (
                    <p className="rep-maia-note">
                      Human-play percentages unavailable (Maia model not loaded) — showing engine lines only.
                    </p>
                  )}
                </div>
              )}

              {!loading && !loadError && candidates.length === 0 && (
                <p className="rep-empty">No candidate moves here — the game is over.</p>
              )}
            </>
          )}
        </div>
      </div>

      <div className="keyboard-hint">
        Click a candidate or move a piece to descend · breadcrumb to jump back · ★ saves the line for drilling
      </div>
    </div>
  )
}
