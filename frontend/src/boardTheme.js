import { createElement } from 'react'

/** react-chessboard default is 300ms; 208ms feels snappy for review scrubbing. */
export const BOARD_ANIMATION_MS = 208

const PIECE_KEYS = ['wP', 'wB', 'wN', 'wR', 'wQ', 'wK', 'bP', 'bB', 'bN', 'bR', 'bQ', 'bK']

export const boardSquareStyles = {
  // Flat printed squares: cream and a muted felt green.
  customBoardStyle: {
    borderRadius: '2px',
    overflow: 'hidden',
  },
  customLightSquareStyle: { backgroundColor: '#e6dcc4' },
  customDarkSquareStyle: { backgroundColor: '#6f9378' },
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
