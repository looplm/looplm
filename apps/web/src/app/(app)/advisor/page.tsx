"use client";

import { useEffect, useState } from "react";
import {
  getIntegrations,
  triggerAdvisorAnalysis,
  getAdvisorSuggestions,
  type Integration,
  type Suggestion,
  type AdvisorResponse,
} from "@/lib/api";

const CATEGORY_LABELS: Record<string, string> = {
  time_to_value: "⚡ Time to Value",
  output_quality: "✨ Output Quality",
  architecture: "🏗️ Architecture",
};

const IMPACT_COLORS: Record<string, string> = {
  high: "bg-red-500/20 text-red-300 border-red-500/30",
  medium: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  low: "bg-green-500/20 text-green-300 border-green-500/30",
};

function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-lg p-4">
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-medium text-sm">{suggestion.title}</h3>
        <span className={`text-[10px] px-2 py-0.5 rounded border shrink-0 ml-2 ${IMPACT_COLORS[suggestion.impact]}`}>
          {suggestion.impact}
        </span>
      </div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-3">{suggestion.description}</p>
      <div className="flex items-center gap-3 mb-2">
        <div className="flex items-center gap-1.5 flex-1">
          <span className="text-[10px] text-gray-400 dark:text-slate-500">Confidence</span>
          <div className="flex-1 h-1.5 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-indigo-500 rounded-full"
              style={{ width: `${suggestion.confidence * 100}%` }}
            />
          </div>
          <span className="text-[10px] text-gray-500 dark:text-slate-400">{(suggestion.confidence * 100).toFixed(0)}%</span>
        </div>
      </div>
      {suggestion.reasoning && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300"
        >
          {expanded ? "Hide reasoning ▴" : "Show reasoning ▾"}
        </button>
      )}
      {expanded && suggestion.reasoning && (
        <div className="mt-2 p-3 bg-gray-100/50 dark:bg-slate-800/50 rounded text-xs text-gray-600 dark:text-slate-300 leading-relaxed">
          {suggestion.reasoning}
        </div>
      )}
    </div>
  );
}

export default function AdvisorPage() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [selectedIntegration, setSelectedIntegration] = useState("");
  const [advisorData, setAdvisorData] = useState<AdvisorResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getIntegrations().then((r) => {
      const filtered = r.data.filter((i) => i.type !== "json_file");
      setIntegrations(filtered);
      if (filtered.length > 0) setSelectedIntegration(filtered[0].id);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedIntegration) return;
    setLoading(true);
    getAdvisorSuggestions(selectedIntegration)
      .then(setAdvisorData)
      .catch(() => setAdvisorData(null))
      .finally(() => setLoading(false));
  }, [selectedIntegration]);

  const handleAnalyze = async () => {
    if (!selectedIntegration) return;
    setAnalyzing(true);
    setError(null);
    try {
      const result = await triggerAdvisorAnalysis(selectedIntegration);
      setAdvisorData(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const grouped = advisorData?.suggestions.reduce<Record<string, Suggestion[]>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {}) ?? {};

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-bold">Architecture Advisor</h1>
        <button
          onClick={handleAnalyze}
          disabled={analyzing || !selectedIntegration}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {analyzing ? "Analyzing..." : "Run Analysis"}
        </button>
      </div>

      <div className="flex items-center gap-4 mb-6">
        <select
          value={selectedIntegration}
          onChange={(e) => setSelectedIntegration(e.target.value)}
          className="px-3 py-2 bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg text-sm"
        >
          <option value="">Select integration</option>
          {integrations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
        {advisorData?.analyzed_at && (
          <span className="text-xs text-gray-400 dark:text-slate-500">
            Last analyzed: {new Date(advisorData.analyzed_at).toLocaleString()}
          </span>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">Loading...</div>
      ) : !advisorData || advisorData.suggestions.length === 0 ? (
        <div className="rounded-xl bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 p-12 text-center text-gray-500 dark:text-slate-400">
          No suggestions yet. Click &quot;Run Analysis&quot; to get started.
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(grouped).map(([category, suggestions]) => (
            <div key={category}>
              <h2 className="text-lg font-semibold mb-4">
                {CATEGORY_LABELS[category] ?? category}
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {suggestions.map((s, i) => (
                  <SuggestionCard key={i} suggestion={s} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
