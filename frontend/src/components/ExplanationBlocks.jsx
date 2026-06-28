import { useState } from 'react'
import { LINE_META } from '../explanationBlocks'
import MoveNotation from './MoveNotation'

/** Read-only rendering of a move line — used where the board can't replay it
    (live play coach). Keeps the chip look without the dead buttons. */
function StaticStepStrip({ steps }) {
  if (!steps?.length) return null
  return (
    <div className="explanation-step-row static-steps">
      {steps.map((step, i) => (
        <span key={`${step.line}-${step.index}-${step.san}`} className="explanation-step-wrap">
          {i > 0 && <span className="explanation-step-arrow" aria-hidden>→</span>}
          <span className="explanation-step-unit">
            <span
              className={`explanation-step-btn static ${(LINE_META[step.line] || LINE_META.pv).chipClass}`}
              title={step.why || undefined}
            >
              <MoveNotation san={step.san} size="sm" />
            </span>
            {step.why ? (
              <span className="explanation-step-why">{step.why}</span>
            ) : null}
          </span>
        </span>
      ))}
    </div>
  )
}

// Backend block texts that only make sense when the steps are clickable.
const INTERACTIVE_PROMPTS = new Set([
  'Step through the punishment line.',
  'Tap a move to see that line on the board.',
])

export function StepStrip({
  steps,
  blockId,
  onStep,
  activeStep,
  onBackToGame,
  isExploring,
  interactive = true,
}) {
  if (!steps?.length) return null
  if (!interactive) return <StaticStepStrip steps={steps} />

  return (
    <div className="explanation-steps">
      <p className="explanation-steps-hint">
        Step through on the board — each button updates the position.
      </p>
      <div className="explanation-step-row">
        {steps.map((step, i) => {
          const meta = LINE_META[step.line] || LINE_META.pv
          const isActive = activeStep?.blockId === blockId && activeStep?.stepIndex === i
          const isResponse = step.opponent === false
          const title = step.why || (isResponse ? 'Your forced response' : meta.label)
          return (
            <span key={`${step.line}-${step.index}-${step.san}`} className="explanation-step-wrap">
              {i > 0 && <span className="explanation-step-arrow" aria-hidden>→</span>}
              <span className="explanation-step-unit">
                <button
                  type="button"
                  className={`explanation-step-btn ${meta.chipClass}${isActive ? ' active' : ''}${isResponse ? ' step-response' : ''}`}
                  onClick={() => onStep(step, blockId, i, steps.length)}
                  title={title}
                >
                  <MoveNotation san={step.san} size="sm" />
                </button>
                {step.why ? (
                  <span className="explanation-step-why">{step.why}</span>
                ) : null}
              </span>
            </span>
          )
        })}
      </div>
      {isExploring && (
        <button type="button" className="explanation-back-btn" onClick={onBackToGame}>
          ← Back to your game
        </button>
      )}
    </div>
  )
}

function parseAltMoves(alt) {
  if (Array.isArray(alt.move_list)) return alt.move_list
  return String(alt.moves || '').split(/\s+/).filter(Boolean)
}

export function AlternativesList({ alternatives, onAltMove, activeLink }) {
  const [open, setOpen] = useState(false)
  if (!alternatives?.length) return null

  return (
    <div className="alternatives-block">
      <button
        type="button"
        className="alternatives-toggle"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        {open ? '▼' : '▶'} Other engine lines ({alternatives.length})
      </button>
      {open && (
        <ul className="alternatives-list">
          {alternatives.map(alt => {
            const moves = parseAltMoves(alt)
            return (
              <li key={alt.rank} className="alternatives-item">
                <span className="alternatives-eval">{alt.eval}</span>
                <div className="alternatives-moves">
                  {moves.map((san, moveIndex) => {
                    const isActive = activeLink?.line === 'alt'
                      && activeLink?.altRank === alt.rank
                      && activeLink?.index === moveIndex
                    return (
                      <span key={`${alt.rank}-${moveIndex}-${san}`} className="alternatives-move-wrap">
                        {moveIndex > 0 && (
                          <span className="explanation-step-arrow" aria-hidden>→</span>
                        )}
                        <button
                          type="button"
                          className={`explanation-step-btn line-alt${isActive ? ' active' : ''}`}
                          onClick={() => onAltMove?.(alt, san, moveIndex, moves)}
                          title={`Alternative line #${alt.rank} — after ${san}`}
                        >
                          <MoveNotation san={san} size="sm" />
                        </button>
                      </span>
                    )
                  })}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default function ExplanationBlocks({
  blocks,
  activeStep = null,
  onStep,
  onAltMove,
  onBackToGame,
  isExploring = false,
  interactive = true,
  previewLink = null,
}) {
  if (!blocks?.length) return null

  return (
    <div className="explanation-blocks">
      {blocks.map(block => {
        // Alternative engine lines exist purely to be replayed on the board —
        // without a board to drive, the whole block is dead weight.
        if (!interactive && block.id === 'alternatives') return null
        const promptWithoutBoard = !interactive
          && INTERACTIVE_PROMPTS.has(block.text)
          && block.steps?.length > 0
        return (
          <section key={block.id} className={`explanation-block block-${block.id}`}>
            <h4 className="explanation-block-label">{block.label}</h4>
            {block.text && !promptWithoutBoard
              ? <p className="explanation-block-text">{block.text}</p>
              : null}
            {block.id === 'alternatives' && block.alternatives && interactive ? (
              <AlternativesList
                alternatives={block.alternatives}
                onAltMove={onAltMove}
                activeLink={previewLink}
              />
            ) : null}
            <StepStrip
              steps={block.steps}
              blockId={block.id}
              onStep={onStep}
              activeStep={activeStep}
              onBackToGame={onBackToGame}
              isExploring={isExploring}
              interactive={interactive}
            />
          </section>
        )
      })}
    </div>
  )
}
