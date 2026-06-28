import { Chess } from 'chess.js'

/** Full engine PV from the decision point (best move first when missing). */
export function normalizePvLine(bestMove, followUpMoves) {
  const line = [...(followUpMoves || [])]
  if (bestMove && (line.length === 0 || line[0] !== bestMove)) {
    line.unshift(bestMove)
  }
  return line
}

export function buildLineFromFen(fen, moves) {
  const chess = new Chess(fen)
  const played = []
  const fens = []
  for (const m of moves || []) {
    try {
      chess.move(m)
      played.push(m)
      fens.push(chess.fen())
    } catch {
      break
    }
  }
  return { played, fens }
}

export function buildVariationLine(fen, bestMove, followUpMoves) {
  return buildLineFromFen(fen, normalizePvLine(bestMove, followUpMoves))
}

/** Map a step link to the index in a played line (handles index/san mismatches). */
export function resolveCursorIndex(played, link) {
  if (!played?.length) return 0
  if (link?.san) {
    const bySan = played.indexOf(link.san)
    if (bySan >= 0) return bySan
  }
  if (link?.index != null && link.index >= 0 && link.index < played.length) {
    return link.index
  }
  return played.length - 1
}

/** Play opponent refutation from the position after the user's move (no prepended best move). */
export function buildRefutationLine(fenAfter, refutationMoves) {
  const chess = new Chess(fenAfter)
  const played = []
  const fens = []
  for (const m of refutationMoves || []) {
    try {
      chess.move(m)
      played.push(m)
      fens.push(chess.fen())
    } catch {
      break
    }
  }
  return { played, fens }
}
