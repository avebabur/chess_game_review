import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Link, useLocation } from 'react-router-dom'
import ReanalyzeBanner from '../../components/ReanalyzeBanner'
import ErrorBoundary from '../../components/ErrorBoundary'
import '../../App.css'
import '../../styles/shell.css'

const Home = lazy(() => import('../../components/home/Home'))
const GamesPage = lazy(() => import('../../components/games/GamesPage'))
const GameReview = lazy(() => import('../../components/GameReview'))
const PuzzleMode = lazy(() => import('../../components/PuzzleMode'))
const Dashboard = lazy(() => import('../../components/Dashboard'))

const NAV = [
  { to: '/', label: 'Home', end: true },
  { to: '/games', label: 'Games' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/puzzles', label: 'Puzzles' },
]

function NotFound() {
  return (
    <div className="cr2" style={{ padding: 48, textAlign: 'center' }}>
      <p style={{ fontSize: 18, fontWeight: 600 }}>Page not found</p>
      <p style={{ marginTop: 8 }}>
        <Link to="/" className="link">Home</Link>{' · '}
        <Link to="/games" className="link">Your games</Link>
      </p>
    </div>
  )
}

function Nav() {
  const location = useLocation()
  return (
    <div className="cr2">
      <nav className="nav2">
        <Link to="/" className="nav2-brand">
          <span className="nav2-logo">♞</span> Chess Review
        </Link>
        <div className="nav2-links">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => {
                const active = isActive
                  || (item.to === '/games' && location.pathname.startsWith('/review/'))
                return active ? 'nav2-link on' : 'nav2-link'
              }}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}

function RoutedContent() {
  const location = useLocation()
  return (
    <ErrorBoundary key={location.pathname}>
      <Suspense fallback={<div className="cr2"><div className="route-loading">Loading...</div></div>}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/games" element={<GamesPage />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/review/:gameId" element={<GameReview />} />
          <Route path="/puzzles" element={<PuzzleMode />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  )
}

export default function ReviewApp() {
  return (
    <BrowserRouter>
      <div className="app">
        <Nav />
        <ReanalyzeBanner />
        <main className="main-content">
          <RoutedContent />
        </main>
      </div>
    </BrowserRouter>
  )
}
