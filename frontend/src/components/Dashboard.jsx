import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import PlayerProfile from './PlayerProfile'
import StudyPlan from './StudyPlan'
import OpeningMistakes from './OpeningMistakes'
import ImprovementChart from './ImprovementChart'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [patterns, setPatterns] = useState(null)
  const [recommendations, setRecommendations] = useState(null)
  const [openingMistakes, setOpeningMistakes] = useState(null)
  const [timeline, setTimeline] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    const opts = { signal: controller.signal }
    Promise.all([
      api.get('/dashboard', opts),
      api.get('/player-patterns', opts),
      api.get('/study/recommendations', opts),
      api.get('/opening-mistakes', opts),
      api.get('/improvement/timeline', opts),
    ]).then(([statsRes, patternsRes, studyRes, openingRes, timelineRes]) => {
      setStats(statsRes.data)
      setPatterns(patternsRes.data)
      setRecommendations(studyRes.data)
      setOpeningMistakes(openingRes.data)
      setTimeline(timelineRes.data)
      setLoading(false)
    }).catch((e) => {
      if (e.name !== 'CanceledError' && e.code !== 'ERR_CANCELED') {
        setLoading(false)
      }
    })
    return () => controller.abort()
  }, [])

  if (loading) return (
    <div className="dashboard-skeleton">
      <div className="skeleton skeleton-line short" style={{ height: 28, marginBottom: 24 }} />
      <div className="skeleton skeleton-summary" />
      <div className="skeleton skeleton-section-title" style={{ marginTop: 32 }} />
      {[1, 2, 3].map(i => <div key={i} className="skeleton skeleton-block" />)}
    </div>
  )
  if (!stats) return (
    <div className="error-box">
      <p>Couldn't reach the server</p>
      <p className="error-hint">Make sure the analysis server is running, then try again</p>
      <button type="button" onClick={() => window.location.reload()}>Try Again</button>
    </div>
  )

  const worstTheme = stats.weakness_profile.length > 0 ? stats.weakness_profile[0] : null

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>

      <div className="dashboard-summary">
        <div className="summary-primary">
          <span className="summary-accuracy">{stats.overall_accuracy}%</span>
          <span className="summary-accuracy-label">puzzle accuracy</span>
          <span className="summary-detail">{stats.puzzles_solved} of {stats.puzzles_attempted} solved</span>
        </div>
        <div className="summary-secondary">
          <div className="summary-stat">
            <span className="summary-stat-value">{stats.games_analyzed}</span>
            <span className="summary-stat-label">games</span>
          </div>
          <div className="summary-stat">
            <span className="summary-stat-value">{stats.total_puzzles}</span>
            <span className="summary-stat-label">puzzles</span>
          </div>
          {worstTheme && (
            <div className="summary-stat summary-stat-weak">
              <span className="summary-stat-value">{worstTheme.accuracy}%</span>
              <span className="summary-stat-label">worst: {worstTheme.theme}</span>
            </div>
          )}
        </div>
      </div>

      <StudyPlan recommendations={recommendations} loading={false} />

      <PlayerProfile patterns={patterns} loading={false} recommendations={recommendations} />

      <ImprovementChart
        timeline={timeline?.timeline}
        motifTrends={timeline?.motif_trends}
        loading={false}
      />

      <OpeningMistakes data={openingMistakes} loading={false} />

      <h2>Recurring Misses</h2>
      {(!stats.recent_misses || stats.recent_misses.length === 0) ? (
        <p className="no-data">Missed tactic patterns appear after you analyze a few games</p>
      ) : (
        <div className="weakness-list">
          {stats.recent_misses.map(m => (
            <div key={m.motif} className="weakness-row">
              <span className="weakness-theme">{m.motif}</span>
              <span className="weakness-count">{m.count} miss{m.count !== 1 ? 'es' : ''} recently</span>
            </div>
          ))}
        </div>
      )}

      <h2>Weakness Profile</h2>
      {stats.weakness_profile.length === 0 ? (
        <p className="no-data">Your weakness breakdown will appear as you solve puzzles</p>
      ) : (
        <div className="weakness-list">
          {stats.weakness_profile.map(w => (
            <div key={w.theme} className="weakness-row">
              <span className="weakness-theme">{w.theme}</span>
              <div className="weakness-bar-bg">
                <div
                  className="weakness-bar-fill"
                  style={{
                    width: `${w.accuracy}%`,
                    backgroundColor: w.accuracy < 40 ? '#e74c3c' : w.accuracy < 70 ? '#f39c12' : '#27ae60',
                  }}
                />
              </div>
              <span className="weakness-accuracy">{w.accuracy}%</span>
              <span className="weakness-count">{w.solved}/{w.shown}</span>
              <Link to={`/puzzles?theme=${encodeURIComponent(w.theme)}`} className="weakness-practice-link">
                practice
              </Link>
            </div>
          ))}
        </div>
      )}

      <h2>Opening Repertoire</h2>
      {(!stats.opening_profile || stats.opening_profile.length === 0) ? (
        <p className="no-data">Opening stats will show up after you analyze a few games</p>
      ) : (
        <div className="opening-list">
          {stats.opening_profile.map(o => (
            <div key={o.opening} className="opening-row">
              <span className="opening-name">{o.opening}</span>
              <div className="opening-stats">
                <span className="opening-games">{o.games} game{o.games !== 1 ? 's' : ''}</span>
                <span className="opening-record">
                  <span className="opening-win">{o.wins}W</span>
                  <span className="opening-draw">{o.draws}D</span>
                  <span className="opening-loss">{o.losses}L</span>
                </span>
                <span className={`opening-winrate ${o.win_rate >= 50 ? 'good' : 'bad'}`}>
                  {o.win_rate}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
