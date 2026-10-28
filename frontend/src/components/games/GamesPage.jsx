import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import './games.css'

const COLORS = [{ k: 'all', l: 'All' }, { k: 'white', l: 'White' }, { k: 'black', l: 'Black' }]
const RESULTS = [{ k: 'all', l: 'All' }, { k: 'win', l: 'Wins' }, { k: 'loss', l: 'Losses' }, { k: 'draw', l: 'Draws' }]
const TIMES = [{ k: 'all', l: 'All' }, { k: 'bullet', l: 'Bullet' }, { k: 'blitz', l: 'Blitz' }, { k: 'rapid', l: 'Rapid' }, { k: 'daily', l: 'Daily' }]

function povResult(g) {
  if (g.result === '1/2-1/2') return 'draw'
  if (g.result === '1-0') return g.user_color === 'black' ? 'loss' : g.user_color === 'white' ? 'win' : 'unknown'
  if (g.result === '0-1') return g.user_color === 'white' ? 'loss' : g.user_color === 'black' ? 'win' : 'unknown'
  return 'unknown'
}
// Imported histories run to hundreds of games; render them a page at a time.
const PAGE = 60

const RES_LABEL = { win: 'Win', loss: 'Loss', draw: 'Draw', unknown: g => g.result }

export default function GamesPage() {
  const navigate = useNavigate()
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [color, setColor] = useState('all')
  const [result, setResult] = useState('all')
  const [time, setTime] = useState('all')
  const [q, setQ] = useState('')
  const [analyzingId, setAnalyzingId] = useState(null)
  const [analyzeError, setAnalyzeError] = useState(null)
  const [page, setPage] = useState({ key: '', n: PAGE })
  const poll = useRef(null)

  useEffect(() => () => clearInterval(poll.current), [])

  useEffect(() => {
    const ctrl = new AbortController()
    api.get('/games/grid', { signal: ctrl.signal })
      .then(r => { setGames(r.data); setLoading(false) })
      .catch(e => { if (e.name !== 'CanceledError') { setError(true); setLoading(false) } })
    return () => ctrl.abort()
  }, [])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return games.filter(g => {
      if (color !== 'all' && g.user_color !== color) return false
      if (time !== 'all' && g.time_class !== time) return false
      if (result !== 'all' && povResult(g) !== result) return false
      if (needle && !(g.opening || '').toLowerCase().includes(needle)) return false
      return true
    })
  }, [games, color, result, time, q])

  // Changing any filter starts again from the first page.
  const filterKey = `${color}|${result}|${time}|${q}`
  const visible = page.key === filterKey ? page.n : PAGE

  const fail = (msg) => {
    clearInterval(poll.current)
    setAnalyzingId(null)
    setAnalyzeError(msg)
  }

  const openGame = (g) => {
    if (g.analyzed) { navigate(`/review/${g.id}`); return }
    if (analyzingId) return
    setAnalyzingId(g.id)
    setAnalyzeError(null)
    api.post(`/games/${g.id}/analyze`).then(res => {
      const sid = res.data.status_id
      poll.current = setInterval(async () => {
        try {
          const d = (await api.get(`/analyze/status/${sid}`)).data
          if (d.status === 'complete') { clearInterval(poll.current); navigate(`/review/${g.id}`) }
          else if (d.status === 'error' || d.status === 'interrupted') fail(d.error || 'Analysis failed')
        } catch { fail('Lost connection to the server') }
      }, 1100)
    }).catch(e => fail(e.response?.data?.detail || 'Could not start the analysis'))
  }

  const counts = useMemo(() => ({
    total: games.length,
    shown: filtered.length,
  }), [games, filtered])

  return (
    <div className="cr2 games">
      <header className="games-head">
        <h1>Your Games</h1>
        <span className="games-count">{counts.shown} of {counts.total}</span>
      </header>

      <div className="games-filters">
        <div className="seg">{COLORS.map(c => <button key={c.k} className={color === c.k ? 'on' : ''} onClick={() => setColor(c.k)}>{c.l}</button>)}</div>
        <div className="seg">{RESULTS.map(c => <button key={c.k} className={result === c.k ? 'on' : ''} onClick={() => setResult(c.k)}>{c.l}</button>)}</div>
        <div className="games-times">{TIMES.map(c => <button key={c.k} className={`chip ${time === c.k ? 'on' : ''}`} onClick={() => setTime(c.k)}>{c.l}</button>)}</div>
        <input className="games-search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search openings…" />
      </div>

      {analyzeError && <div className="games-error" role="alert">{analyzeError}</div>}

      {loading ? (
        <div className="games-skel">{Array.from({ length: 8 }).map((_, i) => <div key={i} className="gskel" />)}</div>
      ) : error ? (
        <div className="games-empty">Couldn't load games — is the server running?</div>
      ) : filtered.length === 0 ? (
        <div className="games-empty">No games match these filters.</div>
      ) : (
        <div className="games-list">
          {filtered.slice(0, visible).map(g => {
            const pov = povResult(g)
            const analyzing = analyzingId === g.id
            return (
              <button key={g.id} className="game-row2" onClick={() => openGame(g)} disabled={analyzing}>
                <span className={`gr-color ${g.user_color || ''}`} title={g.user_color ? `You played ${g.user_color}` : ''} />
                <span className="gr-players">
                  <span className="gr-names">{g.white} <i>vs</i> {g.black}</span>
                  <span className="gr-sub">
                    {g.opening || 'Unknown opening'}
                    {g.opp_rating ? <span className="gr-opp"> · opp {g.opp_rating}</span> : null}
                  </span>
                </span>
                {g.time_class && <span className="gr-tc">{g.time_class}</span>}
                <span className={`gr-res ${pov}`}>{typeof RES_LABEL[pov] === 'function' ? RES_LABEL[pov](g) : RES_LABEL[pov]}</span>
                <span className="gr-date">{(g.date || '').replaceAll('.', '/')}</span>
                <span className="gr-action">
                  {analyzing ? <span className="gr-spin" /> : g.analyzed
                    ? <span className="gr-go">Review →</span>
                    : <span className="gr-analyze">Analyze</span>}
                </span>
              </button>
            )
          })}
          {filtered.length > visible && (
            <button className="games-more" onClick={() => setPage({ key: filterKey, n: visible + PAGE })}>
              Show {Math.min(PAGE, filtered.length - visible)} more
            </button>
          )}
        </div>
      )}
    </div>
  )
}
