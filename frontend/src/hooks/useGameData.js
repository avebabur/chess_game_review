import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

/**
 * Fetch a single game's analysis payload from `/review/{gameId}`.
 *
 * Owns only the data lifecycle (loading flag, error flag, latest payload).
 * Anything the parent wants to reset alongside a reload — exploration state,
 * variations, current move — is the parent's responsibility, because those
 * concerns belong to other hooks (`useExploreEval`, future `useReviewVariations`).
 *
 * The initial fetch supports abort via `AbortController` so a fast re-mount
 * (gameId change while a request is in flight) does not flash stale data.
 *
 * Returns:
 *   game        — full server payload or null while loading
 *   loading     — bool, true while a fetch is in progress
 *   loadError   — bool, true on non-abort failure
 *   reload(opts) — re-fetch the game (no abort guard); opts.silent skips the
 *                  loading-state flash for background refreshes
 *   setGame(updater) — escape hatch for in-place mutations (used when a single
 *                  coaching moment is re-analysed and we splice it in)
 */
export function useGameData(gameId) {
  const [game, setGame] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  const fetchGame = useCallback((signal) => {
    setLoading(true)
    setLoadError(false)
    setGame(null)
    api
      .get(`/review/${gameId}`, { signal })
      .then(res => setGame(res.data))
      .catch((e) => {
        if (
          !signal.aborted
          && e.name !== 'CanceledError'
          && e.code !== 'ERR_CANCELED'
        ) {
          setLoadError(true)
        }
      })
      .finally(() => {
        if (!signal.aborted) setLoading(false)
      })
  }, [gameId])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => fetchGame(controller.signal), 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [fetchGame])

  const reload = useCallback(() => {
    setLoading(true)
    setLoadError(false)
    return api.get(`/review/${gameId}`)
      .then(res => {
        setGame(res.data)
        return res.data
      })
      .catch(() => {
        setLoadError(true)
        return null
      })
      .finally(() => setLoading(false))
  }, [gameId])

  return { game, loading, loadError, reload, setGame }
}
