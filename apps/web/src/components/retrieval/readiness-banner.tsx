"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getRetrievalReadiness, type RetrievalReadiness } from "@/lib/api";

/**
 * Warns when the project isn't configured to *measure* retrieval quality, so a missing embedding
 * model or index semantic configuration reads as an explanation instead of a silently empty chart.
 *
 * - No embedding model / unreachable → dense + hybrid (RRF) stages and the live probe come back empty.
 * - Connected index without a semantic configuration → reranked + agentic+rerank stages come back empty.
 *
 * Renders nothing when everything needed is in place (or the check hasn't resolved yet).
 */
export function RetrievalReadinessBanner() {
  const [readiness, setReadiness] = useState<RetrievalReadiness | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getRetrievalReadiness({}, ctrl.signal)
      .then(setReadiness)
      .catch(() => setReadiness(null));
    return () => ctrl.abort();
  }, []);

  if (!readiness) return null;

  const warnings: { key: string; body: React.ReactNode }[] = [];

  if (!readiness.embedding.configured) {
    warnings.push({
      key: "embedding-missing",
      body: (
        <>
          <strong>No embedding model is configured.</strong> Dense and hybrid (RRF) retrieval can&apos;t
          be measured, so those stages stay empty. Set an embedding deployment/model in{" "}
          <Link href="/settings" className="underline underline-offset-2">
            Settings
          </Link>
          .
        </>
      ),
    });
  } else if (!readiness.embedding.ok) {
    warnings.push({
      key: "embedding-unreachable",
      body: (
        <>
          <strong>The embedding model isn&apos;t reachable.</strong> Dense and hybrid (RRF) stages and
          the live retrieval probe will be empty until it works.
          {readiness.embedding.error ? (
            <span className="mt-1 block font-mono text-xs opacity-80">{readiness.embedding.error}</span>
          ) : null}
        </>
      ),
    });
  }

  // Only flag the semantic gap when an index is actually connected — "no index at all" is a
  // separate state the pages surface on their own.
  if (readiness.index_connected && !readiness.semantic_configured) {
    warnings.push({
      key: "semantic-missing",
      body: (
        <>
          <strong>The connected index has no semantic configuration.</strong> The Reranked and
          Agentic + rerank stages can&apos;t be measured. Add the index&apos;s semantic configuration
          name to the index connection in{" "}
          <Link href="/settings" className="underline underline-offset-2">
            Settings
          </Link>
          .
        </>
      ),
    });
  }

  if (warnings.length === 0) return null;

  return (
    <div
      role="alert"
      className="mb-6 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200"
    >
      <p className="mb-1 font-semibold">Some retrieval stages can&apos;t be measured</p>
      <ul className="list-disc space-y-1.5 pl-5">
        {warnings.map((w) => (
          <li key={w.key}>{w.body}</li>
        ))}
      </ul>
    </div>
  );
}
