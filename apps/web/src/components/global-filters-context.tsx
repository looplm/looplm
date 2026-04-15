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

export type UserFilterMode = "exclude" | "include";

export interface GlobalFilters {
  startDate: string;
  endDate: string;
  environment: string;
  userFilterMode: UserFilterMode;
  filteredUsers: string[];
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
      }}
    >
      {children}
    </GlobalFiltersContext.Provider>
  );
}
