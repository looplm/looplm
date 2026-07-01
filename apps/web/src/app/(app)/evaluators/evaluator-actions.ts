import { useCallback, useRef } from "react";
import {
  importEvaluators,
  updateEvaluator,
  deleteEvaluator,
  bulkDeleteEvaluators,
  createEvaluator,
  type EvaluatorItem,
} from "@/lib/api";
import type { EvaluatorFormData } from "./evaluator-modal";

interface UseEvaluatorActionsOptions {
  evaluators: EvaluatorItem[];
  editingEvaluator: EvaluatorItem | null;
  setError: (error: string | null) => void;
  setImporting: (importing: boolean) => void;
  setShowModal: (show: boolean) => void;
  setEditingEvaluator: (ev: EvaluatorItem | null) => void;
  load: () => Promise<void>;
}

export function useEvaluatorActions({
  evaluators,
  editingEvaluator,
  setError,
  setImporting,
  setShowModal,
  setEditingEvaluator,
  load,
}: UseEvaluatorActionsOptions) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleImportFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const evs = Array.isArray(parsed) ? parsed : parsed.evaluators;
      if (!Array.isArray(evs) || evs.length === 0) {
        throw new Error("JSON must be an array of evaluators or an object with an 'evaluators' array");
      }
      const result = await importEvaluators(evs);
      await load();
      const msg = `Imported ${result.created} evaluator(s)${result.skipped > 0 ? `, ${result.skipped} skipped (already exist)` : ""}`;
      if (result.created === 0) {
        setError(msg);
      }
    } catch (err: any) {
      setError(err.message || "Import failed");
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [setImporting, setError, load]);

  const handleExport = useCallback(() => {
    const exportData = evaluators.map((ev) => ({
      name: ev.name,
      display_name: ev.display_name,
      type: ev.type,
      description: ev.description,
      relevance: ev.relevance,
      affects_pass: ev.affects_pass,
      config: ev.config,
      source: ev.source,
    }));
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "evaluators.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [evaluators]);

  const handleSave = useCallback(async (form: EvaluatorFormData) => {
    setError(null);
    try {
      let config = {};
      try {
        config = JSON.parse(form.config);
      } catch {
        // keep empty
      }

      if (editingEvaluator) {
        await updateEvaluator(editingEvaluator.id, {
          display_name: form.display_name || undefined,
          description: form.description || undefined,
          relevance: form.relevance,
          affects_pass: form.affects_pass,
          source: form.source as "custom" | "ragas" | "langfuse" | "discovered",
          category: form.category ? (form.category as "retrieval" | "generation") : null,
          config,
        });
      } else {
        await createEvaluator({
          name: form.name,
          display_name: form.display_name || undefined,
          type: form.type,
          source: form.source as "custom" | "ragas" | "langfuse" | "discovered",
          category: form.category ? (form.category as "retrieval" | "generation") : null,
          description: form.description || undefined,
          relevance: form.relevance,
          affects_pass: form.affects_pass,
          config,
        });
      }
      setShowModal(false);
      setEditingEvaluator(null);
      await load();
    } catch (err: any) {
      setError(err.message || "Save failed");
    }
  }, [editingEvaluator, setError, setShowModal, setEditingEvaluator, load]);

  const handleConfirmDelete = useCallback(async (ids: string[]) => {
    try {
      if (ids.length === 1) {
        await deleteEvaluator(ids[0]);
      } else {
        await bulkDeleteEvaluators(ids);
      }
      await load();
    } catch {
      // ignore
    }
  }, [load]);

  const handleToggleEnabled = useCallback(async (ev: EvaluatorItem) => {
    try {
      await updateEvaluator(ev.id, { enabled: !ev.enabled });
      await load();
    } catch {
      // ignore
    }
  }, [load]);

  return {
    fileInputRef,
    handleImportFile,
    handleExport,
    handleSave,
    handleConfirmDelete,
    handleToggleEnabled,
  };
}
