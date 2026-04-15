"use client";

import { useEffect, useRef, useState } from "react";

export function useElapsedTime(startedAt: string | null, isRunning: boolean) {
  const [elapsed, setElapsed] = useState(0);
  // Use a ref to remember when we first saw isRunning=true,
  // as a fallback when started_at hasn't arrived from the backend yet.
  const fallbackStart = useRef<number | null>(null);

  useEffect(() => {
    if (!isRunning) {
      fallbackStart.current = null;
      setElapsed(0);
      return;
    }
    // Compute start time: prefer backend started_at, fall back to client-side timestamp
    const start = startedAt
      ? new Date(startedAt).getTime()
      : (fallbackStart.current ??= Date.now());

    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [startedAt, isRunning]);

  if (elapsed < 60) return `${elapsed}s`;
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}m ${secs}s`;
}
