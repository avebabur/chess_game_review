import { Chessboard } from 'react-chessboard'
import BoardCoordinates, { BoardFileStrip } from './BoardCoordinates'
import ClassificationBadge from './ClassificationBadge'
import PlayerBar from './PlayerBar'
import PromotionDialog from './PromotionDialog'
import { BOARD_ANIMATION_MS, boardSquareStyles, customPieces } from '../boardTheme'
import { CLS_SYMBOLS } from '../reviewUtils'

const noPromotion = () => false

/**
 * The board column (top/bottom PlayerBar + interactive Chessboard).
 *
 * Pure presentation: the parent computes `displayPosition`, `squareStyles`,
 * `arrows`, etc. and just hands them down. This component also handles the
 * floating overlays anchored to the board:
 *   - classification badge (??, ?, !, ★ etc.) on the destination square
 *   - pending-promotion piece picker
 *   - "Back to game" exploration banner when previewing a variation
 *
 * `classificationBadge` is only rendered for non-good classifications, when
 * the user is on the mainline and not currently looking at a coach-diff view
 * — otherwise the badge would float over the wrong square.
 */
export default function ReviewBoard({
  boardSize,
  boardOrientation,
  flipped,
  topPlayer,
  topAccuracy,
  topCaptured,
  topMaterialAdv,
  bottomPlayer,
  bottomAccuracy,
  bottomCaptured,
  bottomMaterialAdv,
  displayPosition,
  squareStyles,
  arrows,
  pendingPromotion,
  setPendingPromotion,
  handlePieceDrop,
  handleSquareClick,
  handlePromotion,
  isExploring,
  boardPreview,
  exitExploration,
  coachingDiffMoment,
  currentMoveData,
}) {
  const showBadge = (
    !isExploring
    && !coachingDiffMoment
    && currentMoveData
    && CLS_SYMBOLS[currentMoveData.classification]
    && currentMoveData.classification !== 'good'
  )

  return (
    <div className="board-area" style={{ width: boardSize }}>
      <PlayerBar
        name={topPlayer}
        accuracy={topAccuracy}
        captured={topCaptured}
        isTop
        materialAdvantage={topMaterialAdv}
      />
      <div className="board-frame">
        <div className="board-wrapper" style={{ width: boardSize, height: boardSize }}>
          {isExploring && boardPreview && (
            <div className="board-preview-banner">
              <span className="board-preview-label">{boardPreview.label}</span>
              <button type="button" className="board-preview-back" onClick={exitExploration}>
                Back to game
              </button>
            </div>
          )}
          <div className="board-layer-pieces">
            <Chessboard
              id="review-board"
              position={displayPosition}
              boardWidth={boardSize}
              boardOrientation={boardOrientation}
              arePiecesDraggable={!pendingPromotion}
              onPieceDrop={handlePieceDrop}
              onSquareClick={handleSquareClick}
              onPromotionCheck={noPromotion}
              animationDuration={BOARD_ANIMATION_MS}
              customSquareStyles={squareStyles}
              customArrows={arrows}
              customPieces={customPieces}
              {...boardSquareStyles}
            />
          </div>
          <BoardCoordinates boardSize={boardSize} orientation={boardOrientation} />
          {showBadge && (
            <ClassificationBadge
              cls={currentMoveData.classification}
              fen={currentMoveData.fen}
              move={currentMoveData.user_move}
              flipped={flipped}
              boardSize={boardSize}
            />
          )}
          {pendingPromotion && (
            <PromotionDialog
              color={pendingPromotion.color}
              onSelect={handlePromotion}
              onCancel={() => setPendingPromotion(null)}
            />
          )}
        </div>
        <BoardFileStrip boardSize={boardSize} orientation={boardOrientation} />
      </div>
      <PlayerBar
        name={bottomPlayer}
        accuracy={bottomAccuracy}
        captured={bottomCaptured}
        isTop={false}
        materialAdvantage={bottomMaterialAdv}
      />
    </div>
  )
}
