import { api } from './api'

const STORAGE_KEY = 'chess_reanalyze_session'

export function saveReanalyzeSession(session) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    ...session,
    startedAt: Date.now(),
  }))
  window.dispatchEvent(new CustomEvent('chess-reanalyze-session'))
}

export function clearReanalyzeSession() {
  sessionStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new CustomEvent('chess-reanalyze-session'))
}

export function loadReanalyzeSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function dispatchReanalyzeProgress(data) {
  window.dispatchEvent(new CustomEvent('chess-reanalyze-progress', { detail: data }))
}

export function stopPolling(pollRef) {
  if (pollRef?.current) {
    clearInterval(pollRef.current)
    pollRef.current = null
  }
}

async function tryRecoverReanalyzeAfter404(session) {
  if (!session) return false

  if (session.scope === 'one' && session.gameId != null) {
    try {
      const res = await api.get(`/review/${session.gameId}`)
      const updatedAt = res.data?.analysis_updated_at
      const before = session.analysisUpdatedAtBefore ?? null
      if (updatedAt && updatedAt !== before) {
        dispatchReanalyzeProgress({
          status: 'complete',
          current_game_id: session.gameId,
        })
        clearReanalyzeSession()
        return true
      }
      if (!before && res.data?.analysis) {
        dispatchReanalyzeProgress({
          status: 'complete',
          current_game_id: session.gameId,
        })
        clearReanalyzeSession()
        return true
      }
    } catch {
      /* fall through */
    }
  }

  if (session.scope === 'all' && session.statusId != null) {
    try {
      const res = await api.get(`/games/reanalyze-all/status/${session.statusId}`)
      dispatchReanalyzeProgress(res.data)
      if (res.data.status === 'complete' || res.data.status === 'error') {
        clearReanalyzeSession()
      }
      return res.data.status === 'complete'
    } catch {
      /* fall through */
    }
  }

  return false
}

async function handleReanalyzePollError(statusId, pollRef) {
  const session = loadReanalyzeSession()
  if (session?.statusId === statusId) {
    const recovered = await tryRecoverReanalyzeAfter404(session)
    if (recovered) {
      stopPolling(pollRef)
      return
    }
  }
  stopPolling(pollRef)
  clearReanalyzeSession()
  dispatchReanalyzeProgress({ status: 'error' })
}

export function startReanalyzePolling(statusId, pollRef) {
  stopPolling(pollRef)
  pollRef.current = setInterval(async () => {
    try {
      const res = await api.get(`/games/reanalyze-all/status/${statusId}`)
      const data = res.data
      dispatchReanalyzeProgress(data)
      if (data.status === 'complete' || data.status === 'error') {
        stopPolling(pollRef)
        clearReanalyzeSession()
      }
    } catch (err) {
      if (err.response?.status === 404) {
        await handleReanalyzePollError(statusId, pollRef)
        return
      }
      await handleReanalyzePollError(statusId, pollRef)
    }
  }, 1500)
}

export async function fetchReanalyzeStatus(statusId) {
  const res = await api.get(`/games/reanalyze-all/status/${statusId}`)
  return res.data
}

export async function ensureReanalyzePolling(pollRef) {
  const session = loadReanalyzeSession()
  if (!session?.statusId) {
    stopPolling(pollRef)
    return null
  }

  try {
    const data = await fetchReanalyzeStatus(session.statusId)
    dispatchReanalyzeProgress(data)
    if (data.status === 'analyzing') {
      startReanalyzePolling(session.statusId, pollRef)
      return { session, data }
    }
    if (data.status === 'complete' || data.status === 'error') {
      stopPolling(pollRef)
      clearReanalyzeSession()
    }
    return { session, data }
  } catch (err) {
    if (err.response?.status === 404) {
      const recovered = await tryRecoverReanalyzeAfter404(session)
      if (recovered) {
        stopPolling(pollRef)
        return { session, data: { status: 'complete' } }
      }
    }
    stopPolling(pollRef)
    clearReanalyzeSession()
    return null
  }
}

export function formatReanalyzeLabel(session, progress) {
  if (!session) return null
  if (session.scope === 'one') {
    return formatReanalyzeDetail(progress) || 'Re-analyzing this game…'
  }
  const gi = progress?.game_index ?? progress?.progress ?? 0
  const tg = progress?.total_games ?? progress?.total ?? session.total ?? '?'
  const detail = formatReanalyzeDetail(progress)
  const gameLabel = `game ${gi + 1} of ${tg}`
  return detail ? `Re-analyzing ${gameLabel} — ${detail}` : `Re-analyzing ${gameLabel}…`
}

export function formatReanalyzeDetail(progress) {
  if (!progress || progress.status !== 'analyzing') return ''
  const moveTotal = progress.move_total ?? progress.total ?? 0
  const moveProgress = progress.move_progress ?? progress.progress ?? 0
  if (progress.phase === 'coaching' && moveTotal > 0) {
    return `coaching ${moveProgress} of ${moveTotal}`
  }
  if (progress.phase === 'stockfish' && moveTotal > 0) {
    return `Stockfish move ${moveProgress} of ${moveTotal}`
  }
  if (progress.move_count > 0) {
    return `${progress.move_count} moves in game`
  }
  return 'starting…'
}
