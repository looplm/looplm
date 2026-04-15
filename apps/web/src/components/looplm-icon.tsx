export default function LoopLMIcon({ className = "w-6 h-6" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      {/* Circular loop arrow */}
      <path
        d="M16 4C9.373 4 4 9.373 4 16s5.373 12 12 12 12-5.373 12-12"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
      {/* Arrowhead */}
      <path
        d="M28 4v8h-8"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
