"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  getDataset,
  createTestCase,
  updateTestCase,
  deleteTestCase,
  type TestDatasetDetail,
  type TestCaseItem,
  type TestCaseCreateBody,
} from "@/lib/api";
import { StatCard } from "@/components/eval-shared";
import { TestCaseConditions } from "@/components/test-case-conditions";
import { NO_RETRIEVAL_TAG, isNoRetrievalExpected } from "@/lib/test-case-tags";
import { ConfirmModal } from "@/components/confirm-modal";
import { TestCaseModal, type TestCaseFormData } from "./test-case-modal";
import { NeedsWorkModal } from "./needs-work-modal";
import { SyncExpectedUrlsModal } from "../sync-expected-urls-modal";

function FlagIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 3v1.5M3 21v-6m0 0l2.77-.693a9 9 0 016.208.682l.108.054a9 9 0 006.086.71l3.114-.732a48.524 48.524 0 01-.005-10.499l-3.11.732a9 9 0 01-6.085-.711l-.108-.054a9 9 0 00-6.208-.682L3 4.5M3 15V4.5" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function CheckCircleIcon({ filled }: { filled?: boolean }) {
  return (
    <svg className="w-4 h-4" fill={filled ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      {filled ? (
        <path fillRule="evenodd" clipRule="evenodd" d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75s4.365 9.75 9.75 9.75 9.75-4.365 9.75-9.75S17.385 2.25 12 2.25zm4.28 6.97a.75.75 0 010 1.06l-5.25 5.25a.75.75 0 01-1.06 0l-2.25-2.25a.75.75 0 111.06-1.06l1.72 1.72 4.72-4.72a.75.75 0 011.06 0z" />
      ) : (
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      )}
    </svg>
  );
}

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const highlightTestId = searchParams.get("highlight") || undefined;
  const editCaseId = searchParams.get("edit") || undefined;
  const editOpenedRef = useRef(false);
  const highlightRef = useRef<HTMLTableRowElement>(null);
  const [dataset, setDataset] = useState<TestDatasetDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingCase, setEditingCase] = useState<TestCaseItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteCase, setDeleteCase] = useState<TestCaseItem | null>(null);
  const [needsWorkCase, setNeedsWorkCase] = useState<TestCaseItem | null>(null);
  const [statusSaving, setStatusSaving] = useState(false);
  const [showSyncModal, setShowSyncModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getDataset(id);
      setDataset(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (highlightTestId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightTestId, dataset]);

  // Deep-link from the duplicates view: open the edit modal for a specific case.
  useEffect(() => {
    if (!editCaseId || editOpenedRef.current || !dataset) return;
    const target = dataset.test_cases.find((c) => c.id === editCaseId);
    if (target) {
      editOpenedRef.current = true;
      setEditingCase(target);
      setShowModal(true);
    }
  }, [editCaseId, dataset]);

  async function handleSave(form: TestCaseFormData) {
    setSaving(true);
    try {
      const config = form.config_json.trim()
        ? JSON.parse(form.config_json) as Record<string, unknown>
        : {};

      const {
        team_filter, tag_filter, expected_sources,
        expected_page_urls, expected_source_types,
        max_answer_length, context_filters,
        ...extraMetadata
      } = config;

      // The reserved no-retrieval-expected tag is the only tag the UI edits; keep any others.
      const otherTags = (editingCase?.tags ?? []).filter((t) => t !== NO_RETRIEVAL_TAG);
      const body: Partial<TestCaseCreateBody> & { status?: string; status_note?: string | null; validated?: boolean } = {
        test_id: form.test_id,
        prompt: form.prompt,
        expected_answer: form.expected_answer || undefined,
        team_filter: (team_filter as string[]) || [],
        tag_filter: (tag_filter as string[]) || [],
        expected_sources: (expected_sources as string[]) || [],
        // A negative case must carry no retrieval ground truth.
        expected_page_urls: form.no_retrieval ? [] : (expected_page_urls as string[]) || [],
        expected_source_types: (expected_source_types as string[]) || [],
        max_answer_length: (max_answer_length as number) ?? null,
        context_filters: (context_filters as Record<string, string>) || {},
        metadata: Object.keys(extraMetadata).length > 0 ? extraMetadata : {},
        tags: form.no_retrieval ? [...otherTags, NO_RETRIEVAL_TAG] : otherTags,
      };

      if (editingCase) {
        if (editingCase.status === "needs_work" && form.reactivate) {
          body.status = "active";
          body.status_note = null;
        }
        if (form.validated !== editingCase.validated) {
          body.validated = form.validated;
        }
        await updateTestCase(id, editingCase.id, body);
      } else {
        await createTestCase(id, body as TestCaseCreateBody);
      }
      setShowModal(false);
      setEditingCase(null);
      await load();
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmDelete() {
    if (!deleteCase) return;
    try {
      await deleteTestCase(id, deleteCase.id);
      await load();
    } catch {
      // ignore
    } finally {
      setDeleteCase(null);
    }
  }

  async function handleMarkNeedsWork(note: string) {
    if (!needsWorkCase) return;
    setStatusSaving(true);
    try {
      await updateTestCase(id, needsWorkCase.id, {
        status: "needs_work",
        status_note: note.trim() || null,
      });
      await load();
    } catch {
      // ignore
    } finally {
      setStatusSaving(false);
      setNeedsWorkCase(null);
    }
  }

  async function handleMarkFixed(tc: TestCaseItem) {
    try {
      await updateTestCase(id, tc.id, { status: "active", status_note: null });
      await load();
    } catch {
      // ignore
    }
  }

  async function handleToggleValidated(tc: TestCaseItem) {
    try {
      await updateTestCase(id, tc.id, { validated: !tc.validated });
      await load();
    } catch {
      // ignore
    }
  }

  if (loading) return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  if (!dataset) return <p className="text-gray-500 dark:text-slate-400">Dataset not found.</p>;

  const cases = dataset.test_cases;
  const activeCases = cases.filter((c) => c.status !== "needs_work");
  const needsWorkCases = cases.filter((c) => c.status === "needs_work");

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link href="/datasets" className="text-sm text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 mb-2 inline-block">
          &larr; Datasets
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">{dataset.name}</h2>
            {dataset.description && (
              <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">{dataset.description}</p>
            )}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <StatCard
          label="Test Cases"
          value={activeCases.length}
          sub={needsWorkCases.length > 0 ? `of ${cases.length} total` : undefined}
        />
        <StatCard
          label="With Expected Answer"
          value={activeCases.filter((c) => c.expected_answer).length}
          sub={`of ${activeCases.length}`}
        />
        <StatCard
          label="With Conditions"
          value={activeCases.filter((c) => c.team_filter.length > 0 || Object.keys(c.context_filters).length > 0).length}
        />
        <StatCard
          label="Validated"
          value={dataset.validated_count}
          accent={dataset.validated_count > 0 ? "green" : undefined}
          sub={`of ${cases.length}`}
        />
        <StatCard
          label="Needs Work"
          value={needsWorkCases.length}
          accent={needsWorkCases.length > 0 ? "amber" : undefined}
          sub="excluded from eval runs"
        />
      </div>

      {/* Actions */}
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={() => { setEditingCase(null); setShowModal(true); }}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 transition-colors"
        >
          Add Test Case
        </button>
        <button
          onClick={() => setShowSyncModal(true)}
          title="Derive expected page URLs from chunk relevance labels"
          className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-sm text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
        >
          Sync Expected URLs from Labels
        </button>
      </div>

      {/* Cases Table */}
      {activeCases.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          {needsWorkCases.length > 0
            ? "All test cases are marked as needing work."
            : "No test cases yet. Add one manually or use the Suggestions tab on the Feedback page."}
        </div>
      ) : (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                <th className="px-4 py-3 font-medium">Test ID</th>
                <th className="px-4 py-3 font-medium">Prompt</th>
                <th className="px-4 py-3 font-medium">Conditions</th>
                <th className="px-4 py-3 font-medium w-36"></th>
              </tr>
            </thead>
            <tbody>
              {activeCases.map((tc) => (
                <tr
                  key={tc.id}
                  ref={tc.test_id === highlightTestId ? highlightRef : undefined}
                  onClick={() => { setEditingCase(tc); setShowModal(true); }}
                  className={`border-b border-gray-100/50 dark:border-slate-800/50 hover:bg-gray-100/50 dark:hover:bg-slate-800/30 cursor-pointer ${tc.test_id === highlightTestId ? "ring-2 ring-indigo-500 ring-inset bg-indigo-50/50 dark:bg-indigo-950/20" : ""}`}
                >
                  <td className="px-4 py-3 font-mono text-xs text-indigo-600 dark:text-indigo-400 whitespace-nowrap">
                    {tc.test_id}
                  </td>
                  <td className="px-4 py-3 max-w-xs truncate">{tc.prompt}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-1">
                      {tc.validated && (
                        <span
                          title={`Validated${tc.validated_by_email ? ` by ${tc.validated_by_email}` : ""}`}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                        >
                          validated
                          {tc.validated_by_email && (
                            <span className="font-normal italic opacity-80">by {tc.validated_by_email}</span>
                          )}
                        </span>
                      )}
                      {isNoRetrievalExpected(tc.tags) && (
                        <span
                          title="Negative case: intentionally retrieves nothing; excluded from retrieval metrics"
                          className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300"
                        >
                          no retrieval
                        </span>
                      )}
                      <TestCaseConditions data={tc} />
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleToggleValidated(tc); }}
                        title={tc.validated
                          ? `Validated${tc.validated_by_email ? ` by ${tc.validated_by_email}` : ""} — click to un-validate`
                          : "Mark as validated (reviewer sign-off)"}
                        aria-label={tc.validated ? "Un-validate test case" : "Mark test case as validated"}
                        aria-pressed={tc.validated}
                        className={`p-1.5 rounded-md transition-colors ${
                          tc.validated
                            ? "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
                            : "text-gray-400 dark:text-slate-500 hover:text-emerald-500 dark:hover:text-emerald-400 hover:bg-gray-100 dark:hover:bg-slate-800"
                        }`}
                      >
                        <CheckCircleIcon filled={tc.validated} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setNeedsWorkCase(tc); }}
                        title="Mark as needs work (exclude from eval runs)"
                        aria-label="Mark test case as needs work"
                        className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-amber-500 dark:hover:text-amber-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        <FlagIcon />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingCase(tc); setShowModal(true); }}
                        title="Edit"
                        aria-label="Edit test case"
                        className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        <EditIcon />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteCase(tc); }}
                        title="Delete"
                        aria-label="Delete test case"
                        className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Needs Work section */}
      {needsWorkCases.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-amber-600 dark:text-amber-400"><FlagIcon /></span>
            <h3 className="text-base font-semibold">Needs Work ({needsWorkCases.length})</h3>
            <span className="text-sm text-gray-500 dark:text-slate-400">— excluded from eval runs until fixed</span>
          </div>
          <div className="rounded-xl bg-amber-50/40 dark:bg-amber-950/10 border border-amber-200 dark:border-amber-900/50 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-amber-200/70 dark:border-amber-900/40 text-left text-gray-500 dark:text-slate-400">
                  <th className="px-4 py-3 font-medium">Test ID</th>
                  <th className="px-4 py-3 font-medium">Prompt</th>
                  <th className="px-4 py-3 font-medium">Note</th>
                  <th className="px-4 py-3 font-medium w-44"></th>
                </tr>
              </thead>
              <tbody>
                {needsWorkCases.map((tc) => (
                  <tr
                    key={tc.id}
                    ref={tc.test_id === highlightTestId ? highlightRef : undefined}
                    onClick={() => { setEditingCase(tc); setShowModal(true); }}
                    className={`border-b border-amber-100/60 dark:border-amber-900/30 hover:bg-amber-100/40 dark:hover:bg-amber-950/20 cursor-pointer ${tc.test_id === highlightTestId ? "ring-2 ring-indigo-500 ring-inset" : ""}`}
                  >
                    <td className="px-4 py-3 font-mono text-xs text-amber-700 dark:text-amber-400 whitespace-nowrap">
                      {tc.test_id}
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate">{tc.prompt}</td>
                    <td className="px-4 py-3 max-w-xs truncate text-gray-500 dark:text-slate-400">
                      {tc.status_note || <span className="italic text-gray-400 dark:text-slate-500">No note</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={(e) => { e.stopPropagation(); handleMarkFixed(tc); }}
                          title="Mark as fixed (include in eval runs again)"
                          className="px-2.5 py-1 rounded-md text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30 hover:bg-emerald-100 dark:hover:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-900/50 transition-colors whitespace-nowrap"
                        >
                          Mark fixed
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setEditingCase(tc); setShowModal(true); }}
                          title="Edit"
                          aria-label="Edit test case"
                          className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-amber-100/60 dark:hover:bg-slate-800 transition-colors"
                        >
                          <EditIcon />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); setDeleteCase(tc); }}
                          title="Delete"
                          aria-label="Delete test case"
                          className="p-1.5 rounded-md text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-amber-100/60 dark:hover:bg-slate-800 transition-colors"
                        >
                          <TrashIcon />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Test Case Modal */}
      {showModal && (
        <TestCaseModal
          editingCase={editingCase}
          saving={saving}
          onClose={() => { setShowModal(false); setEditingCase(null); }}
          onSave={handleSave}
        />
      )}

      {/* Sync expected URLs from labels */}
      {showSyncModal && (
        <SyncExpectedUrlsModal
          datasetId={id}
          onClose={() => setShowSyncModal(false)}
          onSynced={load}
        />
      )}

      {/* Needs Work modal */}
      {needsWorkCase && (
        <NeedsWorkModal
          testId={needsWorkCase.test_id}
          saving={statusSaving}
          onConfirm={handleMarkNeedsWork}
          onCancel={() => setNeedsWorkCase(null)}
        />
      )}

      {/* Delete confirmation modal */}
      {deleteCase && (
        <ConfirmModal
          title="Delete Test Case"
          message={`Delete test case "${deleteCase.test_id}"? This action cannot be undone.`}
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={handleConfirmDelete}
          onCancel={() => setDeleteCase(null)}
        />
      )}
    </div>
  );
}
