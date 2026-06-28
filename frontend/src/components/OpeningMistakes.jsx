import { Link } from 'react-router-dom'

function HotspotMoments({ moments }) {
  if (!moments?.length) return null
  return (
    <div className="opening-hotspot-moments">
      {moments.slice(0, 4).map(m => (
        <Link
          key={`${m.game_id}-${m.move_index}`}
          to={`/review/${m.game_id}?move=${m.move_index}`}
          className="opening-hotspot-link"
        >
          #{m.game_id} m{m.move_number} ({m.user_move})
        </Link>
      ))}
    </div>
  )
}

export default function OpeningMistakes({ data, loading }) {
  if (loading) {
    return (
      <div className="opening-mistakes-card">
        <div className="skeleton skeleton-block" style={{ height: 80 }} />
      </div>
    )
  }

  const openings = data?.openings || []
  if (!openings.length) {
    return (
      <div className="opening-mistakes-card">
        <h2>Opening mistake patterns</h2>
        <p className="no-data">
          Opening-phase blunders grouped by opening appear after you analyze several games.
        </p>
      </div>
    )
  }

  return (
    <div className="opening-mistakes-card">
      <h2>Opening mistake patterns</h2>
      <p className="opening-mistakes-subtitle">
        Where you blunder in the opening, grouped by opening and move range
      </p>
      {openings.slice(0, 5).map(op => (
        <details key={op.opening} className="opening-mistakes-group" open={openings.length <= 2}>
          <summary className="opening-mistakes-summary">
            <span className="opening-mistakes-name">{op.opening}</span>
            <span className="opening-mistakes-stats">
              {op.mistakes} mistake{op.mistakes !== 1 ? 's' : ''} in {op.games} game{op.games !== 1 ? 's' : ''}
            </span>
          </summary>
          <div className="opening-hotspots">
            {op.hotspots.map(hs => (
              <div key={`${hs.move_range}-${hs.pattern}`} className="opening-hotspot">
                <div className="opening-hotspot-header">
                  <span className="opening-hotspot-range">Moves {hs.move_range}</span>
                  <span className="opening-hotspot-pattern">{hs.pattern}</span>
                  <span className="opening-hotspot-count">{hs.count}×</span>
                </div>
                {hs.tip && <p className="opening-hotspot-tip">{hs.tip}</p>}
                <HotspotMoments moments={hs.moments} />
              </div>
            ))}
          </div>
        </details>
      ))}
    </div>
  )
}
