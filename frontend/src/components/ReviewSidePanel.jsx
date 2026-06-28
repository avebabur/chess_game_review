import ExplanationPanel from './ExplanationPanel'
import DriftSpans from './DriftSpans'
import KeyMoments from './KeyMoments'
import MoveNotation from './MoveNotation'
import PlanThreads from './PlanThreads'
import { classificationLabel, formatEval } from '../reviewUtils'

/**
 * Right column of Game Review. Three mutually-exclusive states, in priority:
 *
 *  1. `panelMoment` set → render full <ExplanationPanel> for the coaching
 *     moment under the cursor (or one that was forced via `followUpMoment`).
 *  2. Exploring a variation but no moment attached → show a minimal eval +
 *     "best move" hint built from the live `exploreEval` SSE stream.
 *  3. Plain mainline navigation with no moment → show a compact classification
 *     header (best/great/?/?? badge) plus the after-move eval.
 *
 * Falls back to "Starting position" text when none of the above match. In every
 * no-moment state we also show game-level strategic summaries.
 */
export default function ReviewSidePanel({
  boardSize,
  panelMoment,
  goToFollowUp,
  goToExplanationMove,
  handleReanalyzeMoment,
  momentReanalyzeStatus,
  boardPreview,
  exitExploration,
  isExploring,
  exploreEval,
  currentMoveData,
  evalScore,
  driftSpans,
  planThreads,
  criticalMoments,
  goToMove,
  openingIdea,
}) {
  return (
    <div className="right-panel" style={{ maxHeight: boardSize + 72 }}>
      <div className="info-section">
        {panelMoment ? (
          <ExplanationPanel
            moment={panelMoment}
            onFollowUp={goToFollowUp}
            onExplanationMove={goToExplanationMove}
            onReanalyzeMoment={handleReanalyzeMoment}
            momentReanalyzeStatus={momentReanalyzeStatus}
            preview={boardPreview}
            onBackToGame={exitExploration}
          />
        ) : (
          <>
            {isExploring ? (
              <div className="no-moment">
                <p className="eval-display">
                  Eval: <strong>{formatEval(exploreEval?.eval ?? 0)}</strong>
                </p>
                {exploreEval?.best_move && (
                  <p className="best-hint">
                    Best: <MoveNotation san={exploreEval.best_move} size="sm" />
                  </p>
                )}
                {exploreEval?.depth > 0 && (
                  <p className="eval-depth-hint">
                    {exploreEval.searching
                      ? `Refining… depth ${exploreEval.depth}/${exploreEval.target_depth || 20}`
                      : `Depth ${exploreEval.depth}`}
                  </p>
                )}
                <button type="button" className="explanation-back-btn" onClick={exitExploration}>
                  ← Back to your game
                </button>
              </div>
            ) : currentMoveData ? (
              <div className="no-moment">
                <div className="move-classification-header">
                  <span className={`classification-badge cls-${currentMoveData.classification || 'good'}`}>
                    {classificationLabel(currentMoveData.classification)}
                  </span>
                  <span className="current-move-san">
                    {currentMoveData.move_number}
                    {currentMoveData.side === 'White' ? '.' : '...'}
                    {' '}
                    <MoveNotation san={currentMoveData.user_move} size="md" />
                  </span>
                </div>
                <p className="eval-display">
                  Eval: <strong>{formatEval(evalScore)}</strong>
                </p>
                {currentMoveData.user_move !== currentMoveData.best_move && (
                  <p className="best-hint">
                    Best: <MoveNotation san={currentMoveData.best_move} size="sm" />
                  </p>
                )}
                {currentMoveData.coach_line && (
                  <p className="coach-line">{currentMoveData.coach_line}</p>
                )}
              </div>
            ) : (
              <div className="no-moment">
                <p className="eval-display">Starting position</p>
                {openingIdea && (
                  <p className="coach-line opening-idea-hint">
                    <strong>Opening idea:</strong> {openingIdea}
                  </p>
                )}
                <KeyMoments moments={criticalMoments} onJump={goToMove} />
              </div>
            )}
            <PlanThreads threads={planThreads} onGoToMove={goToMove} />
            <DriftSpans spans={driftSpans} onGoToMove={goToMove} />
          </>
        )}
      </div>
    </div>
  )
}
