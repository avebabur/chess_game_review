import { createElement } from 'react'

/** react-chessboard default is 300ms; 208ms feels snappy for review scrubbing. */
export const BOARD_ANIMATION_MS = 208

const PIECE_KEYS = ['wP', 'wB', 'wN', 'wR', 'wQ', 'wK', 'bP', 'bB', 'bN', 'bR', 'bQ', 'bK']

export const boardSquareStyles = {
  customBoardStyle: {
    borderRadius: '2px',
    backgroundImage: 'url(/board/blue2.jpg)',
    backgroundSize: '100% 100%',
    backgroundRepeat: 'no-repeat',
    overflow: 'hidden',
  },
  customLightSquareStyle: { backgroundColor: 'rgba(255, 255, 255, 0.02)' },
  customDarkSquareStyle: { backgroundColor: 'rgba(0, 0, 0, 0.06)' },
  showBoardNotation: false,
}

export const customPieces = Object.fromEntries(
  PIECE_KEYS.map((key) => [
    key,
    ({ squareWidth }) => createElement('img', {
      src: `/piece/merida/${key}.svg`,
      alt: '',
      draggable: false,
      style: {
        width: squareWidth,
        height: squareWidth,
        objectFit: 'contain',
        display: 'block',
      },
    }),
  ]),
)
