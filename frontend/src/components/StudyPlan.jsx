import { Link } from 'react-router-dom'

function MomentLinks({ moments }) {
  if (!moments?.length) return null
  return (
    <div className="study-plan-moments">
      {moments.slice(0, 4).map(m => (
        <Link
          key={`${m.game_id}-${m.move_index}`}
          to={`/review/${m.game_id}?move=${m.move_index}`}
          className="study-plan-moment-link"
        >
          game #{m.game_id}, move {m.move_number}
        </Link>
      ))}
    </div>
  )
}

export default function StudyPlan({ recommendations, loading }) {
  if (loading) {
    return (
      <div className="study-plan-card study-plan-loading">
        <div className="skeleton skeleton-block" style={{ height: 100 }} />
      </div>
    )
  }
  if (!recommendations?.priority) {
    return (
      <div className="study-plan-card">
        <h2>What to study next</h2>
        <p className="no-data">Analyze a few games to get a personalized study plan.</p>
      </div>
    )
  }

  const { priority, theme, puzzles, concept_drills, secondary_focus } = recommendations

  return (
    <div className="study-plan-card">
      <h2>What to study next</h2>
      <div className="study-plan-priority">
        <span className="study-plan-badge">#1 priority</span>
        <h3>{priority.pattern}</h3>
        <p className="study-plan-meta">
          {priority.count}× across {priority.games || 'your'} game{(priority.games || 0) !== 1 ? 's' : ''}
          {priority.accuracy != null ? ` · ${priority.accuracy}% puzzle accuracy` : ''}
        </p>
        {priority.tip && <p className="study-plan-tip">{priority.tip}</p>}
        <MomentLinks moments={priority.moments} />
        <div className="study-plan-actions">
          {theme && (
            <Link to={`/puzzles?theme=${encodeURIComponent(theme)}`} className="study-plan-btn primary">
              Practice {theme} puzzles ({puzzles?.length || 0} due)
            </Link>
          )}
          <Link to="/puzzles" className="study-plan-btn">All puzzles</Link>
        </div>
      </div>

      {concept_drills?.length > 0 && (
        <div className="study-plan-concepts">
          <h3>Concept review</h3>
          <p className="study-plan-concepts-note">
            Spaced repetition for patterns — review these ideas, not just positions.
          </p>
          <ul className="study-plan-concept-list">
            {concept_drills.map(c => (
              <li key={c.concept_key} className="study-plan-concept-item">
                <span>{c.label}</span>
                <span className="study-plan-concept-meta">
                  {c.accuracy}% · due now
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {secondary_focus?.length > 0 && (
        <details className="study-plan-secondary">
          <summary>Also worth studying ({secondary_focus.length})</summary>
          <ul>
            {secondary_focus.map(s => (
              <li key={s.pattern}>
                {s.pattern} ({s.count}×)
                {s.theme && (
                  <Link to={`/puzzles?theme=${encodeURIComponent(s.theme)}`}> · practice</Link>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
