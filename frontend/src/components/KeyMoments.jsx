import MoveNotation from './MoveNotation'
import { rankKeyMoments, KEY_MOMENT_TYPES } from '../reviewUtils'

/**
 * Phase D — a prioritised "turning points" overview. Turns a flat per-move wall
 * into "here are the few moments that decided the game", each clickable to dive
 * in. The ranking lives in reviewUtils.rankKeyMoments so the eval-graph markers
 * mark exactly these same moves.
 */

/** The "why" sentence for a row — first sentence of the lesson, minus the
 *  "<move> is a blunder —" prefix the row label already shows. */
function whySummary(m) {
  const lesson = (m.explanation_blocks || []).find(b => b.id === 'lesson')
  let text = (lesson?.text || m.explanation || '').trim()
  const stop = text.indexOf('. ')
  if (stop > 0) text = text.slice(0, stop + 1)
  text = text.replace(/^\S+\s+is a (?:blunder|mistake)\b\s*(?:—\s*|\.\s*)?/i, '').trim()
  if (!text) return ''
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export default function KeyMoments({ moments, onJump }) {
  const ranked = rankKeyMoments(moments)

  if (!ranked.length) return null

  return (
    <div className="key-moments">
      <h4 className="key-moments-title">Key moments</h4>
      <p className="key-moments-hint">The turning points of the game — click one to dive in.</p>
      <ol className="key-moments-list">
        {ranked.map((m) => {
          const why = whySummary(m)
          const badge = KEY_MOMENT_TYPES[m.type]
          return (
            <li key={m.move_index}>
              <button type="button" className="key-moment-row" onClick={() => onJump(m.move_index)}>
                <span className={`classification-badge cls-${badge.cls}`}>{badge.label}</span>
                <span className="key-moment-move">
                  {m.move_number}{m.side === 'White' ? '.' : '…'}{' '}
                  <MoveNotation san={m.user_move} size="sm" />
                </span>
                {why && <span className="key-moment-why">{why}</span>}
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
