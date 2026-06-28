/**
 * Game-level "Positional drift" summary. Drift is no longer pinned to a single
 * scapegoat move — it's detected as SPANS of a side's
 * own slow eval loss (backend drift.py, stored on analysis.drift_spans). Each
 * span is shown with its lesson and jumps to where the drift began.
 */
export default function DriftSpans({ spans, onGoToMove }) {
  if (!Array.isArray(spans) || spans.length === 0) return null

  const jump = (span) => {
    const idx = Array.isArray(span.half_moves) && span.half_moves.length
      ? span.half_moves[0]
      : null
    if (idx != null) onGoToMove?.(idx)
  }

  return (
    <div className="drift-spans">
      <h3 className="drift-spans-title">Positional drift</h3>
      <p className="drift-spans-sub">
        Stretches where you slowly lost ground — no single blunder, just drift.
      </p>
      {spans.map((s, i) => (
        <div key={`${s.start_move}-${s.side}-${i}`} className="drift-span-item">
          <button
            type="button"
            className="drift-span-jump"
            onClick={() => jump(s)}
            title={`Jump to move ${s.start_move}`}
          >
            Moves {s.start_move}–{s.end_move} · −{s.pawns_lost} pawns
          </button>
          <p className="drift-span-lesson">{s.lesson}</p>
        </div>
      ))}
    </div>
  )
}
