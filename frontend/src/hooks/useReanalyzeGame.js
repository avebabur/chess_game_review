import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import {
  clearReanalyzeSession,
  ensureReanalyzePolling,
  loadReanalyzeSession,
  saveReanalyzeSession,
  stopPolling,
} from '../reanalyzeSession'

/**
 * Encapsulates the "re-analyze this whole game" flow.
 *
 * State transitions:
 *   idle → running (user confirms + POST accepted)
 *   running → done   (cross-tab progress reports complete)
 *   running → error  (API failure or backend reports error)
 *
 * The hook listens for `chess-reanalyze-progress` window events so progress
 * keeps streaming even if the user opens this game from another tab where
 * the re-analysis was triggered. `onComplete` runs once after the analysis
 * finishes — pass it your `reloadGame` callback to refresh the local copy.
 */
export function useReanalyzeGame(gameId, onComplete) {
  const [status, setStatus] = useState(null)
  const [progress, setProgress] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    const gid = Number(gameId)
    const sync = () => {
      const session = loadReanalyzeSession()
      if (session?.scope === 'one' && Number(session.gameId) === gid) {
        setStatus('running')
      }
    }
    const onProgress = (data) => {
      const session = loadReanalyzeSession()
      const matches = session?.scope === 'one' && Number(session.gameId) === gid
      if (data.status === 'analyzing' && matches) {
        setStatus('running')
        setProgress(data)
      } else if (data.status === 'complete' && (matches || Number(data.current_game_id) === gid)) {
        setStatus('done')
        setProgress(null)
        onComplete?.()
      } else if (data.status === 'error' && matches) {
        setStatus('error')
        setProgress(null)
      }
    }
    const onProgressEvent = (e) => onProgress(e.detail)

    const kickPolling = () => {
      sync()
      ensureReanalyzePolling(pollRef)
    }

    window.addEventListener('chess-reanalyze-session', kickPolling)
    window.addEventListener('chess-reanalyze-progress', onProgressEvent)
    kickPolling()

    return () => {
      stopPolling(pollRef)
      window.removeEventListener('chess-reanalyze-session', kickPolling)
      window.removeEventListener('chess-reanalyze-progress', onProgressEvent)
    }
  }, [gameId, onComplete])

  const trigger = useCallback(async () => {
    if (status === 'running') return
    if (!window.confirm(
      'Re-analyze this game with the latest engine and coaching notes?\n\n'
      + 'This may take a minute. Puzzle progress for this game will reset.',
    )) {
      return
    }
    setStatus('running')
    setProgress({ status: 'analyzing', phase: 'stockfish', progress: 0, total: 0 })
    try {
      const res = await api.post(`/games/${gameId}/reanalyze`)
      const { status_id: statusId, analysis_updated_at_before: analysisUpdatedAtBefore } = res.data
      if (!statusId) {
        setStatus(null)
        setProgress(null)
        return
      }
      saveReanalyzeSession({
        statusId,
        scope: 'one',
        gameId: Number(gameId),
        total: 1,
        analysisUpdatedAtBefore: analysisUpdatedAtBefore ?? null,
      })
      ensureReanalyzePolling(pollRef)
    } catch {
      clearReanalyzeSession()
      stopPolling(pollRef)
      setStatus('error')
      setProgress(null)
    }
  }, [gameId, status])

  return { status, progress, trigger }
}
