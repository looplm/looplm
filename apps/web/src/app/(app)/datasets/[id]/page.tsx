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
import { TestCaseModal, type TestCaseFormData } from "./test-case-modal";

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const highlightTestId = searchParams.get("highlight") || undefined;
  const highlightRef = useRef<HTMLTableRowElement>(null);
  const [dataset, setDataset] = useState<TestDatasetDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [editingCase, setEditingCase] = useState<TestCaseItem | null>(null);
  const [saving, setSaving] = useState(false);

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

      const body: Partial<TestCaseCreateBody> = {
        test_id: form.test_id,
        prompt: form.prompt,
        expected_answer: form.expected_answer || undefined,
        team_filter: (team_filter as string[]) || [],
        tag_filter: (tag_filter as string[]) || [],
        expected_sources: (expected_sources as string[]) || [],
        expected_page_urls: (expected_page_urls as string[]) || [],
        expected_source_types: (expected_source_types as string[]) || [],
        max_answer_length: (max_answer_length as number) ?? null,
        context_filters: (context_filters as Record<string, string>) || {},
        metadata: Object.keys(extraMetadata).length > 0 ? extraMetadata : {},
      };

      if (editingCase) {
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

  async function handleDeleteCase(caseId: string) {
    if (!confirm("Delete this test case?")) return;
    try {
      await deleteTestCase(id, caseId);
      await load();
    } catch {
      // ignore
    }
  }

  if (loading) return <p className="text-gray-500 dark:text-slate-400">Loading...</p>;
  if (!dataset) return <p className="text-gray-500 dark:text-slate-400">Dataset not found.</p>;

  const cases = dataset.test_cases;

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
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
        <StatCard label="Test Cases" value={dataset.test_count} />
        <StatCard
          label="With Expected Answer"
          value={cases.filter((c) => c.expected_answer).length}
          sub={`of ${cases.length}`}
        />
        <StatCard
          label="With Conditions"
          value={cases.filter((c) => c.team_filter.length > 0 || Object.keys(c.context_filters).length > 0).length}
        />
      </div>

      {/* Add button */}
      <div className="mb-4">
        <button
          onClick={() => { setEditingCase(null); setShowModal(true); }}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-sm hover:bg-indigo-500 transition-colors"
        >
          Add Test Case
        </button>
      </div>

      {/* Cases Table */}
      {cases.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No test cases yet. Add one manually or use the Suggestions tab on the Feedback page.
        </div>
      ) : (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-slate-800 text-left text-gray-500 dark:text-slate-400">
                <th className="px-4 py-3 font-medium">Test ID</th>
                <th className="px-4 py-3 font-medium">Prompt</th>
                <th className="px-4 py-3 font-medium">Conditions</th>
                <th className="px-4 py-3 font-medium w-28"></th>
              </tr>
            </thead>
            <tbody>
              {cases.map((tc) => (
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
                    <TestCaseConditions data={tc} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); setEditingCase(tc); setShowModal(true); }}
                        className="text-gray-400 dark:text-slate-500 hover:text-indigo-500 dark:hover:text-indigo-400 text-xs"
                      >
                        Edit
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteCase(tc.id); }}
                        className="text-gray-400 dark:text-slate-500 hover:text-red-500 dark:hover:text-red-400 text-xs"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
    </div>
  );
}
