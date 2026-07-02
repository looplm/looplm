// The lead paragraph under the Retrieval-quality heading, explaining what the numbers measure for
// the active source. Split out of the panel to keep it under the file-size limit.
export function SourceDescription({ source }: { source: "urls" | "labels" }) {
  return (
    <p className="text-sm text-gray-500 dark:text-slate-400 mb-5 max-w-3xl">
      {source === "labels" ? (
        <>
          Measured against human chunk relevance labels vs. a live retrieval probe of the
          connected index, per dataset. Recall@k = share of judged-relevant chunks the index
          returns in the top-k; bpref and condensed nDCG stay fair while judging is still
          incomplete.
        </>
      ) : (
        <>
          Measured against your test cases&apos; ground-truth source URLs, per eval run.
          Recall@k = share of expected docs found in the top-k retrieved; nDCG rewards ranking
          them high; MRR = how early the first relevant doc shows up.
        </>
      )}
    </p>
  );
}
