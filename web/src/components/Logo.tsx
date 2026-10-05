/** ScribSalmon mark: folded omelette + sound wave on a salmon tile. Keep in sync with assets/logo.svg. */
export default function Logo({ className = 'size-9' }: { className?: string }) {
  return (
    <svg viewBox="0 0 256 256" className={className} aria-label="ScribSalmon" role="img">
      <defs>
        <linearGradient id="lg-bg" x1="0.1" y1="0" x2="0.9" y2="1">
          <stop offset="0" stopColor="#ffa690" />
          <stop offset="1" stopColor="#ff5f55" />
        </linearGradient>
        <linearGradient id="lg-yolk" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset="0.55" stopColor="#ffd96b" />
          <stop offset="1" stopColor="#ffb938" />
        </linearGradient>
        <linearGradient id="lg-shine" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.55" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="256" height="256" rx="58" fill="url(#lg-bg)" />
      <g transform="translate(0 7)">
        <path
          d="M36 168 C36 98 76 58 128 58 C180 58 220 98 220 168 C220 181 209 188 197 188 L59 188 C47 188 36 181 36 168 Z"
          fill="url(#lg-yolk)"
        />
        <path d="M58 150 C62 108 90 80 124 76" fill="none" stroke="url(#lg-shine)" strokeWidth="9" strokeLinecap="round" />
        <g fill="#6b2a22">
          <rect x="76" y="116" width="15" height="44" rx="7.5" />
          <rect x="101" y="98" width="15" height="80" rx="7.5" />
          <rect x="121" y="84" width="15" height="96" rx="7.5" />
          <rect x="146" y="98" width="15" height="80" rx="7.5" />
          <rect x="171" y="116" width="15" height="44" rx="7.5" />
        </g>
      </g>
    </svg>
  )
}
