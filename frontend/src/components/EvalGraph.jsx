import { useRef, useState, useEffect, useMemo, useCallback, memo } from 'react'
import MoveNotation from './MoveNotation'
import { formatEval, CLS_SYMBOLS } from '../reviewUtils'

const CLS_COLORS = {
  blunder: '#e74c3c',
  mistake: '#e67e22',
  inaccuracy: '#f1c40f',
  great: '#2ecc71',
  best: '#27ae60',
}

const clamp = (v) => Math.max(-5, Math.min(5, (Math.abs(v) >= 100) ? (v > 0 ? 5 : -5) : v))

export default memo(function EvalGraph({ moves, currentMove, onClickMove, keyMomentIndices, driftSpans }) {
  const svgRef = useRef(null)
  const containerRef = useRef(null)
  const [containerWidth, setContainerWidth] = useState(400)
  const [hoverIdx, setHoverIdx] = useState(null)

  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver(entries => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width)
      }
    })
    observer.observe(containerRef.current)
    setContainerWidth(containerRef.current.clientWidth)
    return () => observer.disconnect()
  }, [])

  const width = containerWidth
  const height = 80
  const padding = { left: 24, right: 8, top: 8, bottom: 8 }
  const graphW = width - padding.left - padding.right
  const graphH = height - padding.top - padding.bottom

  const evals = useMemo(
    () => [0.2, ...moves.map(m => clamp(m.eval_after))],
    [moves],
  )

  const xScale = useCallback(
    (i) => padding.left + (i / Math.max(1, evals.length - 1)) * graphW,
    [evals.length, graphW, padding.left],
  )
  const yScale = useCallback(
    (v) => padding.top + ((5 - v) / 10) * graphH,
    [graphH, padding.top],
  )
  const midY = yScale(0)

  const { whitePath, blackPath, linePath, criticalDots } = useMemo(() => {
    const wp = [`M ${xScale(0)} ${midY}`]
    const bp = [`M ${xScale(0)} ${midY}`]

    for (let i = 0; i < evals.length; i++) {
      const x = xScale(i)
      const y = yScale(evals[i])
      if (evals[i] >= 0) {
        wp.push(`L ${x} ${y}`)
        bp.push(`L ${x} ${midY}`)
      } else {
        wp.push(`L ${x} ${midY}`)
        bp.push(`L ${x} ${y}`)
      }
    }

    wp.push(`L ${xScale(evals.length - 1)} ${midY} Z`)
    bp.push(`L ${xScale(evals.length - 1)} ${midY} Z`)

    const lp = evals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(v)}`).join(' ')

    const dots = moves
      .map((m, i) => {
        const cls = m.classification
        if (!CLS_COLORS[cls]) return null
        return { x: xScale(i + 1), y: yScale(evals[i + 1]), color: CLS_COLORS[cls] }
      })
      .filter(Boolean)

    return { whitePath: wp.join(' '), blackPath: bp.join(' '), linePath: lp, criticalDots: dots }
  }, [evals, midY, moves, xScale, yScale])

  // Drift stretches → translucent amber bands behind the curve, so the
  // slow-bleed regions read at a glance (matched to the "Positional drift" hue).
  const driftBands = useMemo(() => {
    if (!driftSpans?.length) return []
    return driftSpans.map((s) => {
      const hms = s.half_moves || []
      if (!hms.length) return null
      const x0 = xScale(Math.min(...hms) + 1)
      const x1 = xScale(Math.max(...hms) + 1)
      return { x0, w: Math.max(2, x1 - x0) }
    }).filter(Boolean)
  }, [driftSpans, xScale])

  // The few game-deciding turns → gold rings on the curve (click to jump there,
  // so the turning points stay reachable while you navigate the game).
  const keyRings = useMemo(() => {
    if (!keyMomentIndices || !keyMomentIndices.size) return []
    const out = []
    for (let i = 0; i < moves.length; i++) {
      if (keyMomentIndices.has(i)) out.push({ x: xScale(i + 1), y: yScale(evals[i + 1]) })
    }
    return out
  }, [keyMomentIndices, moves.length, xScale, yScale, evals])

  const idxFromClientX = useCallback((clientX) => {
    if (!svgRef.current) return null
    const rect = svgRef.current.getBoundingClientRect()
    const scaledX = (clientX - rect.left) * (width / rect.width)
    const fraction = (scaledX - padding.left) / graphW
    return Math.round(fraction * (evals.length - 1)) - 1
  }, [width, graphW, padding.left, evals.length])

  if (!moves || moves.length === 0) return null

  const handleClick = (e) => {
    const idx = idxFromClientX(e.clientX)
    if (idx == null) return
    onClickMove(Math.max(-1, Math.min(idx, moves.length - 1)))
  }

  const handleHover = (e) => {
    const idx = idxFromClientX(e.clientX)
    setHoverIdx(idx == null ? null : Math.max(0, Math.min(idx, moves.length - 1)))
  }

  const activeX = currentMove >= 0 ? xScale(currentMove + 1) : xScale(0)
  const activeY = currentMove >= 0 ? yScale(evals[currentMove + 1]) : yScale(evals[0])

  const hoverMove = hoverIdx != null ? moves[hoverIdx] : null
  const hoverX = hoverIdx != null ? xScale(hoverIdx + 1) : 0
  const hoverSym = hoverMove && CLS_SYMBOLS[hoverMove.classification]

  return (
    <div className="eval-graph-container" ref={containerRef} style={{ position: 'relative' }}>
      <svg
        ref={svgRef}
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="eval-graph"
        onClick={handleClick}
        onMouseMove={handleHover}
        onMouseLeave={() => setHoverIdx(null)}
      >
        <rect x={padding.left} y={padding.top} width={graphW} height={graphH} fill="#3a3531" rx="3" />

        {driftBands.map((b, i) => (
          <rect key={`drift-${i}`} x={b.x0} y={padding.top} width={b.w} height={graphH} fill="rgba(201,168,108,0.14)" />
        ))}

        <path d={whitePath} fill="rgba(238,238,238,0.15)" />
        <path d={blackPath} fill="rgba(51,51,51,0.3)" />

        <line x1={padding.left} y1={midY} x2={width - padding.right} y2={midY} stroke="#444" strokeWidth="1" strokeDasharray="3,3" />

        <path d={linePath} fill="none" stroke="#aaa" strokeWidth="1.5" />

        {hoverIdx != null && (
          <line x1={hoverX} y1={padding.top} x2={hoverX} y2={height - padding.bottom} stroke="rgba(255,255,255,0.22)" strokeWidth="1" />
        )}

        {criticalDots.map((dot, i) => (
          <circle key={i} cx={dot.x} cy={dot.y} r="3.5" fill={dot.color} stroke="#3a3531" strokeWidth="1" />
        ))}

        {keyRings.map((k, i) => (
          <circle key={`key-${i}`} cx={k.x} cy={k.y} r="6" fill="none" stroke="#e8c879" strokeWidth="2" />
        ))}

        <circle cx={activeX} cy={activeY} r="4.5" fill="#c9a86c" stroke="#fff" strokeWidth="1.5" />
        <line x1={activeX} y1={padding.top} x2={activeX} y2={height - padding.bottom} stroke="rgba(79,195,247,0.3)" strokeWidth="1" />

        <text x={padding.left - 3} y={padding.top + 7} textAnchor="end" fill="#9c9488" fontSize="10">+5</text>
        <text x={padding.left - 3} y={midY + 3} textAnchor="end" fill="#9c9488" fontSize="10">0</text>
        <text x={padding.left - 3} y={height - padding.bottom} textAnchor="end" fill="#9c9488" fontSize="10">-5</text>
      </svg>

      {hoverMove && (
        <div
          className="eval-graph-tip"
          style={{ left: `${Math.max(2, Math.min(hoverX, width - 2))}px` }}
        >
          <span className="eval-graph-tip-move">
            {hoverMove.move_number}{hoverMove.side === 'White' ? '.' : '…'}{' '}
            <MoveNotation san={hoverMove.user_move} size="sm" />
          </span>
          {hoverSym && <span style={{ color: hoverSym.color, fontWeight: 700 }}>{hoverSym.text}</span>}
          <span className="eval-graph-tip-eval">{formatEval(hoverMove.eval_after)}</span>
        </div>
      )}
    </div>
  )
})
