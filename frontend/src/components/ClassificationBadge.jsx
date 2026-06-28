import { CLS_SYMBOLS, parseMoveFromFen } from '../reviewUtils'

/**
 * Floating !? / ?? / ★ badge anchored to the destination square of a move.
 *
 * Positioning is computed from board size + flip orientation so the badge
 * stays attached even when the board is resized or flipped. Returns null
 * silently when the classification isn't visualised (e.g. 'good') or the
 * move can't be parsed against the given FEN.
 */
export default function ClassificationBadge({ cls, fen, move, flipped, boardSize }) {
  const info = CLS_SYMBOLS[cls]
  if (!info) return null

  const sq = parseMoveFromFen(fen, move)
  if (!sq) return null

  const col = sq.to.charCodeAt(0) - 97
  const row = parseInt(sq.to[1]) - 1
  const x = flipped ? (7 - col) : col
  const y = flipped ? row : (7 - row)
  const pxPerSquare = boardSize / 8
  const left = x * pxPerSquare + pxPerSquare - 14
  const top = y * pxPerSquare - 4

  return (
    <div
      className="board-cls-badge"
      style={{
        left: `${left}px`,
        top: `${top}px`,
        backgroundColor: info.color,
      }}
    >
      {info.text}
    </div>
  )
}
