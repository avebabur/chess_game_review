/**
 * Owns all "exploration" state for the Game Review screen:
 *  - `variations`: the user-curated list of side lines
 *  - `activeVariation` / `exploreCursor`: which line and step the user is on
 *  - `followUpMoment`: the coaching moment that anchors the current exploration
 *  - `boardPreview`: the click-target meta (which sentence/word triggered the line)
 *
 * It also exposes every transition the UI can take: enter a follow-up, alt,
 * or refutation line; complete a move on the board (mainline or exploring);
 * jump within a variation; delete a variation; or exit back to the mainline.
 *
 * GameReview keeps ownership of `currentMove`, the cursor on the mainline,
 * selection state, and promotion UI. Those are passed in as needed.
 */

import { useCallback, useState } from 'react'
import { Chess } from 'chess.js'
import { playStepSound } from '../sounds'
import {
  buildLineFromFen,
  buildRefutationLine,
  normalizePvLine,
  resolveCursorIndex,
} from '../variationUtils'
import { previewLabel } from '../explanationBlocks'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

export function useReviewExploration({
  coachingMoments,
  moves,
  currentMove,
  setCurrentMove,
  moveRef,
  getCurrentFen,
  fetchExploreEval,
  resetExploreEval,
  clearSelection,
}) {
  const [variations, setVariations] = useState([])
  const [activeVariation, setActiveVariation] = useState(null)
  const [exploreCursor, setExploreCursor] = useState(0)
  const [followUpMoment, setFollowUpMoment] = useState(null)
  const [boardPreview, setBoardPreview] = useState(null)

  const isExploring = activeVariation !== null
  const activeVar = isExploring ? variations[activeVariation] : null

  const reset = useCallback(() => {
    setVariations([])
    setActiveVariation(null)
    setExploreCursor(0)
    setFollowUpMoment(null)
    setBoardPreview(null)
  }, [])

  const exitExploration = useCallback(() => {
    setActiveVariation(null)
    setExploreCursor(0)
    setFollowUpMoment(null)
    resetExploreEval()
    setBoardPreview(null)
    clearSelection()
  }, [clearSelection, resetExploreEval])

  const goToMove = useCallback((idx) => {
    if (activeVariation !== null) exitExploration()
    const clamped = Math.max(-1, Math.min(idx, moves.length - 1))
    clearSelection()
    if (clamped >= 0 && moves[clamped]) playStepSound(moves[clamped].user_move)
    setCurrentMove(clamped)
    moveRef.current = clamped
  }, [moves, activeVariation, exitExploration, clearSelection, setCurrentMove, moveRef])

  const goToExploreMove = useCallback((varIndex, moveIdx) => {
    const v = variations[varIndex]
    if (!v) return
    const fenAfter = v.fens[moveIdx]
    playStepSound(v.moves[moveIdx])
    setActiveVariation(varIndex)
    setExploreCursor(moveIdx)
    fetchExploreEval(fenAfter)
    setFollowUpMoment(v.moment || null)
    clearSelection()
  }, [variations, fetchExploreEval, clearSelection])

  const deleteVariation = useCallback((varIndex) => {
    if (activeVariation === varIndex) {
      exitExploration()
    } else if (activeVariation !== null && activeVariation > varIndex) {
      setActiveVariation(prev => prev - 1)
    }
    setVariations(prev => prev.filter((_, i) => i !== varIndex))
  }, [activeVariation, exitExploration])

  const completeMove = useCallback((sourceSquare, targetSquare, promotion) => {
    const fen = getCurrentFen()
    const chess = new Chess(fen)
    let move
    try {
      move = chess.move({ from: sourceSquare, to: targetSquare, promotion })
    } catch { return false }
    if (!move) return false

    playStepSound(move.san)

    if (activeVariation === null) {
      const nextIdx = currentMove + 1
      if (nextIdx < moves.length && move.san === moves[nextIdx].user_move) {
        moveRef.current = nextIdx
        setCurrentMove(nextIdx)
        clearSelection()
        return true
      }

      const existingIdx = variations.findIndex(
        v => v.branchFrom === currentMove && v.moment == null,
      )
      const newVar = {
        branchFrom: currentMove,
        baseFen: fen,
        moves: [move.san],
        fens: [chess.fen()],
        moment: null,
      }
      if (existingIdx >= 0) {
        setVariations(prev => {
          const next = [...prev]
          next[existingIdx] = newVar
          return next
        })
        setActiveVariation(existingIdx)
      } else {
        const newIdx = variations.length
        setVariations(prev => [...prev, newVar])
        setActiveVariation(newIdx)
      }
      setExploreCursor(0)
      fetchExploreEval(chess.fen())
      setFollowUpMoment(null)
    } else {
      setVariations(prev => {
        const updated = [...prev]
        const v = { ...updated[activeVariation] }
        v.moves = [...v.moves.slice(0, exploreCursor + 1), move.san]
        v.fens = [...v.fens.slice(0, exploreCursor + 1), chess.fen()]
        updated[activeVariation] = v
        return updated
      })
      setExploreCursor(prev => prev + 1)
      fetchExploreEval(chess.fen())
    }
    clearSelection()
    return true
  }, [
    activeVariation,
    currentMove,
    moves,
    getCurrentFen,
    fetchExploreEval,
    clearSelection,
    variations,
    exploreCursor,
    setCurrentMove,
    moveRef,
  ])

  const goToFollowUp = useCallback((
    followUpMoves,
    bestMove,
    cursorInPlayed = null,
    stepMeta = null,
  ) => {
    const baseIdx = followUpMoment?.move_index ?? currentMove
    const moveData = baseIdx >= 0 ? moves[baseIdx] : null
    const fen = baseIdx < 0 ? START_FEN : moveData?.fen
    if (!fen) return

    const sourceMoment = coachingMoments.find(cm => cm.move_index === baseIdx)
    const branchFrom = baseIdx - 1
    const momentKey = sourceMoment?.move_index ?? baseIdx

    const lineMoves = followUpMoves?.length ? followUpMoves : []
    const fullLine = normalizePvLine(bestMove, lineMoves)
    const { played, fens } = buildLineFromFen(fen, fullLine)
    if (!played.length && !bestMove) return

    const cursor = resolveCursorIndex(played, {
      san: stepMeta?.san,
      index: cursorInPlayed,
    })

    const newVar = {
      branchFrom,
      baseFen: fen,
      moves: played,
      fens,
      moment: sourceMoment || null,
      kind: 'pv',
    }

    const existingIdx = variations.findIndex(
      v => v.branchFrom === branchFrom
        && (v.moment?.move_index ?? -1) === momentKey
        && v.kind === 'pv',
    )
    const targetIdx = existingIdx >= 0 ? existingIdx : variations.length

    if (existingIdx >= 0) {
      setVariations(prev => {
        const next = [...prev]
        next[existingIdx] = newVar
        return next
      })
    } else {
      setVariations(prev => [...prev, newVar])
    }

    const link = {
      san: played[cursor],
      line: cursor === 0 && played[0] === bestMove ? 'best' : 'pv',
      index: cursor,
    }
    setBoardPreview({
      link,
      meta: stepMeta,
      label: previewLabel(
        link,
        sourceMoment,
        cursor,
        stepMeta?.stepCount ?? played.length,
      ),
    })

    playStepSound(played[cursor])
    setActiveVariation(targetIdx)
    setExploreCursor(cursor)
    setFollowUpMoment(sourceMoment || null)
    fetchExploreEval(fens[cursor])
  }, [currentMove, moves, coachingMoments, fetchExploreEval, followUpMoment, variations])

  const goToAltLine = useCallback((altMoves, cursorIndex, stepMeta = null) => {
    const sourceMoment = followUpMoment
      || coachingMoments.find(cm => cm.move_index === currentMove)
      || (activeVariation != null ? variations[activeVariation]?.moment : null)
    if (!sourceMoment?.fen || !altMoves?.length) return

    const baseIdx = sourceMoment.move_index
    const branchFrom = baseIdx - 1
    const momentKey = baseIdx

    const { played, fens } = buildLineFromFen(sourceMoment.fen, altMoves)
    if (!played.length) return

    const cursor = resolveCursorIndex(played, {
      san: stepMeta?.san,
      index: cursorIndex,
    })

    const newVar = {
      branchFrom,
      baseFen: sourceMoment.fen,
      moves: played,
      fens,
      moment: sourceMoment,
      kind: 'alt',
    }

    const existingIdx = variations.findIndex(
      v => v.branchFrom === branchFrom
        && (v.moment?.move_index ?? -1) === momentKey
        && v.kind === 'alt',
    )
    const targetIdx = existingIdx >= 0 ? existingIdx : variations.length

    if (existingIdx >= 0) {
      setVariations(prev => {
        const next = [...prev]
        next[existingIdx] = newVar
        return next
      })
    } else {
      setVariations(prev => [...prev, newVar])
    }

    const link = {
      san: played[cursor],
      line: 'alt',
      index: cursor,
      altRank: stepMeta?.altRank,
      moveIndex: cursor,
      altMoves,
    }
    setBoardPreview({
      link,
      meta: stepMeta,
      label: previewLabel(link, sourceMoment, cursor, played.length),
    })

    playStepSound(played[cursor])
    setActiveVariation(targetIdx)
    setExploreCursor(cursor)
    setFollowUpMoment(sourceMoment)
    fetchExploreEval(fens[cursor])
  }, [followUpMoment, coachingMoments, currentMove, activeVariation, variations, fetchExploreEval])

  const goToExplanationMove = useCallback((link, stepMeta = null) => {
    if (!link?.san) return

    const sourceMoment = followUpMoment
      || coachingMoments.find(cm => cm.move_index === currentMove)
      || (activeVariation != null ? variations[activeVariation]?.moment : null)
    if (!sourceMoment) return

    const followUpMoves = Array.isArray(sourceMoment.follow_up_line)
      ? sourceMoment.follow_up_line
      : typeof sourceMoment.follow_up_line === 'string'
        ? sourceMoment.follow_up_line.split(/\s+/).filter(Boolean)
        : []

    const fullRefutation = sourceMoment.refutation_continuation?.length
      ? sourceMoment.refutation_continuation
      : (Array.isArray(sourceMoment.refutation_line) ? sourceMoment.refutation_line : [])

    if (link.line === 'main') {
      exitExploration()
      goToMove(sourceMoment.move_index)
      return
    }

    if (link.line === 'before') {
      exitExploration()
      const beforeIdx = Math.max(-1, sourceMoment.move_index - 1)
      goToMove(beforeIdx)
      setBoardPreview({
        link,
        meta: stepMeta,
        label: 'Position before your move — read the position here.',
      })
      return
    }

    if (link.line === 'best') {
      goToFollowUp([], sourceMoment.best_move, 0, stepMeta)
      return
    }

    if (link.line === 'pv') {
      const fullLine = normalizePvLine(sourceMoment.best_move, followUpMoves)
      const { played } = buildLineFromFen(sourceMoment.fen, fullLine)
      const cursor = resolveCursorIndex(played, link)
      goToFollowUp(followUpMoves, sourceMoment.best_move, cursor, {
        ...stepMeta,
        san: link.san,
        stepIndex: cursor,
        stepCount: played.length,
      })
      return
    }

    if (link.line === 'alt' && link.altMoves?.length) {
      goToAltLine(link.altMoves, link.index ?? link.moveIndex, {
        ...stepMeta,
        san: link.san,
        altRank: link.altRank,
      })
      return
    }

    if (link.line === 'refutation' && sourceMoment.fen_after && fullRefutation.length) {
      const { played, fens } = buildRefutationLine(sourceMoment.fen_after, fullRefutation)
      if (!played.length) return

      const branchFrom = sourceMoment.move_index
      const momentKey = sourceMoment.move_index
      const newVar = {
        branchFrom,
        baseFen: sourceMoment.fen_after,
        moves: played,
        fens,
        moment: sourceMoment,
        kind: 'refutation',
      }

      const existingIdx = variations.findIndex(
        v => v.branchFrom === branchFrom
          && (v.moment?.move_index ?? -1) === momentKey
          && v.kind === 'refutation',
      )
      const targetIdx = existingIdx >= 0 ? existingIdx : variations.length

      if (existingIdx >= 0) {
        setVariations(prev => {
          const next = [...prev]
          next[existingIdx] = newVar
          return next
        })
      } else {
        setVariations(prev => [...prev, newVar])
      }

      const cursor = Math.min(link.index, played.length - 1)
      setBoardPreview({
        link,
        meta: stepMeta,
        label: previewLabel(link, sourceMoment, cursor, played.length),
      })
      playStepSound(played[cursor])
      setActiveVariation(targetIdx)
      setExploreCursor(cursor)
      setFollowUpMoment(sourceMoment)
      fetchExploreEval(fens[cursor])
    }
  }, [
    followUpMoment,
    activeVariation,
    coachingMoments,
    currentMove,
    goToMove,
    goToFollowUp,
    goToAltLine,
    variations,
    fetchExploreEval,
    exitExploration,
  ])

  return {
    variations,
    activeVariation,
    exploreCursor,
    followUpMoment,
    boardPreview,
    isExploring,
    activeVar,
    setFollowUpMoment,
    setExploreCursor,
    exitExploration,
    goToMove,
    goToExploreMove,
    deleteVariation,
    completeMove,
    goToFollowUp,
    goToAltLine,
    goToExplanationMove,
    reset,
  }
}
