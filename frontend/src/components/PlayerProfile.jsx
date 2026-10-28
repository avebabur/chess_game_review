import { Link } from 'react-router-dom'
import { PALETTE } from '../palette'

function PatternBar({ item, maxCount, variant = 'weakness' }) {
  const width = maxCount > 0 ? Math.round((item.count / maxCount) * 100) : 0
  const fillColor = variant === 'strength'
    ? PALETTE.good
    : variant === 'theme'
      ? PALETTE.gold
      : PALETTE.red

  return (
    <div className="player-pattern-bar-row">
      <span className="player-pattern-bar-label">{item.pattern}</span>
      <div className="player-pattern-bar-bg">
        <div
          className="player-pattern-bar-fill"
          style={{ width: `${width}%`, backgroundColor: fillColor }}
        />
      </div>
      <span className="player-pattern-bar-count">{item.count}</span>
    </div>
  )
}

function MomentLinks({ moments }) {
  if (!moments?.length) return null

  return (
    <div className="player-pattern-moments">
      {moments.slice(0, 5).map(m => (
        <Link
          key={`${m.game_id}-${m.move_index}`}
          to={`/review/${m.game_id}?move=${m.move_index}`}
          className="player-pattern-moment-link"
        >
          game #{m.game_id}, move {m.move_number}
          {m.user_move ? ` (${m.user_move})` : ''}
        </Link>
      ))}
    </div>
  )
}

function PatternSection({ title, items, variant, emptyText, practiceTheme }) {
  if (!items?.length) {
    return emptyText ? <p className="no-data">{emptyText}</p> : null
  }

  const maxCount = Math.max(...items.map(i => i.count), 1)
  const top = items[0]

  return (
    <div className="player-pattern-section">
      <div className="player-pattern-chart">
        {items.slice(0, 6).map(item => (
          <PatternBar key={item.pattern} item={item} maxCount={maxCount} variant={variant} />
        ))}
      </div>
      {top && (
        <div className="player-pattern-spotlight">
          <div className="player-pattern-spotlight-header">
            <span className="player-pattern-spotlight-name">{top.pattern}</span>
            <span className="player-pattern-spotlight-meta">
              {top.count}× in {top.games} game{top.games !== 1 ? 's' : ''}
            </span>
          </div>
          {top.tip && <p className="player-pattern-spotlight-tip">{top.tip}</p>}
          {practiceTheme && (
            <Link to={`/puzzles?theme=${encodeURIComponent(practiceTheme)}`} className="player-pattern-practice-btn">
              Practice {practiceTheme}
            </Link>
          )}
          <MomentLinks moments={top.moments} />
        </div>
      )}
      {items.length > 1 && (
        <details className="player-pattern-more">
          <summary>All {title.toLowerCase()} ({items.length})</summary>
          <ul className="player-pattern-more-list">
            {items.map(item => (
              <li key={item.pattern} className="player-pattern-more-item">
                <div className="player-pattern-more-row">
                  <span>{item.pattern}</span>
                  <span className="player-pattern-more-count">{item.count}×</span>
                </div>
                {item.tip && <p className="player-pattern-more-tip">{item.tip}</p>}
                <MomentLinks moments={item.moments} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export default function PlayerProfile({ patterns, loading, recommendations }) {
  if (loading) {
    return (
      <div className="player-profile-card player-profile-loading">
        <div className="skeleton skeleton-block" style={{ height: 120 }} />
      </div>
    )
  }

  if (!patterns) return null

  const hasData = (
    patterns.recurring_weaknesses?.length > 0
    || patterns.improvement_areas?.length > 0
    || patterns.strength_areas?.length > 0
  )

  if (!hasData) {
    return (
      <div className="player-profile-card">
        <h2>Your Patterns</h2>
        <p className="no-data">
          Cross-game patterns appear after you analyze a few games with critical moments.
        </p>
      </div>
    )
  }

  const practiceTheme = recommendations?.theme

  return (
    <div className="player-profile-card">
      <h2>Your Patterns</h2>
      <p className="player-profile-subtitle">
        Recurring mistakes and strengths across all your analyzed games
      </p>

      {patterns.recurring_weaknesses?.length > 0 && (
        <>
          <h3 className="player-profile-section-title">Recurring weaknesses</h3>
          <PatternSection
            title="Weaknesses"
            items={patterns.recurring_weaknesses}
            variant="weakness"
            practiceTheme={practiceTheme}
          />
        </>
      )}

      {patterns.improvement_areas?.length > 0 && (
        <>
          <h3 className="player-profile-section-title">Themes to study</h3>
          <PatternSection
            title="Themes"
            items={patterns.improvement_areas}
            variant="theme"
            practiceTheme={patterns.improvement_areas[0]?.pattern}
          />
        </>
      )}

      {patterns.strength_areas?.length > 0 && (
        <>
          <h3 className="player-profile-section-title">What you do well</h3>
          <PatternSection
            title="Strengths"
            items={patterns.strength_areas}
            variant="strength"
          />
        </>
      )}
    </div>
  )
}
