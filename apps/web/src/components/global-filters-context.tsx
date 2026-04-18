"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useCallback,
  type ReactNode,
} from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import {
  getProjects,
  getSelectedProjectId,
  getTraceNames,
  updateProject,
  type Project,
} from "@/lib/api";

export type UserFilterMode = "exclude" | "include";

export interface GlobalFilters {
  startDate: string;
  endDate: string;
  environment: string;
  userFilterMode: UserFilterMode;
  filteredUsers: string[];
  traceNames: string[];
}

interface GlobalFiltersContextValue extends GlobalFilters {
  setStartDate: (v: string) => void;
  setEndDate: (v: string) => void;
  setEnvironment: (v: string) => void;
  setUserFilterMode: (v: UserFilterMode) => void;
  setFilteredUsers: (v: string[]) => void;
  setDateRange: (start: string, end: string) => void;
  resetFilters: () => void;
  hasActiveFilters: boolean;
  // Persistent trace-name scope (project setting)
  traceNameOptions: string[];
  canEditTraceNames: boolean;
  traceNamesSaving: boolean;
  traceNamesError: string | null;
  setTraceNames: (names: string[]) => Promise<void>;
}

const GlobalFiltersContext = createContext<GlobalFiltersContextValue | null>(null);

export function useGlobalFilters(): GlobalFiltersContextValue {
  const ctx = useContext(GlobalFiltersContext);
  if (!ctx) throw new Error("useGlobalFilters must be used within GlobalFiltersProvider");
  return ctx;
}

export function GlobalFiltersProvider({ children }: { children: ReactNode }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const [startDate, setStartDate] = useState(() => searchParams.get("sd") || "");
  const [endDate, setEndDate] = useState(() => searchParams.get("ed") || "");
  const [environment, setEnvironment] = useState(() => searchParams.get("env") || "all");
  const [userFilterMode, setUserFilterMode] = useState<UserFilterMode>(
    () => (searchParams.get("ufm") as UserFilterMode) || "exclude"
  );
  const [filteredUsers, setFilteredUsers] = useState<string[]>(() => {
    const val = searchParams.get("ufl");
    return val ? val.split(",") : [];
  });

  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [traceNames, setTraceNamesState] = useState<string[]>([]);
  const [traceNameOptions, setTraceNameOptions] = useState<string[]>([]);
  const [traceNamesSaving, setTraceNamesSaving] = useState(false);
  const [traceNamesError, setTraceNamesError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getProjects()
      .then(({ data }) => {
        if (cancelled) return;
        const storedId = getSelectedProjectId();
        const project = data.find((p) => p.id === storedId) ?? data[0] ?? null;
        setCurrentProject(project);
        const names = project?.settings?.observe_trace_names;
        if (Array.isArray(names)) setTraceNamesState(names);
      })
      .catch(() => {});
    getTraceNames()
      .then((names) => { if (!cancelled) setTraceNameOptions(names); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const canEditTraceNames = currentProject?.role === "owner";

  const setTraceNames = useCallback(async (next: string[]) => {
    if (!currentProject || currentProject.role !== "owner") return;
    const prev = traceNames;
    setTraceNamesState(next);
    setTraceNamesSaving(true);
    setTraceNamesError(null);
    try {
      await updateProject(currentProject.id, {
        settings: { observe_trace_names: next },
      });
      setCurrentProject((p) =>
        p ? { ...p, settings: { ...(p.settings || {}), observe_trace_names: next } } : p,
      );
    } catch (e: unknown) {
      setTraceNamesState(prev);
      setTraceNamesError(e instanceof Error ? e.message : "Failed to save trace filter");
    } finally {
      setTraceNamesSaving(false);
    }
  }, [currentProject, traceNames]);

  const setDateRange = useCallback((start: string, end: string) => {
    setStartDate(start);
    setEndDate(end);
  }, []);

  const resetFilters = useCallback(() => {
    setStartDate("");
    setEndDate("");
    setEnvironment("all");
    setUserFilterMode("exclude");
    setFilteredUsers([]);
  }, []);

  // Sync state to URL search params with debounce
  // Use a ref for searchParams to avoid a feedback loop:
  // router.replace() → new searchParams reference → effect re-fires → loop
  const searchParamsRef = useRef(searchParams);
  searchParamsRef.current = searchParams;
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const params = new URLSearchParams(searchParamsRef.current.toString());
      if (startDate) params.set("sd", startDate);
      else params.delete("sd");
      if (endDate) params.set("ed", endDate);
      else params.delete("ed");
      if (environment && environment !== "all") params.set("env", environment);
      else params.delete("env");
      if (filteredUsers.length > 0) {
        params.set("ufm", userFilterMode);
        params.set("ufl", filteredUsers.join(","));
      } else {
        params.delete("ufm");
        params.delete("ufl");
      }

      const qs = params.toString();
      // Skip navigation if URL params haven't actually changed
      if (qs === searchParamsRef.current.toString()) return;
      const target = qs ? `${pathname}?${qs}` : pathname;
      router.replace(target, { scroll: false });
    }, 300);
    return () => clearTimeout(timerRef.current);
  }, [startDate, endDate, environment, userFilterMode, filteredUsers, pathname, router]);

  const hasActiveFilters = !!startDate || !!endDate || (environment !== "all" && environment !== "") || filteredUsers.length > 0;

  return (
    <GlobalFiltersContext.Provider
      value={{
        startDate,
        endDate,
        environment,
        userFilterMode,
        filteredUsers,
        setStartDate,
        setEndDate,
        setEnvironment,
        setUserFilterMode,
        setFilteredUsers,
        setDateRange,
        resetFilters,
        hasActiveFilters,
        traceNames,
        traceNameOptions,
        canEditTraceNames,
        traceNamesSaving,
        traceNamesError,
        setTraceNames,
      }}
    >
      {children}
    </GlobalFiltersContext.Provider>
  );
}
