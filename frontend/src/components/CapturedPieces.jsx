import { memo } from 'react'
import { CAPTURE_GLYPHS } from '../captures'

export default memo(function CapturedPieces({ pieces, isLightBar }) {
  if (!pieces?.length) return null

  return (
    <span className={`captured-pieces ${isLightBar ? 'on-light' : 'on-dark'}`} aria-label="Captured pieces">
      {pieces.map((p, i) => {
        const key = `${p.color}${p.type}`
        return (
          <span key={`${key}-${i}`} className="captured-piece" title={p.type.toUpperCase()}>
            {CAPTURE_GLYPHS[key] || p.type}
          </span>
        )
      })}
    </span>
  )
})
