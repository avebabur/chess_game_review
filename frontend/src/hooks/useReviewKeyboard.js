import { useEffect } from 'react'
import { playStepSound } from '../sounds'

/**
 * Global keyboard navigation for Game Review.
 *
 * Bindings (only fire when the focus is not inside an INPUT/TEXTAREA):
 *   ← / →      previous / next move (or step inside a variation)
 *   ↑ / Home   jump to game start (exits exploration first)
 *   ↓ / End    jump to game end (only in mainline)
 *   [ / ]      jump to previous / next KEY MOMENT (the game-deciding turns)
 *   Esc        leave exploration (also dismisses pending promotion)
 *   F          flip the board
 *
 * Pending promotion: while the user is mid-promotion only Esc is honored,
 * so accidental arrow taps don't change move while a modal is open.
 */
export function useReviewKeyboard({
  pendingPromotion,
  setPendingPromotion,
  isExploring,
  activeVar,
  exploreCursor,
  setExploreCursor,
  fetchExploreEval,
  exitExploration,
  moveRef,
  movesLength,
  goToMove,
  setFlipped,
  keyMomentList = [],
}) {
  useEffect(() => {
    const handleKey = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
      if (pendingPromotion) {
        if (e.key === 'Escape') setPendingPromotion(null)
        return
      }

      if (e.key === 'ArrowRight') {
        e.preventDefault()
        if (isExploring && activeVar) {
          if (exploreCursor < activeVar.moves.length - 1) {
            const next = exploreCursor + 1
            const fenAfter = activeVar.fens[next]
            playStepSound(activeVar.moves[next])
            setExploreCursor(next)
            fetchExploreEval(fenAfter)
          }
        } else if (!isExploring) {
          goToMove(moveRef.current + 1)
        }
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        if (isExploring && activeVar) {
          if (exploreCursor > 0) {
            const prev = exploreCursor - 1
            const fenAfter = activeVar.fens[prev]
            playStepSound(activeVar.moves[prev])
            setExploreCursor(prev)
            fetchExploreEval(fenAfter)
          } else {
            exitExploration()
          }
        } else if (!isExploring) {
          goToMove(moveRef.current - 1)
        }
      } else if (e.key === 'ArrowUp' || e.key === 'Home') {
        e.preventDefault()
        if (isExploring) exitExploration()
        else goToMove(-1)
      } else if (e.key === 'ArrowDown' || e.key === 'End') {
        e.preventDefault()
        if (!isExploring) goToMove(movesLength - 1)
      } else if (e.key === ']') {
        e.preventDefault()
        if (!isExploring && keyMomentList.length) {
          const next = keyMomentList.find(i => i > moveRef.current)
          if (next != null) goToMove(next)
        }
      } else if (e.key === '[') {
        e.preventDefault()
        if (!isExploring && keyMomentList.length) {
          for (let k = keyMomentList.length - 1; k >= 0; k--) {
            if (keyMomentList[k] < moveRef.current) { goToMove(keyMomentList[k]); break }
          }
        }
      } else if (e.key === 'Escape') {
        if (isExploring) exitExploration()
      } else if (e.key === 'f' || e.key === 'F') {
        setFlipped(f => !f)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [
    pendingPromotion,
    setPendingPromotion,
    isExploring,
    activeVar,
    exploreCursor,
    setExploreCursor,
    fetchExploreEval,
    exitExploration,
    moveRef,
    movesLength,
    goToMove,
    setFlipped,
    keyMomentList,
  ])
}
