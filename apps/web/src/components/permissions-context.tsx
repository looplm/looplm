"use client";

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { getMyPermissions, getSelectedProjectId, type ProjectPermissions } from "@/lib/api";

interface PermissionsContextValue {
  role: ProjectPermissions["role"];
  allowedSections: string[];
  isAdmin: boolean;
  loading: boolean;
  canAccess: (section: string) => boolean;
  refresh: () => void;
}

const PermissionsContext = createContext<PermissionsContextValue>({
  role: "owner",
  allowedSections: ["observe", "evaluate", "improve"],
  isAdmin: true,
  loading: true,
  canAccess: () => true,
  refresh: () => {},
});

export function PermissionsProvider({ children }: { children: React.ReactNode }) {
  const [role, setRole] = useState<ProjectPermissions["role"]>("owner");
  const [allowedSections, setAllowedSections] = useState<string[]>([
    "observe",
    "evaluate",
    "improve",
  ]);
  const [loading, setLoading] = useState(true);

  const fetchPermissions = useCallback(() => {
    getMyPermissions()
      .then((data) => {
        setRole(data.role);
        setAllowedSections(data.allowed_sections);
      })
      .catch(() => {
        // On error, default to full access (existing owner-only behavior)
        setRole("owner");
        setAllowedSections(["observe", "evaluate", "improve"]);
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

  return (
    <PermissionsContext.Provider
      value={{ role, allowedSections, isAdmin, loading, canAccess, refresh: fetchPermissions }}
    >
      {children}
    </PermissionsContext.Provider>
  );
}

export function usePermissions() {
  return useContext(PermissionsContext);
}
