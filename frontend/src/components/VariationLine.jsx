import { memo } from 'react'
import MoveNotation from './MoveNotation'

/**
 * Renders one user-explored variation as a branch under the mainline.
 * Stateless and memoized — parent owns the variation list and active cursor.
 *
 * Props:
 *  - variation:   { branchFrom, baseFen, moves[], fens[], moment?, kind? }
 *  - varIndex:    integer index into the parent `variations` array
 *  - isActive:    true when this variation is currently being explored
 *  - activeCursor: index within this variation that the user is on (-1 if none)
 *  - onClickMove(varIndex, moveIdx): jump to a specific half-move inside this var
 *  - onDelete(varIndex): drop this variation entirely
 *  - activeRef:   ref attached to the active <span> for scroll-into-view
 */
const VariationLine = memo(function VariationLine({
  variation,
  varIndex,
  isActive,
  activeCursor,
  onClickMove,
  onDelete,
  activeRef,
}) {
  return (
    <div className={`variation-branch ${isActive ? 'variation-active' : ''}`}>
      <span className="variation-indicator">&#x21b3;</span>
      <div className="variation-moves">
        {variation.moves.map((move, i) => {
          const halfMove = variation.branchFrom + 1 + i
          const moveNum = Math.floor(halfMove / 2) + 1
          const isWhite = halfMove % 2 === 0
          const showNumber = i === 0 || isWhite

          return (
            <span key={i} className="variation-move-wrapper">
              {showNumber && (
                <span className="variation-move-num">
                  {moveNum}{isWhite ? '.' : '...'}
                </span>
              )}
              <span
                ref={isActive && activeCursor === i ? activeRef : null}
                className={`variation-move ${isActive && activeCursor === i ? 'variation-move-active' : ''}`}
                onClick={() => onClickMove(varIndex, i)}
              >
                <MoveNotation san={move} size="sm" />
              </span>
            </span>
          )
        })}
      </div>
      <button
        className="variation-delete-btn"
        onClick={(e) => { e.stopPropagation(); onDelete(varIndex) }}
        title="Remove variation"
      >
        &times;
      </button>
    </div>
  )
})

export default VariationLine
