/**
 * Pure builders for the Chessboard `customSquareStyles` and `customArrows`
 * props. Extracted from GameReview so the rules are testable in isolation
 * and don't have to live inside a 200-line useMemo.
 *
 * Visual conventions used throughout:
 *  - Played-move highlight: dim olive on from/to squares.
 *  - Selected piece: warm yellow on origin, capture/empty dot on legal targets.
 *  - In-check king: red radial glow on the king square.
 *  - Variation preview highlights: dashed blue outline.
 *  - PV arrow color ramp: see `PV_ARROW_COLORS` in reviewUtils.
 *  - Refutation arrows: alternating red (opponent) / blue (your reply).
 *
 * Intentionally absent: the "coach diff" overlay that used to paint changed
 * squares in green/red when comparing the played-line vs the best-line. It
 * was visually noisy and competed with the played-move highlight; the same
 * information is in the engine arrows and the punishment line steps.
 */

import { Chess } from 'chess.js'
import { CLS_SYMBOLS, parseMoveFromFen, appendLineArrows } from './reviewUtils'

const LAST_MOVE_BG = { backgroundColor: 'rgba(186, 202, 68, 0.42)' }

// During a coaching moment we show the position BEFORE the played move and
// want the player to see both what they actually played and what the engine
// recommended. Two distinct tints make the comparison instant — without
// this overlay the user only sees the best-move arrow and has no clue
// where their own move went.
const PLAYED_MOVE_TINT = { backgroundColor: 'rgba(231, 76, 60, 0.30)' }
const BEST_MOVE_TINT = { backgroundColor: 'rgba(46, 204, 113, 0.30)' }

const SELECTION_BG = { backgroundColor: 'rgba(255, 255, 0, 0.4)' }
const LEGAL_CAPTURE = {
  background: 'radial-gradient(transparent 51%, rgba(0,0,0,0.3) 51%)',
  borderRadius: '50%',
}
const LEGAL_EMPTY = {
  background: 'radial-gradient(rgba(0,0,0,0.25) 19%, transparent 20%)',
  cursor: 'pointer',
}
const PREVIEW_HIGHLIGHT = {
  outline: '3px dashed rgba(93, 173, 226, 0.45)',
  outlineOffset: '-3px',
}
const CHECK_GLOW = {
  background: 'radial-gradient(ellipse at center, rgba(220, 20, 20, 0.85) 0%, rgba(169, 0, 0, 0.35) 45%, transparent 72%)',
}

const REFUTATION_COLORS = [
  'rgba(231, 76, 60, 0.9)',
  'rgba(79, 195, 247, 0.75)',
  'rgba(231, 76, 60, 0.75)',
  'rgba(79, 195, 247, 0.6)',
  'rgba(231, 76, 60, 0.6)',
]

/**
 * Compute the full `customSquareStyles` for the current board state.
 * Style precedence (later layers win on the same square):
 *   1. Last-move highlight (mainline or variation)
 *   2. Variation preview "highlights" set
 *   3. Selection + legal-move dots
 *   4. Mainline classification tint
 *   5. In-check king glow
 */
