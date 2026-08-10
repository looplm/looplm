"use client";

import { AdoptionSection } from "./adoption-section";
import { BucketToggle } from "./bucket-toggle";
import { EvalSection } from "./eval-section";
import { FeedbackSection } from "./feedback-section";
import { OverviewKpiRow } from "./overview-kpi-row";
import { SourcesSection } from "./sources-section";
import { useOverviewData } from "./use-overview-data";

export default function OverviewPage() {
  const {
    bucket,
    setBucket,
    selectBucketWidening,
    rangeDays,
    notice,
    summary,
    summaryLoaded,
    summaryError,
    refreshing,
    sources,
    sourcesLoaded,
    sourcesError,
    hoveredBucket,
    setHoveredBucket,
  } = useOverviewData();

  // Skeletons only on genuine first load. Once there is data, a filter change dims the
  // existing charts instead of collapsing the page.
  const summaryLoading = !summaryLoaded && !summaryError;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-slate-100">Overview</h1>
        <BucketToggle
          value={bucket}
          onChange={setBucket}
          rangeDays={rangeDays}
          onWiden={selectBucketWidening}
        />
      </div>
      <p className="text-sm text-gray-500 dark:text-slate-400 mb-6">
        Feedback, adoption, evaluation quality and indexed sources for this project.
      </p>

      {notice ? (
        <div className="mb-4 px-3 py-2 rounded-lg bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900 text-xs text-indigo-700 dark:text-indigo-300">
          {notice}
        </div>
      ) : null}

      {summary ? <OverviewKpiRow kpis={summary.kpis} period={summary.period} /> : null}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <FeedbackSection
          feedback={summary?.feedback ?? null}
          bucket={bucket}
          loading={summaryLoading}
          error={summaryError}
          refreshing={refreshing && summaryLoaded}
          hovered={hoveredBucket}
          onHover={setHoveredBucket}
        />
        <AdoptionSection
          adoption={summary?.adoption ?? null}
          bucket={bucket}
          loading={summaryLoading}
          error={summaryError}
          refreshing={refreshing && summaryLoaded}
          hovered={hoveredBucket}
          onHover={setHoveredBucket}
        />
        <EvalSection
          evals={summary?.evals ?? null}
          bucket={bucket}
          loading={summaryLoading}
          error={summaryError}
          refreshing={refreshing && summaryLoaded}
          hovered={hoveredBucket}
          onHover={setHoveredBucket}
        />
        {/* Sources is Postgres-only and range-independent, so it loads on its own clock. */}
        <SourcesSection
          sources={sources}
          loading={!sourcesLoaded && !sourcesError}
          error={sourcesError}
        />
      </div>
    </div>
  );
}
