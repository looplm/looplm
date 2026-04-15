export type LangsmithRun = {
  id?: string;
  name?: string;
  run_type?: string;
  start_time?: string;
  end_time?: string | null;
  status?: string;
  error?: string | null;
  trace_id?: string | null;
  parent_run_id?: string | null;
  inputs?: unknown;
  outputs?: unknown;
  extra?: Record<string, unknown> | null;
};

export type RunsResponse = {
  status: "ok";
  session_id: string;
  runs_found: number;
  runs: LangsmithRun[];
  next_cursor: string | null;
};

export type RunsState =
  | { state: "loading" }
  | { state: "ready"; data: RunsResponse; items: LangsmithRun[] }
  | { state: "error"; message: string };

export type TraceGroup = {
  id: string;
  runs: LangsmithRun[];
  startTime: string | null;
  root: LangsmithRun | null;
  llmRuns: LangsmithRun[];
  hasError: boolean;
};

export type FiltersState = {
  errorsOnly: boolean;
  runType: string;
  search: string;
};

export const LLM_RUN_TYPES = new Set(["llm", "chat_model", "chat", "llm_call"]);

export const DEFAULT_FILTERS: FiltersState = {
  errorsOnly: false,
  runType: "all",
  search: "",
};

export function formatTimestamp(value?: string | null): string {
  if (!value) return "unknown time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function formatDuration(run: LangsmithRun): string | null {
  if (!run.start_time || !run.end_time) return null;
  const start = new Date(run.start_time).getTime();
  const end = new Date(run.end_time).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  const ms = end - start;
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(2)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds - minutes * 60;
  return `${minutes}m ${remainder.toFixed(0)}s`;
}

export function toPreview(value: unknown, maxLen = 240): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > maxLen ? `${trimmed.slice(0, maxLen)}…` : trimmed;
  }
  try {
    const text = JSON.stringify(value);
    if (!text) return "—";
    return text.length > maxLen ? `${text.slice(0, maxLen)}…` : text;
  } catch {
    return "[unserializable]";
  }
}

function extractMessageContent(message: unknown): string | null {
  if (!message) return null;
  if (typeof message === "string") return message;
  if (typeof message === "object") {
    const record = message as Record<string, unknown>;
    if (typeof record.content === "string") return record.content;
    if (typeof record.text === "string") return record.text;
    if (record.data && typeof record.data === "object") {
      const data = record.data as Record<string, unknown>;
      if (typeof data.content === "string") return data.content;
      if (typeof data.text === "string") return data.text;
    }
  }
  return null;
}

export function extractInput(run: LangsmithRun): string {
  const inputs = run.inputs;
  if (!inputs) return "—";
  if (typeof inputs === "string") return toPreview(inputs);
  if (typeof inputs === "object") {
    const record = inputs as Record<string, unknown>;
    if (typeof record.input === "string") return toPreview(record.input);
    if (typeof record.prompt === "string") return toPreview(record.prompt);
    if (Array.isArray(record.prompts) && record.prompts.length > 0) {
      const first = record.prompts.find((item) => typeof item === "string");
      if (typeof first === "string") return toPreview(first);
    }
    if (Array.isArray(record.messages) && record.messages.length > 0) {
      const lastMessage = [...record.messages]
        .reverse()
        .find((item) => extractMessageContent(item));
      const content = extractMessageContent(lastMessage);
      if (content) return toPreview(content);
    }
  }
  return toPreview(inputs);
}

export function extractOutput(run: LangsmithRun): string {
  const outputs = run.outputs;
  if (!outputs) return "—";
  if (typeof outputs === "string") return toPreview(outputs);
  if (typeof outputs === "object") {
    const record = outputs as Record<string, unknown>;
    if (typeof record.output === "string") return toPreview(record.output);
    if (typeof record.text === "string") return toPreview(record.text);
    if (record.result && typeof record.result === "string") return toPreview(record.result);
    if (Array.isArray(record.generations) && record.generations.length > 0) {
      const firstBatch = record.generations[0];
      if (Array.isArray(firstBatch) && firstBatch.length > 0) {
        const firstGen = firstBatch[0] as Record<string, unknown> | undefined;
        if (firstGen) {
          if (typeof firstGen.text === "string") return toPreview(firstGen.text);
          if (firstGen.message && typeof firstGen.message === "object") {
            const message = firstGen.message as Record<string, unknown>;
            if (typeof message.content === "string") return toPreview(message.content);
          }
        }
      }
    }
  }
  return toPreview(outputs);
}

export function extractModel(run: LangsmithRun): string | null {
  if (!run.extra || typeof run.extra !== "object") return null;
  const extra = run.extra as Record<string, unknown>;
  const invocation = extra.invocation_params as Record<string, unknown> | undefined;
  if (invocation) {
    const direct = invocation.model || invocation.model_name || invocation.model_id;
    if (typeof direct === "string" && direct.trim()) return direct;
  }
  const model = extra.model as Record<string, unknown> | undefined;
  if (model) {
    const name = model.name || model.id;
    if (typeof name === "string" && name.trim()) return name;
  }
  const provider = extra.provider || extra.model_provider;
  if (typeof provider === "string" && provider.trim()) return provider;
  return null;
}

export function groupRunsByTrace(runs: LangsmithRun[]): TraceGroup[] {
  const byTrace = new Map<string, LangsmithRun[]>();

  const normalizeId = (value: string | null | undefined): string | null => {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  };

  const uniqueRuns: LangsmithRun[] = [];
  const seenIds = new Set<string>();

  runs.forEach((run) => {
    const id = normalizeId(run.id);
    if (id) {
      if (seenIds.has(id)) return;
      seenIds.add(id);
    }
    uniqueRuns.push(run);
  });

  uniqueRuns.forEach((run, index) => {
    const traceId = normalizeId(run.trace_id);
    const key = traceId || normalizeId(run.id) || `run-${index}`;

    const current = byTrace.get(key);
    if (current) {
      current.push(run);
    } else {
      byTrace.set(key, [run]);
    }
  });

  const groups: TraceGroup[] = [];
  byTrace.forEach((items, id) => {
    const sorted = [...items].sort((a, b) => {
      const aTime = a.start_time ? new Date(a.start_time).getTime() : 0;
      const bTime = b.start_time ? new Date(b.start_time).getTime() : 0;
      return aTime - bTime;
    });

    const ids = new Set(sorted.map((run) => run.id).filter(Boolean));
    const root =
      sorted.find((run) => !run.parent_run_id || !ids.has(run.parent_run_id)) ||
      sorted[0] ||
      null;

    const startTime = sorted[0]?.start_time ?? null;
    const llmRuns = sorted.filter((run) =>
      run.run_type ? LLM_RUN_TYPES.has(run.run_type) : false
    );
    const hasError = sorted.some((run) => Boolean(run.error));

    groups.push({
      id,
      runs: sorted,
      startTime,
      root,
      llmRuns,
      hasError,
    });
  });

  groups.sort((a, b) => {
    const aTime = a.startTime ? new Date(a.startTime).getTime() : 0;
    const bTime = b.startTime ? new Date(b.startTime).getTime() : 0;
    return bTime - aTime;
  });

  return groups;
}

export async function copyToClipboard(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // ignore and fallback
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const success = document.execCommand("copy");
    document.body.removeChild(textarea);
    return success;
  } catch {
    return false;
  }
}
