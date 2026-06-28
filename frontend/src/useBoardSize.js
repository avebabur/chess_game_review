import { useState, useEffect, useRef } from 'react'

// Height drives the size on normal desktop windows; the width term only
// kicks in on narrow windows, where ~600px of side panels would otherwise
// push the board off-screen (the side panels wrap below at <=1100px, which
// is why the width budget is generous).
function computeSize() {
  const vh = window.innerHeight
  const vw = window.innerWidth
  const byHeight = Math.floor(vh - 200)
  const byWidth = vw > 1100 ? Math.floor(vw - 700) : Math.floor(vw - 60)
  return Math.min(Math.max(Math.min(byHeight, byWidth), 400), 800)
}

export function useBoardSize() {
  const [size, setSize] = useState(computeSize)
  const raf = useRef(null)
  useEffect(() => {
    const update = () => {
      if (raf.current) cancelAnimationFrame(raf.current)
      raf.current = requestAnimationFrame(() => {
        setSize(computeSize())
      })
    }
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('resize', update)
      if (raf.current) cancelAnimationFrame(raf.current)
    }
  }, [])
  return size
}
