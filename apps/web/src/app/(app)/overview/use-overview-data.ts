"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getOverviewSources,
  getOverviewSummary,
  type OverviewBucket,
  type OverviewSummary,
  type SourcesOverview,
} from "@/lib/api";
import { useGlobalFilters, daysAgo, nowLocal } from "@/components/global-filters-context";
import { userFilterArrays } from "@/lib/user-filter-params";
import { BUCKET_MIN_DAYS, BUCKET_WIDEN_DAYS } from "./overview-constants";
import { rangeInDays } from "./overview-format";

function isBucket(value: string | null): value is OverviewBucket {
  return value === "day" || value === "week" || value === "month";
}

/** The largest bucket a range of `days` can meaningfully show. */
function largestUsableBucket(days: number): OverviewBucket {
  if (days >= BUCKET_MIN_DAYS.month) return "month";
  if (days >= BUCKET_MIN_DAYS.week) return "week";
  return "day";
}

export function useOverviewData() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const {
    startDate,
    endDate,
    environment,
    userFilterMode,
    effectiveUserIds,
    traceNames,
    currentProject,
    setDateRange,
  } = useGlobalFilters();

  const [bucket, setBucketState] = useState<OverviewBucket>(() => {
    const fromUrl = searchParams.get("bkt");
    return isBucket(fromUrl) ? fromUrl : "day";
  });
  const [notice, setNotice] = useState<string | null>(null);

  const [summary, setSummary] = useState<OverviewSummary | null>(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [summaryError, setSummaryError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [sources, setSources] = useState<SourcesOverview | null>(null);
  const [sourcesLoaded, setSourcesLoaded] = useState(false);
  const [sourcesError, setSourcesError] = useState<unknown>(null);

  // One hover index shared by all three charts, so the crosshair lines up across them.
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);

  const days = useMemo(() => rangeInDays(startDate, endDate), [startDate, endDate]);

  /**
   * Written synchronously from the click handler, not from a debounced effect. The global
   * filter context also calls router.replace on this URL, but it only ever touches its own
   * keys, so `bkt` survives as long as it lands before that 300ms timer fires. Read from
   * window.location.search rather than the possibly-stale searchParams snapshot.
   */
  const writeBucketToUrl = useCallback(
    (next: OverviewBucket) => {
      const params = new URLSearchParams(window.location.search);
      if (next === "day") params.delete("bkt");
      else params.set("bkt", next);
      const qs = params.toString();
      router.replace(qs ? `/overview?${qs}` : "/overview", { scroll: false });
    },
    [router],
  );

  const setBucket = useCallback(
    (next: OverviewBucket) => {
      setBucketState(next);
      writeBucketToUrl(next);
      setNotice(null);
    },
    [writeBucketToUrl],
  );

  /**
   * Widen the shared range and switch bucket in one gesture. The page must not silently
   * mutate a range that is shared across pages and synced to the URL, but making it one
   * explicit click is fair.
   */
  const selectBucketWidening = useCallback(
    (next: OverviewBucket) => {
      const widenTo = BUCKET_WIDEN_DAYS[next];
      setDateRange(daysAgo(widenTo), nowLocal());
      setBucketState(next);
      writeBucketToUrl(next);
      setNotice(`Date range widened to ${widenTo} days.`);
    },
    [setDateRange, writeBucketToUrl],
  );

  // Narrowing the range below the current bucket's minimum would collapse every chart to
  // one or two bars, so demote instead of rendering something useless.
  useEffect(() => {
    if (days === 0) return;
    if (days >= BUCKET_MIN_DAYS[bucket]) return;
    const demoted = largestUsableBucket(days);
    if (demoted === bucket) return;
    setBucketState(demoted);
    writeBucketToUrl(demoted);
    setNotice(`Switched to ${demoted} buckets for a ${days} day range.`);
  }, [days, bucket, writeBucketToUrl]);

  useEffect(() => {
    if (!startDate) return;
    let cancelled = false;
    setRefreshing(true);
    setSummaryError(null);
    getOverviewSummary({
      bucket,
      start_date: new Date(startDate).toISOString(),
      end_date: new Date(endDate).toISOString(),
      environment: environment || undefined,
      ...userFilterArrays({ userFilterMode, effectiveUserIds }),
    })
      .then((data) => {
        // Guarded because the date inputs debounce: without this, a slow earlier request
        // can land after a newer one and overwrite it.
        if (cancelled) return;
        setSummary(data);
        setSummaryLoaded(true);
      })
      .catch((err) => {
        if (!cancelled) setSummaryError(err);
      })
      .finally(() => {
        if (!cancelled) setRefreshing(false);
      });
    return () => {
      cancelled = true;
    };
    // traceNames is included because the trace-type filter claims to scope every Observe
    // number, and this page aggregates exactly those.
  }, [startDate, endDate, bucket, environment, userFilterMode, effectiveUserIds, traceNames]);

  useEffect(() => {
    // currentProject resolves asynchronously; the client reads the project id from
    // localStorage, so firing early would just waste a request.
    if (!currentProject) return;
    let cancelled = false;
    setSourcesError(null);
    getOverviewSources()
      .then((data) => {
        if (cancelled) return;
        setSources(data);
        setSourcesLoaded(true);
      })
      .catch((err) => {
        if (!cancelled) setSourcesError(err);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProject?.id]);

  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!notice) return;
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 6000);
    return () => {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    };
  }, [notice]);

  return {
    bucket,
    setBucket,
    selectBucketWidening,
    rangeDays: days,
    notice,
    summary,
    summaryLoaded,
    summaryError,
    refreshing,
    sources,
    sourcesLoaded,
    sourcesError,
    providers: sources?.providers ?? [],
    hoveredBucket,
    setHoveredBucket,
  };
}
