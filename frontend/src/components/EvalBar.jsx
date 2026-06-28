import { memo } from 'react'

export default memo(function EvalBar({ eval: evalScore, flipped, height = 640 }) {
  const isMate = Math.abs(evalScore) >= 100
  const displayVal = isMate ? (evalScore > 0 ? 10 : -10) : evalScore
  const clampedEval = Math.max(-10, Math.min(10, displayVal))
  const whitePercent = 50 + (clampedEval / 10) * 50

  let displayEvalText
  if (Math.abs(evalScore) >= 900) {
    const mateIn = Math.round(Math.abs(evalScore) - 1000)
    displayEvalText = evalScore > 0 ? `M${mateIn}` : `-M${mateIn}`
  } else if (Math.abs(evalScore) >= 100) {
    displayEvalText = evalScore > 0 ? 'M' : '-M'
  } else {
    displayEvalText = evalScore > 0 ? `+${evalScore.toFixed(1)}` : evalScore.toFixed(1)
  }

  // When not flipped: white at bottom (board perspective: white plays from bottom)
  // The bar is a column: first child is top, second is bottom
  // Not flipped: top = black portion, bottom = white portion
  // Flipped: top = white portion, bottom = black portion
  const topColor = flipped ? 'oklch(93% 0.006 270)' : 'oklch(28% 0.01 270)'
  const bottomColor = flipped ? 'oklch(28% 0.01 270)' : 'oklch(93% 0.006 270)'
  const topHeight = flipped ? whitePercent : 100 - whitePercent
  const bottomHeight = flipped ? 100 - whitePercent : whitePercent

  return (
    <div className="eval-bar-container">
      <div className="eval-bar" style={{ height }}>
        <div style={{ height: `${topHeight}%`, background: topColor, transition: 'height 0.15s ease' }} />
        <div style={{ height: `${bottomHeight}%`, background: bottomColor, transition: 'height 0.15s ease' }} />
      </div>
      <div className={`eval-label ${evalScore >= 0 ? 'white-advantage' : 'black-advantage'}`}>
        {displayEvalText}
      </div>
    </div>
  )
})
