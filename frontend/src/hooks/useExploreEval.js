import { useCallback, useEffect, useRef, useState } from 'react'
import { api, API } from '../api'

/**
 * Live engine eval for arbitrary positions during exploration.
 *
 * Stockfish runs on the server and streams depth updates over SSE; this hook
 * owns the connection lifecycle so the rest of GameReview doesn't have to
 * juggle EventSource / fallback POST / sessions.
 *
 * Concurrency guarantees:
 *  - 100ms debounce prevents floods when the user rapidly cycles arrow keys.
 *  - A monotonic `evalSessionRef` discards stale SSE messages that arrive
 *    after a newer request — without this you'd see the eval flicker back to
 *    an older position.
 *  - On `onerror` the hook falls back to a single POST so the panel still
 *    shows *some* eval (SSE blocked by proxies is a real failure mode).
 *
 * Returns:
 *   exploreEval — { eval, best_move, depth, target_depth, done, searching }
 *   fetch(fen)  — request eval for `fen` (debounced)
 *   reset()     — clear the current eval (used when leaving exploration)
 */
export function useExploreEval() {
  const [exploreEval, setExploreEval] = useState(null)
  const evalTimeoutRef = useRef(null)
  const evalSourceRef = useRef(null)
  const evalSessionRef = useRef(0)

  useEffect(() => () => {
    if (evalTimeoutRef.current) clearTimeout(evalTimeoutRef.current)
    if (evalSourceRef.current) {
      evalSourceRef.current.close()
      evalSourceRef.current = null
    }
  }, [])

  const fetch = useCallback((fen) => {
    if (evalTimeoutRef.current) clearTimeout(evalTimeoutRef.current)
    evalTimeoutRef.current = setTimeout(() => {
      if (evalSourceRef.current) {
        evalSourceRef.current.close()
        evalSourceRef.current = null
      }

      const session = evalSessionRef.current + 1
      evalSessionRef.current = session
      setExploreEval({ depth: 0, target_depth: 20, done: false, searching: true })

      const url = `${API}/evaluate-stream?fen=${encodeURIComponent(fen)}`
      const es = new EventSource(url)
      evalSourceRef.current = es

      es.onmessage = (event) => {
        if (session !== evalSessionRef.current) return
        try {
          const data = JSON.parse(event.data)
          if (data.error) return
          setExploreEval({
            eval: data.eval,
            best_move: data.best_move,
            depth: data.depth,
            target_depth: data.target_depth,
            done: Boolean(data.done),
            searching: !data.done,
          })
          if (data.done) {
            es.close()
            if (evalSourceRef.current === es) evalSourceRef.current = null
          }
        } catch { /* ignore malformed SSE */ }
      }

      es.onerror = () => {
        es.close()
        if (evalSourceRef.current === es) evalSourceRef.current = null
        if (session === evalSessionRef.current) {
          api.post('/evaluate', { fen }).then(res => {
            if (session !== evalSessionRef.current) return
            setExploreEval({
              ...res.data,
              depth: res.data.target_depth ?? 20,
              target_depth: 20,
              done: true,
              searching: false,
            })
          }).catch(() => {})
        }
      }
    }, 100)
  }, [])

  const reset = useCallback(() => {
    setExploreEval(null)
  }, [])

  return { exploreEval, fetch, reset }
}
