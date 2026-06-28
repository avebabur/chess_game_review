import { Fragment } from 'react'
import GamePatternsSummary from './GamePatternsSummary'
import EvalGraph from './EvalGraph'
import MoveCell from './MoveCell'
import VariationLine from './VariationLine'

/**
 * Left column of Game Review: pattern summary, transport controls, mainline
 * move list (with interleaved variations), and the eval graph footer.
 *
 * `variationsByBranch` is a Map<branchIndex, varIndex[]> keyed by the
 * mainline half-move *before* the branch; -1 means "branch before move 1".
 * Variations are rendered right under the move they branched from so the
 * scroll position stays anchored as the user explores.
 *
 * `activeMoveRef` is forwarded to whichever cell or variation step is
 * currently focused — the parent uses it for scrollIntoView.
 */
export default function ReviewMoveList({
  boardSize,
  gamePatterns,
  criticalMoments,
  movePairs,
  variations,
  variationsByBranch,
  activeVariation,
  exploreCursor,
  currentMove,
  isExploring,
  criticalIndices,
  highlightIndices,
  moves,
  goToMove,
  goToExploreMove,
  deleteVariation,
  setFlipped,
  activeMoveRef,
  keyMomentIndices,
  driftSpans,
}) {
  return (
    <div className="left-panel" style={{ maxHeight: boardSize + 72 }}>
      <div className="move-list-container">
        <GamePatternsSummary
          patterns={gamePatterns}
          criticalMoments={criticalMoments}
          onGoToMove={goToMove}
        />
        <div className="move-controls">
          <button onClick={() => goToMove(-1)} aria-label="Go to start">⏮</button>
          <button onClick={() => goToMove(currentMove - 1)} aria-label="Previous move">◀</button>
          <button onClick={() => goToMove(currentMove + 1)} aria-label="Next move">▶</button>
          <button onClick={() => goToMove(moves.length - 1)} aria-label="Go to end">⏭</button>
          <button onClick={() => setFlipped(f => !f)} aria-label="Flip board">⇅</button>
        </div>

        <div className="move-list-table">
          {(variationsByBranch.get(-1) || []).map(vi => (
            <VariationLine
              key={`var-pre-${vi}`}
              variation={variations[vi]}
              varIndex={vi}
              isActive={activeVariation === vi}
              activeCursor={activeVariation === vi ? exploreCursor : -1}
              onClickMove={goToExploreMove}
              onDelete={deleteVariation}
              activeRef={activeVariation === vi ? activeMoveRef : null}
            />
          ))}
          {movePairs.map((pair) => (
            <Fragment key={pair.number}>
              <div className="move-row">
                <span className="move-number-col">{pair.number}.</span>
                <MoveCell
                  data={pair.white}
                  isActive={pair.white.index === currentMove && !isExploring}
                  isCritical={criticalIndices.has(pair.white.index) && !highlightIndices.has(pair.white.index)}
                  isHighlight={highlightIndices.has(pair.white.index)}
                  onGoToMove={goToMove}
                  activeRef={pair.white.index === currentMove && !isExploring ? activeMoveRef : null}
                />
                {pair.black ? (
                  <MoveCell
                    data={pair.black}
                    isActive={pair.black.index === currentMove && !isExploring}
                    isCritical={criticalIndices.has(pair.black.index) && !highlightIndices.has(pair.black.index)}
                    isHighlight={highlightIndices.has(pair.black.index)}
                    onGoToMove={goToMove}
                    activeRef={pair.black.index === currentMove && !isExploring ? activeMoveRef : null}
                  />
                ) : (
                  <span className="move-cell empty" />
                )}
              </div>
              {[pair.white.index, pair.black?.index].filter(i => i != null).flatMap(idx =>
                (variationsByBranch.get(idx) || []).map(vi => (
                  <VariationLine
                    key={`var-${vi}`}
                    variation={variations[vi]}
                    varIndex={vi}
                    isActive={activeVariation === vi}
                    activeCursor={activeVariation === vi ? exploreCursor : -1}
                    onClickMove={goToExploreMove}
                    onDelete={deleteVariation}
                    activeRef={activeVariation === vi ? activeMoveRef : null}
                  />
                )),
              )}
            </Fragment>
          ))}
        </div>
      </div>

      <EvalGraph
        moves={moves}
        currentMove={currentMove}
        onClickMove={goToMove}
        keyMomentIndices={keyMomentIndices}
        driftSpans={driftSpans}
      />
    </div>
  )
}
