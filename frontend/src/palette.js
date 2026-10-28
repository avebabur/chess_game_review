/**
 * The poker-table palette for places CSS variables can't reach: SVG
 * presentation attributes (board arrows, the eval graph) and inline styles
 * computed in JS. Keep in sync with styles/tokens.css.
 */
export const PALETTE = {
  felt: '#133827',
  felt2: '#18442f',
  felt3: '#1f5840',
  feltDeep: '#0e2c1e',
  cream: '#f2ebdd',
  muted: '#b9bca9',
  faint: '#8c9a89',
  gold: '#c29a45',
  goldInk: '#d9b871',
  red: '#b1262b',
  redInk: '#e0827a',
  good: '#a9c79f',
  line: '#2b5a44',
}

/** `#rrggbb` + alpha → `rgba(...)` (react-chessboard wants plain colour strings). */
export function alpha(hex, a) {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}

/** Move-classification colours shared by badges, the move list and the eval graph. */
export const CLASS_COLORS = {
  blunder: PALETTE.red,
  mistake: PALETTE.redInk,
  inaccuracy: PALETTE.gold,
  great: PALETTE.goldInk,
  best: PALETTE.good,
  excellent: PALETTE.good,
  book: PALETTE.muted,
}
