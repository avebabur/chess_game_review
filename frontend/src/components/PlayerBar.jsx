import { memo } from 'react'
import CapturedPieces from './CapturedPieces'

export default memo(function PlayerBar({ name, accuracy, captured, isTop, materialAdvantage }) {
  const isLightBar = !isTop
  const showAdvantage = materialAdvantage > 0

  return (
    <div className={`player-bar ${isTop ? 'top' : 'bottom'}`}>
      <div className="player-bar-left">
        <span className="player-name">{name}</span>
        <CapturedPieces pieces={captured} isLightBar={isLightBar} />
        {showAdvantage && (
          <span className="material-advantage" title="Extra material from captures">
            +{materialAdvantage}
          </span>
        )}
      </div>
      {accuracy != null && <span className="player-accuracy">{accuracy}%</span>}
    </div>
  )
})
