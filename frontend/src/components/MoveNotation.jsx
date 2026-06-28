import { memo } from 'react'
import { parseSanDisplay, MOVE_PIECE_GLYPHS } from '../moveNotation'

function MoveNotation({ san, size = 'md', className = '' }) {
  if (!san) return null

  const parsed = parseSanDisplay(san)
  const classes = ['move-notation', `move-notation-${size}`, className].filter(Boolean).join(' ')

  if (parsed.kind === 'text') {
    return <span className={classes} title={san}>{parsed.text}</span>
  }

  if (parsed.kind === 'castle') {
    return (
      <span className={classes} title={san} aria-label={san}>
        <span className="move-piece-glyph" aria-hidden="true">{parsed.glyph}</span>
        <span className="move-castle">{parsed.label}</span>
        {parsed.suffix && <span className="move-suffix">{parsed.suffix}</span>}
      </span>
    )
  }

  const disambigParts = []
  if (parsed.kind === 'piece') {
    if (parsed.disambigFile) disambigParts.push(parsed.disambigFile)
    if (parsed.disambigRank) disambigParts.push(parsed.disambigRank)
  } else if (parsed.fromFile) {
    disambigParts.push(parsed.fromFile)
  }

  return (
    <span className={classes} title={san} aria-label={san}>
      <span className="move-piece-glyph" aria-hidden="true">{parsed.glyph}</span>
      {disambigParts.map((part, i) => (
        <span key={`${part}-${i}`} className="move-disambig">{part}</span>
      ))}
      {parsed.capture && <span className="move-capture" aria-hidden="true">&times;</span>}
      <span className="move-square">{parsed.to}</span>
      {parsed.promotion && (
        <>
          <span className="move-promo-eq" aria-hidden="true">=</span>
          <span className="move-piece-glyph move-promo-piece" aria-hidden="true">
            {MOVE_PIECE_GLYPHS[parsed.promotion]}
          </span>
        </>
      )}
      {parsed.suffix && <span className="move-suffix">{parsed.suffix}</span>}
    </span>
  )
}

export default memo(MoveNotation)
