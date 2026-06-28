export default function PlanThreads({ threads, onGoToMove }) {
  if (!Array.isArray(threads) || threads.length === 0) return null

  const jump = (thread) => {
    const first = Array.isArray(thread.moves) ? thread.moves[0] : null
    const idx = first?.half_move
    if (idx != null) onGoToMove?.(idx)
  }

  return (
    <div className="plan-threads">
      <h3 className="plan-threads-title">Strategic threads</h3>
      <p className="plan-threads-sub">
        Ideas the engine kept returning to across the game.
      </p>
      {threads.map((thread) => (
        <div key={thread.id || thread.title} className="plan-thread-item">
          <button
            type="button"
            className="plan-thread-jump"
            onClick={() => jump(thread)}
            title={`Jump to move ${thread.start_move}`}
          >
            {thread.count}x · moves {thread.start_move}-{thread.end_move}
          </button>
          <p className="plan-thread-title">{thread.title}</p>
          <p className="plan-thread-summary">{thread.summary}</p>
        </div>
      ))}
    </div>
  )
}
