import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Chess } from 'chess.js'
import { api } from '../../api'
import './home.css'

function validatePgn(text) {
  if (!text.trim()) return null
  try {
    const chess = new Chess()
    chess.loadPgn(text)
    if (chess.history().length === 0) return { valid: false, error: 'No moves found in PGN' }
    const h = chess.header()
    return { valid: true, moves: chess.history().length, white: h.White || '?', black: h.Black || '?' }
  } catch {
    return { valid: false, error: 'Invalid PGN format' }
  }
}

export default function Home() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState(null)
  const [username, setUsername] = useState('')
  const [imp, setImp] = useState({ state: 'idle' })   // idle | running | done | error
  const [impData, setImpData] = useState(null)
  const [recent, setRecent] = useState([])

  const [pgn, setPgn] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pgnState, setPgnState] = useState('idle')    // idle | analyzing | error
  const [pgnMsg, setPgnMsg] = useState(null)

  const importPoll = useRef(null)
  const pgnPoll = useRef(null)

  useEffect(() => () => {
    clearInterval(importPoll.current)
    clearInterval(pgnPoll.current)
  }, [])

  const loadProfile = () => api.get('/profile').then(r => {
    setProfile(r.data)
    setUsername(prev => prev || r.data.chesscom_username || '')
  }).catch(() => {})

  const loadRecent = () => api.get('/games/recent?limit=6')
    .then(r => setRecent(r.data)).catch(() => {})

  useEffect(() => { loadProfile(); loadRecent() }, [])

  // Parsing a PGN replays every move; don't redo it on each import-progress poll.
  const pgnValid = useMemo(() => validatePgn(pgn), [pgn])

  const handleImport = async () => {
    const u = username.trim()
    if (!u || imp.state === 'running') return
    setImp({ state: 'running' })
    setImpData({ imported: 0, fetched: 0, total_months: 0 })
    try {
      const res = await api.post('/import/chesscom', { username: u })
      const sid = res.data.status_id
      importPoll.current = setInterval(async () => {
        try {
          const s = (await api.get(`/import/chesscom/status/${sid}`)).data
          setImpData(s)
          if (s.status === 'complete') {
            clearInterval(importPoll.current)
            setImp({ state: 'done' })
            loadProfile(); loadRecent()
          } else if (s.status === 'error') {
            clearInterval(importPoll.current)
            setImp({ state: 'error', error: s.error })
          }
        } catch {
          clearInterval(importPoll.current)
          setImp({ state: 'error', error: 'Lost connection to the server' })
        }
      }, 700)
    } catch (e) {
      setImp({ state: 'error', error: e.response?.data?.detail || e.message })
    }
  }

  const handleAnalyze = async () => {
    if (!pgnValid?.valid) return
    setPgnState('analyzing'); setPgnMsg('Starting…')
    try {
      const res = await api.post('/analyze', { pgn })
      const sid = res.data.status_id
      pgnPoll.current = setInterval(async () => {
        try {
          const d = (await api.get(`/analyze/status/${sid}`)).data
          if (d.status === 'complete') {
            clearInterval(pgnPoll.current)
            navigate(`/review/${d.game_id}`)
          } else if (d.status === 'error' || d.status === 'interrupted') {
            clearInterval(pgnPoll.current)
            setPgnState('error'); setPgnMsg(d.error || 'Analysis interrupted')
          } else if (d.total > 0) {
            setPgnMsg(d.phase === 'coaching' || d.phase === 'explanations'
              ? `Coaching notes ${d.progress}/${d.total}…`
              : `Stockfish ${d.progress}/${d.total}…`)
          }
        } catch {
          clearInterval(pgnPoll.current)
          setPgnState('error'); setPgnMsg('Analysis could not complete')
        }
      }, 1200)
    } catch (e) {
      setPgnState('error'); setPgnMsg(e.response?.data?.detail || e.message)
    }
  }

  const total = profile?.games?.total
  const analyzed = profile?.games?.analyzed
  const importPct = impData?.total_months
    ? Math.round((impData.fetched / impData.total_months) * 100) : 0

  return (
    <div className="cr2 home">
      <header className="home-hero">
        <h1>Your chess, <span>reviewed.</span></h1>
        <p>Pull your whole chess.com history, review it with Stockfish, and learn why your moves go wrong.</p>
      </header>

      <section className="card import-card">
        <div className="import-row">
          <div className="import-field">
            <label>chess.com username</label>
            <input
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="your username"
              spellCheck={false}
              onKeyDown={e => e.key === 'Enter' && handleImport()}
            />
          </div>
          <button className="btn-primary" onClick={handleImport} disabled={imp.state === 'running' || !username.trim()}>
            {imp.state === 'running' ? 'Importing…' : 'Import my games'}
          </button>
        </div>

        {imp.state === 'running' && (
          <div className="import-progress">
            <div className="bar"><i style={{ width: `${importPct}%` }} /></div>
            <p>
              {impData?.month ? `Fetching ${impData.month} · ` : 'Reading your archives · '}
              <b>{impData?.imported ?? 0}</b> imported
              {impData?.total_months ? ` · month ${impData.fetched}/${impData.total_months}` : ''}
            </p>
          </div>
        )}
        {imp.state === 'done' && (
          <div className="import-done">
            Imported <b>{impData?.imported ?? 0}</b> new games.{' '}
            <Link to="/games" className="link">Browse your games →</Link>
          </div>
        )}
        {imp.state === 'error' && <div className="import-error">{imp.error || 'Import failed'}</div>}

        {total != null && (
          <div className="import-stats">
            <span><b>{total}</b> games in your library</span>
            <span className="dot">·</span>
            <span><b>{analyzed}</b> deeply analyzed</span>
          </div>
        )}
      </section>

      <div className="home-cols">
        <section className="card recent-card">
          <div className="card-head">
            <h2>Recent games</h2>
            <Link to="/games" className="link">All games →</Link>
          </div>
          {recent.length === 0 ? (
            <p className="muted-note">Import your games to get started.</p>
          ) : (
            <ul className="recent-list">
              {recent.map(g => (
                <li key={g.id}>
                  <Link to={`/review/${g.id}`} className="recent-item">
                    <span className="ri-players">{g.white} <i>vs</i> {g.black}</span>
                    <span className="ri-meta">
                      {g.opening && <span className="ri-opening">{g.opening}</span>}
                      <span className={`ri-res ${g.result === '1-0' ? 'w' : g.result === '0-1' ? 'l' : 'd'}`}>{g.result}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card paste-card">
          <button className="paste-toggle" onClick={() => setPasteOpen(o => !o)}>
            <h2>Analyze a single PGN</h2>
            <span className={`chev ${pasteOpen ? 'open' : ''}`}>▾</span>
          </button>
          {pasteOpen && (
            <div className="paste-body">
              <textarea
                value={pgn}
                onChange={e => setPgn(e.target.value)}
                placeholder={'[Event "..."]\n\n1. e4 e5 2. Nf3 ...'}
                rows={7}
              />
              {pgnValid && (
                <div className={`pgn-val ${pgnValid.valid ? 'ok' : 'bad'}`}>
                  {pgnValid.valid ? `${pgnValid.white} vs ${pgnValid.black} · ${pgnValid.moves} moves` : pgnValid.error}
                </div>
              )}
              <button className="btn-primary" onClick={handleAnalyze}
                disabled={pgnState === 'analyzing' || !pgnValid?.valid}>
                {pgnState === 'analyzing' ? (pgnMsg || 'Analyzing…') : 'Analyze game'}
              </button>
              {pgnState === 'error' && <div className="import-error">{pgnMsg}</div>}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
