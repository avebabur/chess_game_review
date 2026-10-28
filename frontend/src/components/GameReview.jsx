import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Chess } from 'chess.js'
import { buildCaptureTimeline, computeCaptures } from '../captures'
import { useBoardSize } from '../useBoardSize'
import { buildBoardArrows, buildSquareStyles } from '../reviewBoardStyles'
import EvalBar from './EvalBar'
import ReviewHeader from './ReviewHeader'
import ReviewMoveList from './ReviewMoveList'
import ReviewSidePanel from './ReviewSidePanel'
import ReviewBoard from './ReviewBoard'
import { rankKeyMoments } from '../reviewUtils'
import { useExploreEval } from '../hooks/useExploreEval'
import { useReanalyzeGame } from '../hooks/useReanalyzeGame'
import { useGameData } from '../hooks/useGameData'
import { useReanalyzeMoment } from '../hooks/useReanalyzeMoment'
import { useReviewKeyboard } from '../hooks/useReviewKeyboard'
import { useReviewExploration } from '../hooks/useReviewExploration'
import './review.css'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const EMPTY_CAPTURES = { whiteCaptured: [], blackCaptured: [], materialBalance: 0 }

export default function GameReview() {
  const { gameId } = useParams()
  const [searchParams] = useSearchParams()
  const { game, loading, loadError, reload: reloadGameData, setGame } = useGameData(gameId)
  const [currentMove, setCurrentMove] = useState(-1)
  const [flipped, setFlipped] = useState(false)

  const [pendingPromotion, setPendingPromotion] = useState(null)
  const [selectedSquare, setSelectedSquare] = useState(null)
  const [legalMoves, setLegalMoves] = useState([])

  const { exploreEval, fetch: fetchExploreEval, reset: resetExploreEval } = useExploreEval()

  const moveRef = useRef(-1)
  const activeMoveRef = useRef(null)
  const boardSize = useBoardSize()

  const clearSelection = useCallback(() => {
    setSelectedSquare(null)
    setLegalMoves([])
  }, [])

  const analysis = game?.analysis
  const moves = useMemo(() => analysis?.moves || [], [analysis])
  const criticalMoments = useMemo(() => analysis?.critical_moments || [], [analysis])
  const highlightMoments = useMemo(() => analysis?.highlight_moments || [], [analysis])
  const coachingMoments = useMemo(
    () => [...criticalMoments, ...highlightMoments].sort((a, b) => a.move_index - b.move_index),
    [criticalMoments, highlightMoments],
  )

  const criticalIndices = useMemo(
    () => new Set(coachingMoments.map(cm => cm.move_index)),
    [coachingMoments],
  )

  const highlightIndices = useMemo(
    () => new Set(highlightMoments.map(hm => hm.move_index)),
    [highlightMoments],
  )

  // The handful of game-deciding turns (same ranking the Key Moments list uses),
  // marked on the eval graph and jumped between with [ and ].
  const keyMoments = useMemo(() => rankKeyMoments(criticalMoments), [criticalMoments])
  const keyMomentIndices = useMemo(
    () => new Set(keyMoments.map(m => m.move_index)),
    [keyMoments],
  )
  const keyMomentList = useMemo(() => keyMoments.map(m => m.move_index), [keyMoments])

  const fenCache = useMemo(() => {
    if (!moves.length) return [START_FEN]
    // The server already stores every position; replaying the game through
    // chess.js is only a fallback for analyses saved before `fen_after` existed.
    if (moves.every(m => m.fen_after)) {
      return [moves[0].fen || START_FEN, ...moves.map(m => m.fen_after)]
    }
    const fens = [START_FEN]
    const chess = new Chess()
    for (let i = 0; i < moves.length; i++) {
      try { chess.move(moves[i].user_move) } catch { break }
      fens.push(chess.fen())
    }
    return fens
  }, [moves])

  const getPosition = useCallback((idx) => {
    if (idx < 0 || !moves.length) return START_FEN
    return fenCache[Math.min(idx + 1, fenCache.length - 1)]
  }, [moves.length, fenCache])

  /**
   * `useReviewExploration` needs to peek at the current FEN to make moves,
   * but the canonical "current FEN" formula depends on `isExploring`/`activeVar`
   * — which only exist after the hook runs. Break the cycle with a ref that we
   * update after the fact.
   */
  const getCurrentFenRef = useRef(() => START_FEN)
  const getCurrentFen = useCallback(() => getCurrentFenRef.current(), [])

  const exploration = useReviewExploration({
    coachingMoments,
    moves,
    currentMove,
    setCurrentMove,
    moveRef,
    getCurrentFen,
    fetchExploreEval,
    resetExploreEval,
    clearSelection,
  })
  const {
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
    goToExplanationMove,
    reset: resetExploration,
  } = exploration

  useEffect(() => {
    getCurrentFenRef.current = () => {
      if (isExploring && activeVar) return activeVar.fens[exploreCursor]
      return getPosition(currentMove)
    }
  }, [isExploring, activeVar, exploreCursor, currentMove, getPosition])

  const resetForGame = useCallback(() => {
    setCurrentMove(-1)
    resetExploration()
  }, [resetExploration])

  useEffect(() => {
    const timer = window.setTimeout(resetForGame, 0)
    return () => window.clearTimeout(timer)
  }, [gameId, resetForGame])

  const syncMoveFromSearch = useCallback(() => {
    const moveParam = searchParams.get('move')
    if (!game || moveParam == null) return
    const idx = Number.parseInt(moveParam, 10)
    if (Number.isNaN(idx)) return
    const max = (game.analysis?.moves?.length ?? 0) - 1
    const next = Math.max(-1, Math.min(idx, max))
    setCurrentMove(next)
    moveRef.current = next
  }, [game, searchParams])

  useEffect(() => {
    const timer = window.setTimeout(syncMoveFromSearch, 0)
    return () => window.clearTimeout(timer)
  }, [syncMoveFromSearch])

  const reloadGame = useCallback(async () => {
    await reloadGameData()
    setCurrentMove(-1)
    resetExploration()
  }, [reloadGameData, resetExploration])

  const {
    status: reanalyzeStatus,
    progress: reanalyzeProgress,
    trigger: handleReanalyze,
  } = useReanalyzeGame(gameId, reloadGame)

  const captureTimeline = useMemo(() => buildCaptureTimeline(moves), [moves])

  const captureState = useMemo(() => {
    if (isExploring && activeVar) {
      return computeCaptures({
        moves,
        currentMove,
        isExploring,
        activeVar,
        exploreCursor,
      })
    }
    if (currentMove < 0) return captureTimeline[0] || EMPTY_CAPTURES
    return captureTimeline[Math.min(currentMove + 1, captureTimeline.length - 1)]
      || EMPTY_CAPTURES
  }, [captureTimeline, currentMove, isExploring, activeVar, exploreCursor, moves])

  const currentMoveData = currentMove >= 0 ? moves[currentMove] : null
  const moment = coachingMoments.find(cm => cm.move_index === currentMove)
  const panelMoment = followUpMoment || moment || activeVar?.moment || null
  const activeMoment = panelMoment
  const coachingDiffMoment = !isExploring && moment
    && moment.user_move !== moment.best_move
    && moment.fen_after_best
    ? moment
    : null
  // When a coaching-diff moment is active (user move ≠ best move), show the
  // position AFTER the user's played move — so their piece is visually on its
  // destination square and captures show the capturing piece replacing the
  // captured one. The arrows for played-vs-best are still drawn from the
  // pre-move source squares (computed off `coachingDiffMoment.fen`), so the
  // "what you did vs what the engine wanted" overlay still reads correctly.
  const displayPosition = isExploring && activeVar
    ? activeVar.fens[exploreCursor]
    : (coachingDiffMoment?.fen_after || coachingDiffMoment?.fen || getPosition(currentMove))
  const boardOrientation = flipped ? 'black' : 'white'

  let evalScore
  if (isExploring) {
    evalScore = exploreEval?.eval ?? currentMoveData?.eval_after ?? 0.2
  } else if (coachingDiffMoment) {
    // Match the bar to the board: it shows the position after the played move
    // whenever `fen_after` exists (it used to show the pre-move eval there).
    evalScore = coachingDiffMoment.fen_after
      ? coachingDiffMoment.eval_after
      : coachingDiffMoment.eval_before
  } else if (currentMoveData) {
    evalScore = currentMoveData.eval_after
  } else {
    evalScore = 0.2
  }

  const movePairs = useMemo(() => {
    const pairs = []
    for (let i = 0; i < moves.length; i += 2) {
      pairs.push({
        number: moves[i].move_number,
        white: { move: moves[i], index: i },
        black: i + 1 < moves.length ? { move: moves[i + 1], index: i + 1 } : null,
      })
    }
    return pairs
  }, [moves])

  const variationsByBranch = useMemo(() => {
    const map = new Map()
    variations.forEach((v, vi) => {
      const key = v.branchFrom
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(vi)
    })
    return map
  }, [variations])

  const squareStyles = useMemo(
    () => buildSquareStyles({
      isExploring,
      currentMoveData,
      selectedSquare,
      legalMoves,
      coachingDiffMoment,
      activeVar,
      exploreCursor,
      displayPosition,
      boardPreview,
    }),
    [isExploring, currentMoveData, selectedSquare, legalMoves, activeVar, exploreCursor, displayPosition, boardPreview, coachingDiffMoment],
  )

  const arrows = useMemo(
    () => buildBoardArrows({
      isExploring,
      currentMoveData,
      activeMoment,
      exploreEval,
      displayPosition,
      boardPreview,
      activeVar,
      exploreCursor,
    }),
    [isExploring, currentMoveData, activeMoment, exploreEval, displayPosition, boardPreview, activeVar, exploreCursor],
  )

  const handlePieceDrop = (sourceSquare, targetSquare) => {
    const fen = getCurrentFen()
    const chess = new Chess(fen)
    const piece = chess.get(sourceSquare)
    if (piece && piece.type === 'p') {
      const rank = targetSquare[1]
      if ((piece.color === 'w' && rank === '8') || (piece.color === 'b' && rank === '1')) {
        let testMove
        try { testMove = chess.move({ from: sourceSquare, to: targetSquare, promotion: 'q' }) } catch { /* invalid */ }
        if (testMove) {
          chess.undo()
          setPendingPromotion({ from: sourceSquare, to: targetSquare, color: piece.color })
          clearSelection()
          return false
        }
        return false
      }
    }
    return completeMove(sourceSquare, targetSquare, 'q')
  }

  const handleSquareClick = (square) => {
    if (pendingPromotion) return

    if (selectedSquare && legalMoves.includes(square)) {
      const fen = getCurrentFen()
      const chess = new Chess(fen)
      const piece = chess.get(selectedSquare)
      if (piece && piece.type === 'p') {
        const rank = square[1]
        if ((piece.color === 'w' && rank === '8') || (piece.color === 'b' && rank === '1')) {
          setPendingPromotion({ from: selectedSquare, to: square, color: piece.color })
          clearSelection()
          return
        }
      }
      completeMove(selectedSquare, square, 'q')
      return
    }

    const fen = getCurrentFen()
    const chess = new Chess(fen)
    const piece = chess.get(square)
    if (piece && piece.color === chess.turn()) {
      setSelectedSquare(square)
      const pieceMoves = chess.moves({ square, verbose: true })
      setLegalMoves(pieceMoves.map(m => m.to))
    } else {
      clearSelection()
    }
  }

  const handlePromotion = (piece) => {
    if (!pendingPromotion) return
    completeMove(pendingPromotion.from, pendingPromotion.to, piece)
    setPendingPromotion(null)
  }

  const onMomentReanalyzed = useCallback((updated, original) => {
    if (followUpMoment?.move_index === original.move_index) {
      setFollowUpMoment(updated)
    }
    exitExploration()
  }, [followUpMoment, exitExploration, setFollowUpMoment])

  const {
    status: momentReanalyzeStatus,
    trigger: handleReanalyzeMoment,
  } = useReanalyzeMoment(gameId, setGame, onMomentReanalyzed)

  useReviewKeyboard({
    pendingPromotion,
    setPendingPromotion,
    isExploring,
    activeVar,
    exploreCursor,
    setExploreCursor,
    fetchExploreEval,
    exitExploration,
    moveRef,
    movesLength: moves.length,
    goToMove,
    setFlipped,
    keyMomentList,
  })

  useEffect(() => {
    if (activeMoveRef.current) {
      activeMoveRef.current.scrollIntoView({ block: 'nearest', behavior: 'auto' })
    }
  }, [currentMove, activeVariation, exploreCursor])

  if (loading) return (
    <div className="puzzle-skeleton">
      <div className="skeleton" style={{ width: 28, height: 500 }} />
      <div className="skeleton skeleton-board" />
      <div className="skeleton-panel">
        <div className="skeleton skeleton-block" style={{ height: 120 }} />
        <div className="skeleton skeleton-block" style={{ height: 300 }} />
        <div className="skeleton skeleton-block" style={{ height: 80 }} />
      </div>
    </div>
  )
  if (loadError || !game) return (
    <div className="error-box">
      <p>{loadError ? 'Couldn\'t load this game' : 'Game not found'}</p>
      <p className="error-hint">
        {loadError ? 'Make sure the server is running, then try again' : 'This game may have been removed'}
      </p>
      <button onClick={loadError ? () => window.location.reload() : () => window.history.back()}>
        {loadError ? 'Try Again' : 'Go Back'}
      </button>
    </div>
  )

  // Analysis carries PGN headers, but un-analyzed games have none yet — fall
  // back to the game row so the header shows real players/result/date (and a
  // clear Re-analyze prompt) instead of "? vs ?".
  const headers = {
    White: analysis?.headers?.White || game.white,
    Black: analysis?.headers?.Black || game.black,
    Result: analysis?.headers?.Result || game.result,
    Date: analysis?.headers?.Date || game.date,
  }
  const topPlayer = flipped ? (headers.White || 'White') : (headers.Black || 'Black')
  const bottomPlayer = flipped ? (headers.Black || 'Black') : (headers.White || 'White')
  const topAccuracy = flipped ? analysis?.white_accuracy : analysis?.black_accuracy
  const bottomAccuracy = flipped ? analysis?.black_accuracy : analysis?.white_accuracy
  const topIsWhite = flipped

  const topCaptured = topIsWhite ? captureState.whiteCaptured : captureState.blackCaptured
  const bottomCaptured = topIsWhite ? captureState.blackCaptured : captureState.whiteCaptured
  const topMaterialAdv = topIsWhite
    ? Math.max(0, captureState.materialBalance)
    : Math.max(0, -captureState.materialBalance)
  const bottomMaterialAdv = topIsWhite
    ? Math.max(0, -captureState.materialBalance)
    : Math.max(0, captureState.materialBalance)

  return (
    <div className="game-review review-skin">
      <ReviewHeader
        headers={headers}
        analysisOpening={analysis?.opening || game.opening}
        analysisEco={analysis?.eco || game.eco}
        reanalyzeStatus={reanalyzeStatus}
        reanalyzeProgress={reanalyzeProgress}
        onReanalyze={handleReanalyze}
      />

      <div className="review-layout">
        <ReviewMoveList
          boardSize={boardSize}
          gamePatterns={analysis?.game_patterns}
          criticalMoments={criticalMoments}
          movePairs={movePairs}
          variations={variations}
          variationsByBranch={variationsByBranch}
          activeVariation={activeVariation}
          exploreCursor={exploreCursor}
          currentMove={currentMove}
          isExploring={isExploring}
          criticalIndices={criticalIndices}
          highlightIndices={highlightIndices}
          moves={moves}
          goToMove={goToMove}
          goToExploreMove={goToExploreMove}
          deleteVariation={deleteVariation}
          setFlipped={setFlipped}
          activeMoveRef={activeMoveRef}
          keyMomentIndices={keyMomentIndices}
          driftSpans={analysis?.drift_spans}
        />

        <div className="eval-bar-column">
          <EvalBar eval={evalScore} flipped={flipped} height={boardSize} />
          <span
            className={`eval-depth-label${
              isExploring && exploreEval?.searching ? ' searching' : ''
            }${isExploring && exploreEval ? '' : ' eval-depth-placeholder'}`}
          >
            {isExploring && exploreEval
              ? (exploreEval.depth > 0
                ? `depth ${exploreEval.depth}/${exploreEval.target_depth || 20}`
                : 'analyzing…')
              : '\u00a0'}
          </span>
        </div>

        <ReviewBoard
          boardSize={boardSize}
          boardOrientation={boardOrientation}
          flipped={flipped}
          topPlayer={topPlayer}
          topAccuracy={topAccuracy}
          topCaptured={topCaptured}
          topMaterialAdv={topMaterialAdv}
          bottomPlayer={bottomPlayer}
          bottomAccuracy={bottomAccuracy}
          bottomCaptured={bottomCaptured}
          bottomMaterialAdv={bottomMaterialAdv}
          displayPosition={displayPosition}
          squareStyles={squareStyles}
          arrows={arrows}
          pendingPromotion={pendingPromotion}
          setPendingPromotion={setPendingPromotion}
          handlePieceDrop={handlePieceDrop}
          handleSquareClick={handleSquareClick}
          handlePromotion={handlePromotion}
          isExploring={isExploring}
          boardPreview={boardPreview}
          exitExploration={exitExploration}
          coachingDiffMoment={coachingDiffMoment}
          currentMoveData={currentMoveData}
        />

        <ReviewSidePanel
          boardSize={boardSize}
          panelMoment={panelMoment}
          driftSpans={analysis?.drift_spans}
          planThreads={analysis?.plan_threads}
          openingIdea={analysis?.opening_idea}
          goToMove={goToMove}
          goToFollowUp={goToFollowUp}
          goToExplanationMove={goToExplanationMove}
          handleReanalyzeMoment={handleReanalyzeMoment}
          momentReanalyzeStatus={momentReanalyzeStatus}
          boardPreview={boardPreview}
          exitExploration={exitExploration}
          isExploring={isExploring}
          exploreEval={exploreEval}
          currentMoveData={currentMoveData}
          evalScore={evalScore}
          criticalMoments={criticalMoments}
        />
      </div>

      <div className="keyboard-hint">
        ← → prev/next | ↑↓ start/end | [ ] key moments | F flip | Click or drag to explore | Esc back to game
      </div>
    </div>
  )
}
