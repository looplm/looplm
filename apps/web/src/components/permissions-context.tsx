"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { getMyPermissions, getSelectedProjectId, type ProjectPermissions } from "@/lib/api";

interface PermissionsContextValue {
  role: ProjectPermissions["role"];
  allowedSections: string[];
  allowedPages: string[] | null;
  writePages: string[] | null;
  isAdmin: boolean;
  isPlatformAdmin: boolean;
  loading: boolean;
  canAccess: (section: string) => boolean;
  canAccessPage: (page: string) => boolean;
  canWrite: (page: string) => boolean;
  refresh: () => void;
}

const PermissionsContext = createContext<PermissionsContextValue>({
  role: "owner",
  allowedSections: ["observe", "evaluate", "improve"],
  allowedPages: null,
  writePages: null,
  isAdmin: true,
  isPlatformAdmin: false,
  loading: true,
  canAccess: () => true,
  canAccessPage: () => true,
  canWrite: () => true,
  refresh: () => {},
});

export function PermissionsProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<ProjectPermissions["role"]>("owner");
  const [allowedSections, setAllowedSections] = useState<string[]>([
    "observe",
    "evaluate",
    "improve",
  ]);
  const [allowedPages, setAllowedPages] = useState<string[] | null>(null);
  const [writePages, setWritePages] = useState<string[] | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchPermissions = useCallback(() => {
    getMyPermissions()
      .then((data) => {
        setRole(data.role);
        setAllowedSections(data.allowed_sections);
        setAllowedPages(data.allowed_pages);
        setWritePages(data.write_pages);
        setIsPlatformAdmin(data.is_platform_admin);
      })
      .catch(() => {
        // On error, default to full access (existing owner-only behavior)
        setRole("owner");
        setAllowedSections(["observe", "evaluate", "improve"]);
        setAllowedPages(null);
        setWritePages(null);
        setIsPlatformAdmin(false);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  // Re-fetch when project changes (listen to storage events from other tabs
  // and poll the project ID on focus)
  useEffect(() => {
    let lastProjectId = getSelectedProjectId();

    function handleFocus() {
      const current = getSelectedProjectId();
      if (current !== lastProjectId) {
        lastProjectId = current;
        fetchPermissions();
      }
    }

    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [fetchPermissions]);

  const isAdmin = role === "owner" || role === "admin";
  const canAccess = useCallback(
    (section: string) => allowedSections.includes(section),
    [allowedSections],
  );
  const canAccessPage = useCallback(
    (page: string) => {
      if (allowedPages === null) return true;
      return allowedPages.includes(page);
    },
    [allowedPages],
  );
  const canWrite = useCallback(
    (page: string) => {
      if (role === "owner" || role === "admin") return true;
      if (allowedPages !== null && !allowedPages.includes(page)) return false;
      if (writePages === null) return true; // legacy: null = full write on allowed pages
      return writePages.includes(page);
    },
    [role, allowedPages, writePages],
  );

  return (
    <PermissionsContext.Provider
      value={{
        role,
        allowedSections,
        allowedPages,
        writePages,
        isAdmin,
        isPlatformAdmin,
        loading,
        canAccess,
        canAccessPage,
        canWrite,
        refresh: fetchPermissions,
      }}
    >
      {children}
    </PermissionsContext.Provider>
  );
}

export function usePermissions() {
  return useContext(PermissionsContext);
}
