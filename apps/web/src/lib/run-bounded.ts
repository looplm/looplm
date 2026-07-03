// Run an async op over items with bounded concurrency, reporting progress as each settles.
// Failures are swallowed (best-effort bulk actions); progress still advances so callers can show a
// live count. Returns when every item has settled. Pass ``signal`` to stop early: once aborted, no
// new items are picked up (in-flight ops settle as usual; wire the same signal into their fetches
// to cancel those too).
export async function runBounded<T>(
  items: T[],
  concurrency: number,
  op: (item: T) => Promise<void>,
  onProgress?: (done: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  let cursor = 0;
  let done = 0;
  const worker = async () => {
    while (cursor < items.length && !signal?.aborted) {
      const item = items[cursor++];
      try {
        await op(item);
      } catch {
        // Skip failures; bulk actions are best-effort.
      } finally {
        onProgress?.(++done);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker));
}
