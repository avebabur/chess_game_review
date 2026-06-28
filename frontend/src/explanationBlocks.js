import { Chess } from 'chess.js'
import { normalizePvLine } from './variationUtils'

/** Labels and colors for explanation step previews on the board. */

export const LINE_META = {
  before: {
    label: 'Position before your move',
    short: 'Before',
    chipClass: 'line-before',
  },
  main: {
    label: 'Your move in the game',
    short: 'Your move',
    chipClass: 'line-main',
  },
  best: {
    label: 'Best move from this position',
    short: 'Best',
    chipClass: 'line-best',
  },
  pv: {
    label: 'Engine best line',
    short: 'Best line',
    chipClass: 'line-pv',
  },
  refutation: {
    label: 'Punishment after your move',
    short: 'Punishment',
    chipClass: 'line-refutation',
  },
  alt: {
    label: 'Alternative engine line',
    short: 'Alt line',
    chipClass: 'line-alt',
  },
}

export function previewLabel(link, moment, stepIndex, stepCount) {
  const meta = LINE_META[link?.line] || { label: 'Preview', short: 'Preview' }
  const moveNum = moment?.move_number
  const prefix = moveNum ? `After move ${moveNum}` : 'Preview'
  const step = typeof stepIndex === 'number' && stepCount
    ? ` · step ${stepIndex + 1} of ${stepCount}`
    : ''
  return `${prefix}: ${meta.label}${step} — ${link?.san || ''}`
}

/** All moves in the refutation PV, tagged with opponent flag for styling. */
export function refutationStepsFromMoment(moment) {
  const full = moment.refutation_continuation?.length
    ? moment.refutation_continuation
    : (Array.isArray(moment.refutation_line) ? moment.refutation_line : [])

  if (!full.length || !moment.fen_after) {
    return (moment.opponent_refutation || []).map((san, index) => ({
      san,
      line: 'refutation',
      index,
      opponent: true,
    }))
  }

  const userIsWhite = moment.side === 'White'
  const opponentColor = userIsWhite ? 'b' : 'w'
  const steps = []

  try {
    const chess = new Chess(moment.fen_after)
    for (let ply = 0; ply < full.length; ply++) {
      const mover = chess.turn()
      const san = full[ply]
      steps.push({ san, line: 'refutation', index: ply, opponent: mover === opponentColor })
      chess.move(san)
    }
  } catch {
    return (moment.opponent_refutation || []).map((san, index) => ({
      san,
      line: 'refutation',
      index,
      opponent: true,
    }))
  }

  return steps
}

/** Build blocks for games saved before explanation_blocks existed. */
function pvStepsFromMoment(moment, line = 'pv', limit = 5) {
  const raw = Array.isArray(moment.follow_up_line)
    ? moment.follow_up_line
    : String(moment.follow_up_line || '').split(/\s+/).filter(Boolean)
  const lineMoves = normalizePvLine(moment.best_move, raw)
  return lineMoves.slice(0, limit).map((san, index) => ({ san, line, index }))
}

export function blocksFromMoment(moment) {
  const freshRef = refutationStepsFromMoment(moment)

  if (Array.isArray(moment.explanation_blocks) && moment.explanation_blocks.length) {
    const hasPvSteps = moment.explanation_blocks.some(
      b => (b.id === 'better' || b.id === 'tactic' || b.id === 'plan') && b.steps?.length,
    )
    return moment.explanation_blocks
      .filter(b => b.id !== 'cost' && !b.thread_suppressed)
      .map(block => {
        if ((block.id === 'punishment') && freshRef.length) {
          return { ...block, steps: freshRef.slice(0, 8) }
        }
        if (block.id === 'plan' && hasPvSteps) {
          return null
        }
        if (block.id === 'plan' && (!block.steps || !block.steps.length)) {
          return {
            ...block,
            label: 'Better plan',
            text: block.text?.includes('→') ? '' : (block.text || ''),
            steps: pvStepsFromMoment(moment, 'pv', 5),
          }
        }
        if (block.id === 'alternatives' && block.alternatives?.length) {
          const legacyInline = /^#\d/.test(block.text || '')
          return {
            ...block,
            text: legacyInline || !block.text
              ? 'Tap moves below to see each line on the board (from this position).'
              : block.text,
          }
        }
        return block
      })
      .filter(Boolean)
  }

  const pv = (Array.isArray(moment.follow_up_line)
    ? moment.follow_up_line
    : String(moment.follow_up_line || '').split(/\s+/).filter(Boolean)
  ).map((san, index) => ({ san, line: 'pv', index }))

  const blocks = [{
    id: 'body',
    label: 'Coach note',
    text: moment.explanation || '',
    steps: [],
  }]

  if (freshRef.length) {
    blocks.push({
      id: 'punishment',
      label: 'Punishment line',
      text: 'Tap each move to step through how you get punished.',
      steps: freshRef.slice(0, 8),
    })
  }
  if (pv.length) {
    blocks.push({
      id: 'better',
      label: 'Engine line',
      text: 'Tap each move to see the better continuation.',
      steps: pv.slice(0, 5),
    })
  }
  return blocks
}

export function filterLegacyThemeTags(tags, moveNumber = 0) {
  if (!tags?.length) return []
  let out = [...tags]
  if (moveNumber <= 15) {
    out = out.filter(t => t !== 'back rank')
  }
  if (moveNumber <= 12 && out.length > 2) {
    const concrete = ['fork', 'pin', 'discovered attack', 'pawn structure', 'king safety']
    if (concrete.some(c => out.includes(c))) {
      out = out.filter(t => t !== 'piece activity')
    }
  }
  return out.slice(0, 3)
}

export function findActiveStep(blocks, preview) {
  if (!preview?.link) return null
  for (const block of blocks) {
    const idx = (block.steps || []).findIndex(
      s => s.san === preview.link.san && s.line === preview.link.line,
    )
    if (idx >= 0) {
      return { blockId: block.id, stepIndex: idx }
    }
  }
  return null
}
