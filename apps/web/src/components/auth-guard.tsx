"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  isAuthenticated,
  getProjects,
  getSelectedProjectId,
  setSelectedProjectId,
} from "@/lib/api";
import NoProjectGate from "@/components/no-project-gate";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [hasProjects, setHasProjects] = useState(true);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }

    // Ensure a project is selected
    getProjects()
      .then(({ data }) => {
        setHasProjects(data.length > 0);
        if (data.length > 0) {
          const stored = getSelectedProjectId();
          if (!stored || !data.some((p) => p.id === stored)) {
            setSelectedProjectId(data[0].id);
          }
        }
        setChecked(true);
      })
      .catch(() => {
        // If projects fetch fails (e.g. token expired), auth middleware handles redirect
        setChecked(true);
      });
  }, [router]);

  if (checked && !hasProjects) {
    return <NoProjectGate />;
  }

  if (!checked) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-gray-500 dark:text-slate-400">Loading...</div>
      </div>
    );
  }

  return <>{children}</>;
}
