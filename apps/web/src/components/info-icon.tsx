/**
 * Small "there is an explanation here" glyph, meant to sit inside a Tooltip trigger.
 * Extracted from the dashboard page, which had it inline, because the Overview page needs
 * it in about ten places.
 */
export default function InfoIcon() {
  return (
    <svg
      className="inline-block w-3.5 h-3.5 ml-1 text-gray-400 dark:text-slate-500"
      viewBox="0 0 16 16"
      fill="currentColor"
    >
      <path
        fillRule="evenodd"
        d="M8 15A7 7 0 108 1a7 7 0 000 14zm.75-10.25a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM7.25 8a.75.75 0 011.5 0v3a.75.75 0 01-1.5 0V8z"
        clipRule="evenodd"
      />
    </svg>
  );
}
