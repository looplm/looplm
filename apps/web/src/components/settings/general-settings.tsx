"use client";

import { useEffect, useState } from "react";
import { getGithubStatus, type GithubStatus, type Project } from "@/lib/api";
import EvaluatorLlm from "./evaluator-llm";
import GithubAppConfigSection from "./github-app-config";
import GithubRepoSettings from "./github-repo-settings";
import CodeAgentSettings from "./code-agent-settings";

interface GeneralSettingsProps {
  currentProjectId: string | null;
  projects: Project[];
}

export default function GeneralSettings({ currentProjectId, projects }: GeneralSettingsProps) {
  // githubStatus is per-project and shared by both GitHub sections: the App
  // config section refreshes it after save/delete, and the repo section reads it.
  const [githubStatus, setGithubStatus] = useState<GithubStatus | null>(null);

  const currentProject = projects.find((p) => p.id === currentProjectId);

  // GitHub status is per-project, so it re-fetches whenever the active project changes.
  useEffect(() => {
    if (!currentProjectId) {
      setGithubStatus(null);
      return;
    }
    getGithubStatus()
      .then(setGithubStatus)
      .catch(() => setGithubStatus({ enabled: false, app_name: null, install_url: null }));
  }, [currentProjectId]);

  return (
    <div className="space-y-6 max-w-2xl">
      <EvaluatorLlm currentProjectId={currentProjectId} projects={projects} />
      <GithubAppConfigSection
        currentProjectId={currentProjectId}
        setGithubStatus={setGithubStatus}
      />
      <GithubRepoSettings
        currentProjectId={currentProjectId}
        currentProject={currentProject}
        githubStatus={githubStatus}
      />
      <CodeAgentSettings currentProjectId={currentProjectId} projects={projects} />
    </div>
  );
}
