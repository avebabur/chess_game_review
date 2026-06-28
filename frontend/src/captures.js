import { Chess } from 'chess.js'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

const PIECE_VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9 }
const SORT_ORDER = { q: 0, r: 1, b: 2, n: 3, p: 4 }

export const CAPTURE_GLYPHS = {
  bp: '♟', bn: '♞', bb: '♝', br: '♜', bq: '♛',
  wp: '♙', wn: '♘', wb: '♗', wr: '♖', wq: '♕',
}

function sortCaptured(pieces) {
  return [...pieces].sort((a, b) => (SORT_ORDER[a.type] ?? 9) - (SORT_ORDER[b.type] ?? 9))
}

const EMPTY_CAPTURE_STATE = {
  whiteCaptured: [],
  blackCaptured: [],
  materialBalance: 0,
}

function captureStateFromLists(whiteCaptured, blackCaptured) {
  const whitePoints = whiteCaptured.reduce((s, p) => s + (PIECE_VALUE[p.type] || 0), 0)
  const blackPoints = blackCaptured.reduce((s, p) => s + (PIECE_VALUE[p.type] || 0), 0)
  return {
    whiteCaptured: sortCaptured(whiteCaptured),
    blackCaptured: sortCaptured(blackCaptured),
    materialBalance: whitePoints - blackPoints,
  }
}

/** Precompute capture trays per move index (0 = start, i+1 = after move i). */
export function buildCaptureTimeline(moves = []) {
  const timeline = [EMPTY_CAPTURE_STATE]
  const chess = new Chess(START_FEN)
  const whiteCaptured = []
  const blackCaptured = []

  for (let i = 0; i < moves.length; i++) {
    const san = moves[i]?.user_move
    if (!san) break
    try {
      const m = chess.move(san)
      if (m?.captured) {
        const capturedColor = m.color === 'w' ? 'b' : 'w'
        const piece = { type: m.captured, color: capturedColor }
        if (m.color === 'w') whiteCaptured.push(piece)
        else blackCaptured.push(piece)
      }
      timeline.push(captureStateFromLists(whiteCaptured, blackCaptured))
    } catch {
      break
    }
  }

  return timeline
}

/** Captured pieces up to the current position (chess.js move.captured). */
export function computeCaptures({
  moves = [],
  currentMove = -1,
  isExploring = false,
  activeVar = null,
  exploreCursor = 0,
}) {
  const chess = new Chess(START_FEN)
  const whiteCaptured = []
  const blackCaptured = []

  const apply = (san) => {
    if (!san) return false
    try {
      const m = chess.move(san)
      if (m?.captured) {
        const capturedColor = m.color === 'w' ? 'b' : 'w'
        const piece = { type: m.captured, color: capturedColor }
        if (m.color === 'w') whiteCaptured.push(piece)
        else blackCaptured.push(piece)
      }
      return true
    } catch {
      return false
    }
  }

  if (isExploring && activeVar) {
    const branch = activeVar.branchFrom ?? -1
    if (branch < 0) {
      try {
        chess.load(activeVar.baseFen || START_FEN)
      } catch {
        chess.load(START_FEN)
      }
    } else {
      for (let i = 0; i <= branch; i++) {
        if (!moves[i]) break
        if (!apply(moves[i].user_move)) break
      }
    }
    for (let j = 0; j <= exploreCursor; j++) {
      if (!apply(activeVar.moves[j])) break
    }
  } else {
    for (let i = 0; i <= currentMove; i++) {
      if (i < 0 || !moves[i]) continue
      if (!apply(moves[i].user_move)) break
    }
  }

  return captureStateFromLists(whiteCaptured, blackCaptured)
}
