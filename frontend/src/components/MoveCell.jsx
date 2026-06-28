import { memo } from 'react'
import MoveNotation from './MoveNotation'

/**
 * One half-move chip inside the mainline move list.
 *
 * `cls` (move classification) drives the colored dot and outline:
 *   - blunder / mistake / inaccuracy → warning dot
 *   - great / best                   → accent dot
 *   - book                           → 📖 icon, no dot
 * Highlighted coaching moments get a leading ★ regardless of `cls`.
 */
const MoveCell = memo(function MoveCell({
  data,
  isActive,
  isCritical,
  isHighlight,
  onGoToMove,
  activeRef,
}) {
  const { move, index } = data
  const cls = move.classification || 'good'

  return (
    <span
      ref={activeRef}
      className={`move-cell ${isActive ? 'active' : ''} ${isCritical ? 'critical' : ''} ${isHighlight ? 'highlight' : ''} cls-${cls}`}
      onClick={() => onGoToMove(index)}
    >
      {isHighlight && <span className="highlight-star" title="Strong move explained">★</span>}
      {(cls === 'blunder' || cls === 'mistake' || cls === 'inaccuracy' || cls === 'great' || cls === 'best') && (
        <span className={`cls-dot cls-dot-${cls}`} />
      )}
      {cls === 'book' && <span className="book-icon">📖</span>}
      <MoveNotation san={move.user_move} size="sm" />
    </span>
  )
})

export default MoveCell
