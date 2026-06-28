import { useCallback, useState } from 'react'
import { api } from '../api'

/**
 * Re-analyze a single coaching moment (cheaper than a full-game rerun).
 *
 * The backend returns the refreshed moment plus recomputed `concept_threads`
 * and both moment lists (thread suppression spans the whole game).
 * `onUpdated(updatedMoment)` runs after state sync so the parent can exit
 * exploration, etc.
 *
 * Status auto-clears: 'done' fades after 2.5s, 'error' after 4s — both purely
 * for the badge in the UI.
 */
export function useReanalyzeMoment(gameId, setGame, onUpdated) {
  const [status, setStatus] = useState(null)

  const trigger = useCallback(async (moment) => {
    if (!moment || status === 'running') return
    setStatus('running')
    try {
      const res = await api.post(`/games/${gameId}/reanalyze-moment`, {
        move_index: moment.move_index,
      })
      const {
        kind,
        moment_index: momentIndex,
        moment: updated,
        concept_threads: conceptThreads,
        critical_moments: criticalMoments,
        highlight_moments: highlightMoments,
      } = res.data
      const listKey = kind === 'critical' ? 'critical_moments' : 'highlight_moments'
      setGame(prev => {
        if (!prev?.analysis) return prev
        const nextAnalysis = { ...prev.analysis }
        if (Array.isArray(criticalMoments) && Array.isArray(highlightMoments)) {
          nextAnalysis.critical_moments = criticalMoments
          nextAnalysis.highlight_moments = highlightMoments
        } else {
          const nextList = [...(prev.analysis[listKey] || [])]
          nextList[momentIndex] = updated
          nextAnalysis[listKey] = nextList
        }
        if (Array.isArray(conceptThreads)) {
          nextAnalysis.concept_threads = conceptThreads
        }
        return { ...prev, analysis: nextAnalysis }
      })
      onUpdated?.(updated, moment)
      setStatus('done')
      window.setTimeout(() => setStatus(null), 2500)
    } catch {
      setStatus('error')
      window.setTimeout(() => setStatus(null), 4000)
    }
  }, [gameId, status, setGame, onUpdated])

  return { status, trigger }
}
