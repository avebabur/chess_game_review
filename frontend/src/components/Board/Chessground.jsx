import { useCallback, useEffect, useRef } from 'react'
import { Chessground } from 'chessground'
import 'chessground/assets/chessground.base.css'
// Board geometry from chessground; the board image + Merida pieces come from
// our own public assets (frontend/public) via board.css — not the bundled theme.
import './board.css'

const FILES = 'abcdefgh'

function squareFromEvent(event, orientation, el) {
  if (!el) return null
  const rect = el.getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width
  const y = (event.clientY - rect.top) / rect.height
  if (x < 0 || x > 1 || y < 0 || y > 1) return null
  const visualFile = Math.min(7, Math.max(0, Math.floor(x * 8)))
  const visualRank = Math.min(7, Math.max(0, Math.floor(y * 8)))
  const fileIndex = orientation === 'white' ? visualFile : 7 - visualFile
  const rank = orientation === 'white' ? 8 - visualRank : visualRank + 1
  return `${FILES[fileIndex]}${rank}`
}

/**
 * Thin React wrapper around lichess's chessground board.
 * Shows a position, last move, arrow hints, and optional legal move handling.
 */
export default function Board({
  fen,
  orientation = 'white',
  lastMove = null,
  shapes = [],
  duration = 220,
  movableDests = null,
  movableColor = 'both',
  onMove = null,
}) {
  const elRef = useRef(null)
  const cgRef = useRef(null)
  const onMoveRef = useRef(onMove)
  const moveVersionRef = useRef(0)
  const selectedSquareRef = useRef(null)
  const suppressCgMoveRef = useRef(null)

  useEffect(() => {
    onMoveRef.current = onMove
  }, [onMove])

  const emitMove = useCallback((orig, dest, metadata) => {
    moveVersionRef.current += 1
    onMoveRef.current?.(orig, dest, metadata)
  }, [])

  const handleCgMove = useCallback((orig, dest, metadata) => {
    const suppressed = suppressCgMoveRef.current
    if (suppressed?.orig === orig && suppressed?.dest === dest) {
      suppressCgMoveRef.current = null
      moveVersionRef.current += 1
      return
    }
    emitMove(orig, dest, metadata)
  }, [emitMove])

  const handleFallbackClick = useCallback((event) => {
    if (!onMove || !movableDests) return
    const square = squareFromEvent(event, orientation, elRef.current)
    if (!square) return
    const selected = selectedSquareRef.current
    const selectedDests = selected ? movableDests.get(selected) || [] : []
    if (selected && selectedDests.includes(square)) {
      selectedSquareRef.current = null
      const version = moveVersionRef.current
      window.setTimeout(() => {
        if (moveVersionRef.current !== version) return
        suppressCgMoveRef.current = { orig: selected, dest: square }
        emitMove(selected, square)
      }, 30)
      return
    }
    selectedSquareRef.current = (movableDests.get(square) || []).length ? square : null
  }, [emitMove, movableDests, onMove, orientation])

  useEffect(() => {
    selectedSquareRef.current = null
  }, [fen, orientation])

  useEffect(() => {
    cgRef.current = Chessground(elRef.current, {
      fen,
      orientation,
      viewOnly: !onMove,
      coordinates: true,
      animation: { enabled: true, duration },
      highlight: { lastMove: true, check: true },
      lastMove: lastMove || undefined,
      drawable: { enabled: false, visible: true, autoShapes: shapes },
      movable: {
        free: false,
        color: movableColor,
        dests: movableDests || new Map(),
        showDests: Boolean(onMove),
        events: { after: onMove ? handleCgMove : undefined },
      },
    })
    return () => cgRef.current?.destroy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    cgRef.current?.set({
      fen,
      orientation,
      viewOnly: !onMove,
      lastMove: lastMove || undefined,
      drawable: { autoShapes: shapes },
      movable: {
        free: false,
        color: movableColor,
        dests: movableDests || new Map(),
        showDests: Boolean(onMove),
        events: { after: onMove ? handleCgMove : undefined },
      },
    })
  }, [fen, orientation, lastMove, shapes, movableDests, movableColor, onMove, handleCgMove])

  return (
    <div className="cr-board">
      <div className="cr-board-inner" ref={elRef} onClick={handleFallbackClick} />
    </div>
  )
}
