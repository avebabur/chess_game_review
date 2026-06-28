/**
 * Tiny pure helpers shared by Game Review components.
 *
 * Keep this file dependency-light (just chess.js) so any UI piece can import
 * it without dragging in board / panel state. Anything that needs React state
 * belongs in a hook, not here.
 */

import { Chess } from 'chess.js'

/**
 * Key-moment ranking — the few moves that actually decided the game. Shared by
 * the <KeyMoments> overview AND the eval-graph markers so they never disagree.
 * Ranks by the mover's eval swing, capped (mate artifacts), ignoring minor
 * slips and moves played from an already-decided position.
 */
const KM_DECIDED = 6
const KM_SWING_CAP = 12
const KM_MIN_SWING = 1.0
const KM_MAX_ROWS = 5

export const KEY_MOMENT_TYPES = {
  blunder: { cls: 'blunder', label: 'Blunder' },
  mistake: { cls: 'mistake', label: 'Mistake' },
  missed_tactic: { cls: 'mistake', label: 'Missed tactic' },
}

function moverSwing(m) {
  const eb = Number(m.eval_before)
  const ea = Number(m.eval_after)
  if (!Number.isFinite(eb) || !Number.isFinite(ea)) return null
  return m.side === 'White' ? eb - ea : ea - eb
}

function moverEvalBefore(m) {
  const eb = Number(m.eval_before)
  return m.side === 'White' ? eb : -eb
}

/** The few game-deciding turning points, returned in game order. */
export function rankKeyMoments(moments, maxRows = KM_MAX_ROWS) {
  return (moments || [])
    .filter(m => KEY_MOMENT_TYPES[m.type])
    .map(m => ({ m, swing: moverSwing(m) }))
    .filter(x => x.swing != null && x.swing >= KM_MIN_SWING
      && Math.abs(moverEvalBefore(x.m)) < KM_DECIDED)
    .map(x => ({ ...x, rank: Math.min(x.swing, KM_SWING_CAP) }))
    .sort((a, b) => b.rank - a.rank)
    .slice(0, maxRows)
    .sort((a, b) => a.m.move_index - b.m.move_index)
    .map(x => x.m)
}

/** Engine pawn-units -> compact display string ("+1.20", "M3"). */
export function formatEval(v) {
  if (Math.abs(v) >= 900) {
    const mateIn = Math.round(Math.abs(v) - 1000)
    return v > 0 ? `M${mateIn}` : `-M${mateIn}`
  }
  if (Math.abs(v) >= 100) {
    return v > 0 ? 'M' : '-M'
  }
  return v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2)
}

/**
 * Per-classification badge presentation. Keys must match the move
 * classifications produced by backend `move_detection.classify_move`.
 * 'good' has no visual badge by design — only deviations are surfaced.
 */
export const CLS_SYMBOLS = {
  blunder: { text: '??', color: '#e74c3c' },
  mistake: { text: '?', color: '#e67e22' },
  inaccuracy: { text: '?!', color: '#f1c40f' },
  great: { text: '!', color: '#2ecc71' },
  best: { text: '★', color: '#27ae60' },
  excellent: { text: '◆', color: '#2ecc71' },
  book: { text: '📖', color: '#6c5ce7' },
}

/** SAN move on a given FEN -> `{from, to}` squares, or null if illegal. */
export function parseMoveFromFen(fen, moveSan) {
  if (!fen || !moveSan) return null
  try {
    const chess = new Chess(fen)
    const parsed = chess.move(moveSan)
    return parsed ? { from: parsed.from, to: parsed.to } : null
  } catch { return null }
}

export function classificationLabel(cls) {
  const labels = {
    book: '📖 Book',
    best: '★ Best',
    excellent: 'Excellent',
    great: '! Great',
    good: 'Good',
    inaccuracy: '?! Inaccuracy',
    mistake: '? Mistake',
    blunder: '?? Blunder',
  }
  return labels[cls] || cls
}

/** Arrow color ramp for engine principal-variation overlays. */
export const PV_ARROW_COLORS = [
  'rgb(0, 180, 0)',
  'rgba(79, 195, 247, 0.9)',
  'rgba(79, 195, 247, 0.75)',
  'rgba(79, 195, 247, 0.6)',
  'rgba(79, 195, 247, 0.45)',
]

/**
 * Push board arrows for a SAN sequence starting at `startFen`.
 * Mutates `arrs` in place to match the existing call sites.
 */
export function appendLineArrows(arrs, startFen, lineMoves, count, colors = PV_ARROW_COLORS) {
  try {
    const chess = new Chess(startFen)
    const limit = Math.min(count, lineMoves.length)
    for (let i = 0; i < limit; i++) {
      const parsed = parseMoveFromFen(chess.fen(), lineMoves[i])
      if (!parsed) break
      arrs.push([parsed.from, parsed.to, colors[i] || colors[colors.length - 1]])
      chess.move(lineMoves[i])
    }
  } catch { /* skip invalid line */ }
}
