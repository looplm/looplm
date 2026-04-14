"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  getProjects,
  getSelectedProjectId,
  setSelectedProjectId,
  type Project,
} from "@/lib/api";
import ProjectSettings from "@/components/settings/project-settings";
import EvaluationsSettings from "@/components/settings/evaluations-settings";
import GeneralSettings from "@/components/settings/general-settings";
import MembersSettings from "@/components/settings/members-settings";
import IntegrationsPanel from "@/components/integrations-panel";
import { usePermissions } from "@/components/permissions-context";

const ALL_TABS = ["project", "members", "evaluations", "integrations", "ai-models"] as const;
type Tab = (typeof ALL_TABS)[number];

const TAB_LABELS: Partial<Record<Tab, string>> = { "ai-models": "AI Models" };

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { isAdmin } = usePermissions();
  const TABS = ALL_TABS.filter((t) => t !== "members" || isAdmin);

  const tabParam = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<Tab>(
    TABS.includes(tabParam as Tab) ? (tabParam as Tab) : "project"
  );

  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);

  function switchTab(tab: Tab) {
    setActiveTab(tab);
    router.replace(`/settings${tab === "project" ? "" : "?tab=" + tab}`, { scroll: false });
  }

  async function loadProjects() {
    try {
      const { data } = await getProjects();
      setProjects(data);
      const stored = getSelectedProjectId();
      const active = stored && data.some((p) => p.id === stored) ? stored : data[0]?.id;
      if (active) {
        setCurrentProjectId(active);
      }
    } catch {}
  }

  useEffect(() => {
    loadProjects();
  }, []);

  function handleProjectChange(id: string) {
    setCurrentProjectId(id);
    setSelectedProjectId(id);
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Settings</h1>

      {/* Tab bar */}
      <div className="flex gap-1 mb-8 border-b border-gray-200 dark:border-slate-800">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => switchTab(tab)}
            className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200"
            }`}
          >
            {TAB_LABELS[tab] ?? tab}
          </button>
        ))}
      </div>

      {activeTab === "project" && (
        <ProjectSettings
          currentProjectId={currentProjectId}
          onProjectChange={handleProjectChange}
          projects={projects}
          reloadProjects={loadProjects}
        />
      )}
      {activeTab === "evaluations" && (
        <EvaluationsSettings
          currentProjectId={currentProjectId}
          projects={projects}
          reloadProjects={loadProjects}
        />
      )}
      {activeTab === "members" && isAdmin && (
        <MembersSettings projectId={currentProjectId} />
      )}
      {activeTab === "integrations" && <IntegrationsPanel />}
      {activeTab === "ai-models" && (
        <GeneralSettings
          currentProjectId={currentProjectId}
          projects={projects}
        />
      )}
    </div>
  );
}
