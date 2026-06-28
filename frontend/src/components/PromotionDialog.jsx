const PIECES = [
  { piece: 'q', label: 'Queen' },
  { piece: 'r', label: 'Rook' },
  { piece: 'b', label: 'Bishop' },
  { piece: 'n', label: 'Knight' },
]

const PIECE_CHARS = {
  q: { w: '♕', b: '♛' },
  r: { w: '♖', b: '♜' },
  b: { w: '♗', b: '♝' },
  n: { w: '♘', b: '♞' },
}

export default function PromotionDialog({ color, onSelect, onCancel }) {
  return (
    <div className="promotion-overlay" onClick={onCancel}>
      <div className="promotion-dialog" onClick={e => e.stopPropagation()}>
        <p className="promotion-title">Promote to:</p>
        <div className="promotion-choices">
          {PIECES.map(({ piece, label }) => (
            <button
              key={piece}
              className="promotion-piece"
              onClick={() => onSelect(piece)}
              title={label}
            >
              {PIECE_CHARS[piece][color]}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
