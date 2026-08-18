export function BrandMark({ size = 26 }: { size?: number }) {
  const gradientId = `musicseed-brand-gradient-${size}`;

  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f2b632" />
          <stop offset="1" stopColor="#ef7a24" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gradientId})`} />
      <circle cx="16" cy="19" r="6.5" fill="#0b0a12" opacity="0.35" />
      <path
        d="M16 5.5c-2 2.4-3 4.4-3 6.5a3 3 0 0 0 6 0c0-2.1-1-4.1-3-6.5Z"
        fill="#ffffff"
      />
      <circle cx="16" cy="13.5" r="1.6" fill="#ffffff" />
    </svg>
  );
}
