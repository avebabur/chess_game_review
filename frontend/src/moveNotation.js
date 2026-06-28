/** Unicode piece glyphs for move display (same family as captured pieces). */
export const MOVE_PIECE_GLYPHS = {
  K: '♔',
  Q: '♕',
  R: '♖',
  B: '♗',
  N: '♘',
  P: '♙',
}

/**
 * Parse SAN into display parts. Disambiguation file/rank come from the SAN itself
 * (e.g. Nbd2, N1d2, Nb1d2) so the correct piece is always identifiable.
 */
export function parseSanDisplay(san) {
  if (!san || typeof san !== 'string') {
    return { kind: 'text', text: san || '' }
  }

  const trimmed = san.trim()
  if (trimmed === 'O-O' || trimmed === 'O-O-O') {
    return {
      kind: 'castle',
      glyph: MOVE_PIECE_GLYPHS.K,
      label: trimmed,
      suffix: '',
    }
  }

  let suffix = ''
  let core = trimmed
  const suffixMatch = core.match(/([+#]+)$/)
  if (suffixMatch) {
    suffix = suffixMatch[1]
    core = core.slice(0, -suffix.length)
  }

  let promotion = null
  const promoMatch = core.match(/=([QRBNqrbn])$/)
  if (promoMatch) {
    promotion = promoMatch[1].toUpperCase()
    core = core.slice(0, -promoMatch[0].length)
  }

  const pieceMatch = core.match(/^([KQRBN])([a-h])?([1-8])?(x?)([a-h][1-8])$/)
  if (pieceMatch) {
    const piece = pieceMatch[1]
    return {
      kind: 'piece',
      glyph: MOVE_PIECE_GLYPHS[piece],
      piece,
      disambigFile: pieceMatch[2] || null,
      disambigRank: pieceMatch[3] || null,
      capture: Boolean(pieceMatch[4]),
      to: pieceMatch[5],
      promotion,
      suffix,
    }
  }

  const pawnCapture = core.match(/^([a-h])(x)([a-h][1-8])$/)
  if (pawnCapture) {
    return {
      kind: 'pawn',
      glyph: MOVE_PIECE_GLYPHS.P,
      fromFile: pawnCapture[1],
      capture: true,
      to: pawnCapture[3],
      promotion,
      suffix,
    }
  }

  const pawnPush = core.match(/^([a-h][1-8])$/)
  if (pawnPush) {
    return {
      kind: 'pawn',
      glyph: MOVE_PIECE_GLYPHS.P,
      fromFile: null,
      capture: false,
      to: pawnPush[1],
      promotion,
      suffix,
    }
  }

  return { kind: 'text', text: trimmed }
}
