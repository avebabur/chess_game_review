import { memo } from 'react'
import { buildVariationLine } from '../variationUtils'
import { blocksFromMoment, findActiveStep } from '../explanationBlocks'
import ExplanationBlocks, { AlternativesList } from './ExplanationBlocks'
import MoveNotation from './MoveNotation'
import { PALETTE } from '../palette'

const TYPE_COLORS = {
  blunder: PALETTE.red,
  drift: PALETTE.gold,
  missed_tactic: PALETTE.redInk,
  mistake: PALETTE.redInk,
  highlight: PALETTE.goldInk,
}

const TYPE_LABELS = {
  blunder: 'BLUNDER',
  drift: 'POSITIONAL DRIFT',
  missed_tactic: 'MISSED TACTIC',
  mistake: 'MISTAKE',
  highlight: 'STRONG MOVE',
}

function formatClock(seconds) {
  if (seconds == null) return null
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export default memo(function ExplanationPanel({
  moment,
  onFollowUp,
  onExplanationMove,
  onReanalyzeMoment,
  momentReanalyzeStatus = null,
  preview,
  onBackToGame,
}) {
  if (!moment) return null

  const blocks = blocksFromMoment(moment)
  const activeStep = preview ? findActiveStep(blocks, preview) : null
  const isExploring = Boolean(preview)

  const followUpMoves = Array.isArray(moment.follow_up_line)
    ? moment.follow_up_line
    : typeof moment.follow_up_line === 'string'
      ? moment.follow_up_line.split(' ').filter(Boolean)
      : []

  const hasBetterSteps = blocks.some(
    b => (b.id === 'better' || b.id === 'tactic') && b.steps?.length > 0,
  )

  const handleStep = (step, blockId, stepIndex, stepCount) => {
    if (!onExplanationMove) return
    onExplanationMove(step, { blockId, stepIndex, stepCount })
  }

  const handleAltMove = (alt, san, moveIndex, moves) => {
    if (!onExplanationMove) return
    onExplanationMove(
      { san, line: 'alt', index: moveIndex, altRank: alt.rank, altMoves: moves },
      { blockId: 'alternatives', stepIndex: moveIndex, stepCount: moves.length, altRank: alt.rank },
    )
  }

  const momentColor = TYPE_COLORS[moment.type] || PALETTE.faint

  return (
    <div
      className="explanation-panel"
      style={{
        backgroundColor: `${momentColor}10`,
        borderColor: `${momentColor}30`,
      }}
    >
      <div className="explanation-header">
        <span
          className="moment-badge"
          style={{ backgroundColor: momentColor }}
        >
          {TYPE_LABELS[moment.type] || moment.type}
        </span>
        {moment.time_pressure && (
          <span
            className="time-pressure-chip"
            title="This mistake likely happened under time pressure"
          >
            ⏱ {formatClock(moment.clock_before_seconds) || 'low time'}
          </span>
        )}
        <span className="moment-move-info">
          Move {moment.move_number}{moment.side === 'White' ? '.' : '...'}{' '}
        </span>
        {onReanalyzeMoment && (
          <button
            type="button"
            className="reanalyze-moment-btn"
            onClick={() => onReanalyzeMoment(moment)}
            disabled={momentReanalyzeStatus === 'running'}
            title="Re-run Stockfish and refresh coaching notes for this moment only (~15s)"
          >
            {momentReanalyzeStatus === 'running'
              ? 'Refreshing…'
              : momentReanalyzeStatus === 'done'
                ? 'Updated'
                : momentReanalyzeStatus === 'error'
                  ? 'Failed — retry'
                  : 'Refresh moment'}
          </button>
        )}
      </div>

      {momentReanalyzeStatus === 'running' && (
        <p className="reanalyze-moment-hint">Updating engine lines and coaching notes…</p>
      )}

      {/* The You-played/Best-move card, eval rows, and board-diff legend
          used to live here — removed 2026-06-11: the board, the eval bar,
          and the lesson sentence already carry all of it. The lesson is
          the product; everything else was noise. */}
      <ExplanationBlocks
        blocks={blocks}
        activeStep={activeStep}
        onStep={handleStep}
        onAltMove={handleAltMove}
        onBackToGame={onBackToGame}
        isExploring={isExploring}
        interactive
        previewLink={preview?.link}
      />

      {moment.alternative_lines?.length > 1 && !blocks.some(b => b.id === 'alternatives') && (
        <AlternativesList
          alternatives={moment.alternative_lines.slice(1)}
          onAltMove={handleAltMove}
          activeLink={preview?.link}
        />
      )}

      {!hasBetterSteps && followUpMoves.length > 0 && (
        <div className="follow-up">
          <span className="follow-up-label">Engine line:</span>
          <div className="follow-up-moves-list">
            {followUpMoves.map((move, i) => (
              <button
                key={i}
                className="follow-up-move-btn"
                onClick={() => {
                  if (!onFollowUp) return
                  const { played } = buildVariationLine(
                    moment.fen,
                    moment.best_move,
                    followUpMoves.slice(0, i + 1),
                  )
                  onFollowUp(followUpMoves, moment.best_move, played.length - 1, {
                    blockId: 'follow-up',
                    stepIndex: i,
                    stepCount: followUpMoves.length,
                  })
                }}
                title={`Play up to ${move}`}
              >
                <MoveNotation san={move} size="sm" />
              </button>
            ))}
            {onFollowUp && (
              <button
                className="play-all-btn"
                onClick={() => onFollowUp(followUpMoves, moment.best_move, null, {
                  blockId: 'follow-up',
                  stepIndex: followUpMoves.length - 1,
                  stepCount: followUpMoves.length,
                })}
              >
                ▶ All
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
})
