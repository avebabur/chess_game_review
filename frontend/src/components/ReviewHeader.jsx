import { formatReanalyzeDetail } from '../reanalyzeSession'

/**
 * Top strip of the Game Review screen — players, opening, date, and the
 * single big "Re-analyze game" button.
 *
 * Owns no state. The reanalyze status pill below the title row reflects the
 * shared `useReanalyzeGame` hook, so the same banner appears whether the
 * analysis was triggered here or from another tab.
 */
export default function ReviewHeader({
  headers,
  analysisOpening,
  analysisEco,
  reanalyzeStatus,
  reanalyzeProgress,
  onReanalyze,
}) {
  return (
    <>
      <div className="review-header">
        <div className="review-title-row">
          <h2>{headers.White || '?'} vs {headers.Black || '?'}</h2>
          <span className="review-result">{headers.Result}</span>
          {analysisOpening && (
            <span className="review-opening">{analysisEco} · {analysisOpening}</span>
          )}
          <span className="review-date">{headers.Date}</span>
          <button
            type="button"
            className="reanalyze-game-btn"
            onClick={onReanalyze}
            disabled={reanalyzeStatus === 'running'}
          >
            {reanalyzeStatus === 'running'
              ? 'Re-analyzing…'
              : reanalyzeStatus === 'done'
                ? 'Re-analyzed'
                : 'Re-analyze game'}
          </button>
        </div>
        {reanalyzeStatus === 'error' && (
          <p className="reanalyze-hint error">Re-analyze failed. Is the server running?</p>
        )}
      </div>

      {reanalyzeStatus === 'running' && (
        <div className="reanalyze-inline-panel">
          <div className="reanalyze-inline-spinner" aria-hidden />
          <div className="reanalyze-inline-text">
            <strong>Re-analyzing this game</strong>
            <span>
              {formatReanalyzeDetail(reanalyzeProgress) || 'Stockfish and coaching notes…'}
            </span>
          </div>
        </div>
      )}
      {reanalyzeStatus === 'done' && (
        <p className="reanalyze-hint success">Re-analysis complete — explanations updated.</p>
      )}
    </>
  )
}
