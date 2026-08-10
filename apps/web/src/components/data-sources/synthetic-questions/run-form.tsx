"use client";

/**
 * Configuration form for a synthetic-question run: what to sample, how many questions per
 * chunk, how many unanswerable negatives, and where the resulting cases land.
 */

import { useEffect, useState } from "react";

import { getDatasets, getIndexTree, getPartitionKeys } from "@/lib/api";
import type { PartitionKey } from "@/lib/api-types/rag-coverage";
import type {
  SyntheticQuestionRunRequest,
  SyntheticScope,
} from "@/lib/api-types/synthetic-questions";

type RunBody = Omit<SyntheticQuestionRunRequest, "provider_id">;

interface PartitionValue {
  value: string;
  doc_count: number;
}

const FIELD =
  "w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm";
const LABEL = "block text-xs font-medium text-gray-600 dark:text-slate-300 mb-1";

export function RunForm({
  providerId,
  disabled,
  onStart,
}: {
  providerId: string;
  disabled: boolean;
  onStart: (body: RunBody) => void;
}) {
  const [scope, setScope] = useState<SyntheticScope>("corpus");
  const [partitionKeys, setPartitionKeys] = useState<PartitionKey[]>([]);
  const [partitionKey, setPartitionKey] = useState("");
  const [partitionValues, setPartitionValues] = useState<PartitionValue[]>([]);
  const [partitionValue, setPartitionValue] = useState("");
  const [loadingValues, setLoadingValues] = useState(false);
  const [sampleSize, setSampleSize] = useState(50);
  const [questionsPerChunk, setQuestionsPerChunk] = useState(2);
  const [negativeShare, setNegativeShare] = useState(15);
  const [verifyNegatives, setVerifyNegatives] = useState(true);
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [datasetName, setDatasetName] = useState("");

  useEffect(() => {
    getPartitionKeys(providerId)
      .then(({ data }) => setPartitionKeys(data))
      .catch(() => setPartitionKeys([]));
    getDatasets({ per_page: "200" })
      .then((res) => setDatasets(res.data.map((d) => ({ id: d.id, name: d.name }))))
      .catch(() => setDatasets([]));
  }, [providerId]);

  // Partition values come from the same tree endpoint the index breakdown uses, so the
  // picker always shows exactly the buckets that exist, with their chunk counts.
  useEffect(() => {
    if (scope !== "partition" || !partitionKey) {
      setPartitionValues([]);
      setPartitionValue("");
      return;
    }
    let cancelled = false;
    setLoadingValues(true);
    getIndexTree({ providerId, levels: [[partitionKey]], limit: 200 })
      .then((res) => {
        if (cancelled) return;
        const groups = res.sections[0]?.groups ?? [];
        setPartitionValues(groups.map((g) => ({ value: g.value, doc_count: g.doc_count })));
      })
      .catch(() => !cancelled && setPartitionValues([]))
      .finally(() => !cancelled && setLoadingValues(false));
    return () => {
      cancelled = true;
    };
  }, [providerId, scope, partitionKey]);

  const partitionIncomplete = scope === "partition" && !(partitionKey && partitionValue);

  const body = (persist: boolean, size: number): RunBody => ({
    scope,
    partition_key: scope === "partition" ? partitionKey : null,
    partition_value: scope === "partition" ? partitionValue : null,
    sample_size: size,
    questions_per_chunk: questionsPerChunk,
    negative_share: negativeShare,
    verify_negatives: verifyNegatives,
    persist,
    dataset_id: persist && datasetId ? datasetId : null,
    dataset_name: persist && !datasetId ? datasetName.trim() || null : null,
  });

  return (
    <div className="rounded-xl border border-gray-200 dark:border-slate-700 p-4 mb-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <label className={LABEL} htmlFor="syn-scope">
            Chunks to draw from
          </label>
          <select
            id="syn-scope"
            className={FIELD}
            value={scope}
            onChange={(e) => setScope(e.target.value as SyntheticScope)}
          >
            <option value="corpus">Whole index</option>
            <option value="partition">One category</option>
          </select>
        </div>

        {scope === "partition" && (
          <>
            <div>
              <label className={LABEL} htmlFor="syn-partition-key">
                Category field
              </label>
              <select
                id="syn-partition-key"
                className={FIELD}
                value={partitionKey}
                onChange={(e) => setPartitionKey(e.target.value)}
              >
                <option value="">Select a field</option>
                {partitionKeys.map((k) => (
                  <option key={k.key} value={k.key}>
                    {k.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="syn-partition-value">
                Value
              </label>
              <select
                id="syn-partition-value"
                className={FIELD}
                value={partitionValue}
                onChange={(e) => setPartitionValue(e.target.value)}
                disabled={!partitionKey || loadingValues}
              >
                <option value="">
                  {loadingValues ? "Loading values…" : "Select a value"}
                </option>
                {partitionValues.map((v) => (
                  <option key={v.value} value={v.value}>
                    {v.value} ({v.doc_count.toLocaleString()})
                  </option>
                ))}
              </select>
            </div>
          </>
        )}

        <div>
          <label className={LABEL} htmlFor="syn-sample">
            Chunks to sample
          </label>
          <input
            id="syn-sample"
            type="number"
            min={1}
            max={1000}
            className={FIELD}
            value={sampleSize}
            onChange={(e) => setSampleSize(Number(e.target.value) || 1)}
          />
        </div>

        <div>
          <label className={LABEL} htmlFor="syn-per-chunk">
            Questions per chunk
          </label>
          <select
            id="syn-per-chunk"
            className={FIELD}
            value={questionsPerChunk}
            onChange={(e) => setQuestionsPerChunk(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-gray-500 dark:text-slate-400">
            One uses the chunk&apos;s own wording, the rest are paraphrased.
          </p>
        </div>

        <div>
          <label className={LABEL} htmlFor="syn-negatives">
            Unanswerable share
          </label>
          <div className="flex items-center gap-2">
            <input
              id="syn-negatives"
              type="number"
              min={0}
              max={50}
              className={FIELD}
              value={negativeShare}
              onChange={(e) => setNegativeShare(Number(e.target.value) || 0)}
            />
            <span className="text-sm text-gray-500 dark:text-slate-400">%</span>
          </div>
          {negativeShare > 0 && (
            <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-slate-400">
              <input
                type="checkbox"
                checked={verifyNegatives}
                onChange={(e) => setVerifyNegatives(e.target.checked)}
              />
              Check each one against the index first
            </label>
          )}
        </div>

        <div className="sm:col-span-2">
          <label className={LABEL} htmlFor="syn-dataset">
            Save into
          </label>
          <select
            id="syn-dataset"
            className={FIELD}
            value={datasetId}
            onChange={(e) => setDatasetId(e.target.value)}
          >
            <option value="">A new dataset</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          {!datasetId && (
            <input
              className={`${FIELD} mt-2`}
              placeholder="New dataset name (optional)"
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
            />
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          onClick={() => onStart(body(true, sampleSize))}
          disabled={disabled || partitionIncomplete}
          className="px-3 py-2 rounded-lg text-sm bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          Generate dataset
        </button>
        <button
          onClick={() => onStart(body(false, Math.min(5, sampleSize)))}
          disabled={disabled || partitionIncomplete}
          className="px-3 py-2 rounded-lg text-sm border border-gray-200 dark:border-slate-700 hover:bg-gray-50 dark:hover:bg-slate-800 disabled:opacity-50"
        >
          Preview 5 chunks
        </button>
        {partitionIncomplete && (
          <span className="text-xs text-gray-500 dark:text-slate-400">
            Pick a category field and value first.
          </span>
        )}
      </div>
    </div>
  );
}