export function buildSquareStyles({
  isExploring,
  currentMoveData,
  selectedSquare,
  legalMoves,
  coachingDiffMoment,
  activeVar,
  exploreCursor,
  displayPosition,
  boardPreview,
}) {
  const styles = {}

  if (!isExploring && currentMoveData && !selectedSquare && !coachingDiffMoment) {
    const lastSq = parseMoveFromFen(currentMoveData.fen, currentMoveData.user_move)
    if (lastSq) {
      styles[lastSq.from] = LAST_MOVE_BG
      styles[lastSq.to] = LAST_MOVE_BG
    }
  }

  // Coaching moment: paint the played-move from/to in red and the best-move
  // from/to in green on the BEFORE-position board, so the player can see
  // both choices side-by-side. Previously the highlight was suppressed
  // during coachingDiffMoment which made the explained move invisible on
  // the board.
  if (!isExploring && coachingDiffMoment && !selectedSquare) {
    const playedSq = parseMoveFromFen(coachingDiffMoment.fen, coachingDiffMoment.user_move)
    const bestSq = parseMoveFromFen(coachingDiffMoment.fen, coachingDiffMoment.best_move)
    if (playedSq) {
      styles[playedSq.from] = { ...styles[playedSq.from], ...PLAYED_MOVE_TINT }
      styles[playedSq.to] = { ...styles[playedSq.to], ...PLAYED_MOVE_TINT }
    }
    if (bestSq) {
      styles[bestSq.from] = { ...styles[bestSq.from], ...BEST_MOVE_TINT }
      styles[bestSq.to] = { ...styles[bestSq.to], ...BEST_MOVE_TINT }
    }
  }

  if (isExploring && activeVar && !selectedSquare) {
    const prevFen = exploreCursor === 0 ? activeVar.baseFen : activeVar.fens[exploreCursor - 1]
    const lastSq = parseMoveFromFen(prevFen, activeVar.moves[exploreCursor])
    if (lastSq) {
      styles[lastSq.from] = LAST_MOVE_BG
      styles[lastSq.to] = LAST_MOVE_BG
    }
    for (const sq of boardPreview?.link?.highlights || []) {
      styles[sq] = { ...styles[sq], ...PREVIEW_HIGHLIGHT }
    }
  }

  if (selectedSquare) {
    styles[selectedSquare] = SELECTION_BG
    try {
      const chess = new Chess(displayPosition)
      for (const sq of legalMoves) {
        styles[sq] = chess.get(sq) ? LEGAL_CAPTURE : LEGAL_EMPTY
      }
    } catch { /* invalid fen */ }
  }

  if (!isExploring && currentMoveData && !selectedSquare && !coachingDiffMoment) {
    const sq = parseMoveFromFen(currentMoveData.fen, currentMoveData.user_move)
    if (sq) {
      const cls = currentMoveData.classification
      const clsInfo = CLS_SYMBOLS[cls]
      if (clsInfo && cls !== 'good') {
        styles[sq.to] = {
          ...styles[sq.to],
          backgroundColor: cls === 'blunder' || cls === 'mistake'
            ? `${clsInfo.color}40` : undefined,
        }
      }
    }
  }

  try {
    const chess = new Chess(displayPosition)
    if (chess.inCheck()) {
      const turn = chess.turn()
      const board = chess.board()
      for (let r = 0; r < 8; r++) {
        for (let c = 0; c < 8; c++) {
          const p = board[r][c]
          if (p && p.type === 'k' && p.color === turn) {
            const sq = `${String.fromCharCode(97 + c)}${8 - r}`
            styles[sq] = { ...styles[sq], ...CHECK_GLOW }
          }
        }
      }
    }
  } catch { /* invalid fen */ }

  return styles
}

/**
 * Compute board arrows: PV ramp on the mainline, variation arrows during
 * exploration, refutation alternating arrows when previewing a refutation,
 * and a single green arrow for the exploration eval's best move.
 */
export function buildBoardArrows({
  isExploring,
  currentMoveData,
  activeMoment,
  exploreEval,
  displayPosition,
  boardPreview,
  activeVar,
  exploreCursor,
}) {
  const arrs = []

  if (!isExploring && currentMoveData && currentMoveData.user_move !== currentMoveData.best_move) {
    const pvMoves = currentMoveData.top_lines?.[0]?.pv
      || activeMoment?.follow_up_line
      || [currentMoveData.best_move]
    appendLineArrows(arrs, currentMoveData.fen, pvMoves, pvMoves.length)
  }

  if (isExploring && activeVar) {
    if (activeVar.kind === 'pv' || activeVar.kind === 'alt') {
      appendLineArrows(arrs, activeVar.baseFen, activeVar.moves, exploreCursor + 1)
    } else if (activeVar.kind === 'refutation') {
      appendLineArrows(arrs, activeVar.baseFen, activeVar.moves, exploreCursor + 1, REFUTATION_COLORS)
      if (boardPreview?.link?.san) {
        const prevFen = exploreCursor === 0 ? activeVar.baseFen : activeVar.fens[exploreCursor - 1]
        const stepSq = parseMoveFromFen(prevFen, boardPreview.link.san)
        if (stepSq) {
          const color = boardPreview.link.opponent === false
            ? 'rgba(79, 195, 247, 0.95)'
            : 'rgba(231, 76, 60, 0.95)'
          arrs.push([stepSq.from, stepSq.to, color])
        }
      }
    }
    // BUG FIX 2026-05-29: the old code early-returned here, so the
    // green "engine best move at this exploring position" arrow below
    // never rendered while the user was navigating an activeVar (which
    // is almost the entire exploration session). User reported "can't
    // see top engine moves while exploring". Now we FALL THROUGH and
    // append the best-move arrow on top of the variation arrows.
  }

  // Green arrow: engine's best move for THIS exploring position.
  // Appended last so it renders on top of variation arrows. The user
  // only needs the single best (top main line) — that's all that's
  // overlaid; PV depth beyond that stays in the side panel text.
  if (isExploring && exploreEval?.best_move && displayPosition) {
    const bestSq = parseMoveFromFen(displayPosition, exploreEval.best_move)
    if (bestSq) {
      arrs.push([bestSq.from, bestSq.to, 'rgb(0, 180, 0)'])
    }
  }

  return arrs
}
