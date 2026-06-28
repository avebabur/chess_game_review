export default function ImprovementChart({ timeline, motifTrends, loading }) {
  if (loading) {
    return (
      <div className="improvement-chart-card">
        <div className="skeleton skeleton-block" style={{ height: 140 }} />
      </div>
    )
  }

  const points = timeline || []
  if (!points.length) {
    return (
      <div className="improvement-chart-card">
        <h2>Improvement over time</h2>
        <p className="no-data">Trend charts appear as you analyze more games over time.</p>
      </div>
    )
  }

  const accValues = points.map(p => p.avg_accuracy).filter(v => v != null)
  const blunderValues = points.map(p => p.blunders)
  const maxBlunders = Math.max(...blunderValues, 1)
  const minAcc = accValues.length ? Math.min(...accValues) : 0
  const maxAcc = accValues.length ? Math.max(...accValues) : 100
  const accRange = Math.max(maxAcc - minAcc, 10)

  const width = 320
  const height = 100
  const pad = 8

  const accPath = points.map((p, i) => {
    const x = pad + (i / Math.max(points.length - 1, 1)) * (width - pad * 2)
    const acc = p.avg_accuracy ?? minAcc
    const y = height - pad - ((acc - minAcc) / accRange) * (height - pad * 2)
    return `${i === 0 ? 'M' : 'L'}${x},${y}`
  }).join(' ')

  const blunderBars = points.map((p, i) => {
    const x = pad + (i / Math.max(points.length - 1, 1)) * (width - pad * 2)
    const barH = (p.blunders / maxBlunders) * (height * 0.25)
    return { x, barH, week: p.week, blunders: p.blunders }
  })

  const topMotif = motifTrends?.[0]

  return (
    <div className="improvement-chart-card">
      <h2>Improvement over time</h2>
      <div className="improvement-chart-wrap">
        <svg viewBox={`0 0 ${width} ${height + 24}`} className="improvement-chart-svg">
          {blunderBars.map((b, i) => (
            <rect
              key={i}
              x={b.x - 4}
              y={height - b.barH}
              width={8}
              height={b.barH}
              fill="rgba(231, 76, 60, 0.25)"
              rx={2}
            />
          ))}
          {accValues.length > 1 && (
            <path d={accPath} fill="none" stroke="#27ae60" strokeWidth="2.5" />
          )}
          {points.map((p, i) => {
            const x = pad + (i / Math.max(points.length - 1, 1)) * (width - pad * 2)
            return (
              <text key={p.week} x={x} y={height + 16} textAnchor="middle" className="improvement-chart-label">
                {p.week.slice(5)}
              </text>
            )
          })}
        </svg>
        <div className="improvement-chart-legend">
          <span className="legend-acc">Accuracy trend</span>
          <span className="legend-blunder">Blunders / week</span>
        </div>
      </div>

      {topMotif && (
        <div className="improvement-motif-trend">
          <h3>Most missed pattern: {topMotif.label}</h3>
          <p>{topMotif.total} misses total{topMotif.tip ? ` — ${topMotif.tip}` : ''}</p>
        </div>
      )}

      <ul className="improvement-week-list">
        {points.slice(-6).reverse().map(p => (
          <li key={p.week}>
            <span>{p.week}</span>
            <span>{p.games} game{p.games !== 1 ? 's' : ''}</span>
            <span>{p.avg_accuracy != null ? `${p.avg_accuracy}% acc` : '—'}</span>
            <span>{p.blunders} blunder{p.blunders !== 1 ? 's' : ''}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
