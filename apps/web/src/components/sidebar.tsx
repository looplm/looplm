"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  logout,
  getProjects,
  createProject,
  getSelectedProjectId,
  setSelectedProjectId,
  type Project,
} from "@/lib/api";
import LoopLMIcon from "@/components/looplm-icon";
import { usePermissions } from "@/components/permissions-context";

type NavItem = { href: string; label: string; icon: string; page?: string };

const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "OBSERVE",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "\u{1F4CA}" },
      { href: "/traces", label: "Traces", icon: "\u{1F50D}" },
      { href: "/analytics", label: "Analytics", icon: "\u{1F4C8}" },
      { href: "/feedback", label: "Feedback", icon: "\u{1F4AC}" },
      { href: "/data-sources", label: "Data Sources", icon: "\u{1F5C2}️" },
      { href: "/costs", label: "Costs", icon: "\u{1F4B0}" },
    ],
  },
  {
    label: "EVALUATE",
    items: [
      { href: "/evaluations", label: "Evaluations", icon: "\u{1F9EA}" },
      { href: "/evaluators", label: "Evaluators", icon: "\u{1F4CF}" },
      { href: "/datasets", label: "Datasets", icon: "\u{1F4CB}" },
      { href: "/coverage", label: "Coverage", icon: "\u{1F4E1}" },
      { href: "/pipeline", label: "Pipeline", icon: "\u{1F9ED}" },
      { href: "/retrieval", label: "Retrieval", icon: "\u{1F3AF}", page: "pipeline" },
      { href: "/labeling", label: "Labeling", icon: "\u{1F3F7}️" },
    ],
  },
  {
    label: "IMPROVE",
    items: [
      { href: "/issues", label: "Issues", icon: "\u{1F6A8}" },
      { href: "/advisor", label: "Advisor", icon: "\u{1F9E0}" },
      { href: "/routes", label: "Routes", icon: "\u{1F5FA}\uFE0F" },
      { href: "/prompts", label: "Prompts", icon: "\u{1F4DD}" },
    ],
  },
];

export default function Sidebar({ onNavigate, collapsed, onToggleCollapse }: { onNavigate?: () => void; collapsed?: boolean; onToggleCollapse?: () => void }) {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { allowedSections, canAccessPage, isPlatformAdmin } = usePermissions();
  const [mounted, setMounted] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [showNewProject, setShowNewProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [creating, setCreating] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    getProjects()
      .then(({ data }) => {
        setProjects(data);
        const stored = getSelectedProjectId();
        if (stored && data.some((p) => p.id === stored)) {
          setCurrentProjectId(stored);
        } else if (data.length > 0) {
          setCurrentProjectId(data[0].id);
          setSelectedProjectId(data[0].id);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
        setShowNewProject(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const currentProject = projects.find((p) => p.id === currentProjectId);

  function switchProject(id: string) {
    setCurrentProjectId(id);
    setSelectedProjectId(id);
    setDropdownOpen(false);
    window.location.reload();
  }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return;
    setCreating(true);
    try {
      const project = await createProject({ name: newProjectName.trim() });
      setProjects((prev) => [...prev, project]);
      setNewProjectName("");
      setShowNewProject(false);
      switchProject(project.id);
    } catch {
      // ignore
    } finally {
      setCreating(false);
    }
  }

  return (
    <aside className="h-full flex flex-col p-4 overflow-y-auto">
      <div className={`flex ${collapsed ? "flex-col items-center gap-3" : "items-center justify-between"} mb-4 md:pt-4`}>
        <Link href="/" className={`text-xl font-bold tracking-tight flex items-center gap-2 ${collapsed ? "" : "px-3"}`} onClick={onNavigate}>
          <LoopLMIcon className="w-6 h-6 text-indigo-400 flex-shrink-0" />
          {!collapsed && <span><span className="text-indigo-400">Loop</span>LM</span>}
        </Link>
        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className="hidden md:flex items-center justify-center w-6 h-6 rounded text-gray-400 dark:text-slate-500 hover:text-gray-700 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <svg className={`w-4 h-4 transition-transform ${collapsed ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        )}
      </div>

      {/* Project switcher */}
      {projects.length > 0 && !collapsed && (
        <div className="relative mb-4 px-1" ref={dropdownRef}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-sm text-gray-700 dark:text-slate-200 hover:bg-gray-200 dark:hover:bg-slate-750 transition-colors"
          >
            <span className="truncate">{currentProject?.name || "Select project"}</span>
            <svg className={`w-4 h-4 ml-2 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {dropdownOpen && (
            <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg shadow-xl overflow-hidden">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => switchProject(p.id)}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                    p.id === currentProjectId
                      ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300"
                      : "text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700"
                  }`}
                >
                  {p.name}
                </button>
              ))}
              {isPlatformAdmin && (
              <div className="border-t border-gray-200 dark:border-slate-700">
                {showNewProject ? (
                  <div className="p-2 flex gap-1">
                    <input
                      type="text"
                      value={newProjectName}
                      onChange={(e) => setNewProjectName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleCreateProject()}
                      placeholder="Project name"
                      className="flex-1 px-2 py-1 bg-gray-50 dark:bg-slate-900 border border-gray-300 dark:border-slate-600 rounded text-sm text-gray-700 dark:text-slate-200 placeholder-gray-400 dark:placeholder-slate-500"
                      autoFocus
                    />
                    <button
                      onClick={handleCreateProject}
                      disabled={creating || !newProjectName.trim()}
                      className="px-2 py-1 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-500 disabled:opacity-50"
                    >
                      {creating ? "..." : "+"}
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setShowNewProject(true)}
                    className="w-full text-left px-3 py-2 text-sm text-indigo-600 dark:text-indigo-400 hover:bg-gray-100 dark:hover:bg-slate-700 transition-colors"
                  >
                    + New Project
                  </button>
                )}
              </div>
              )}
            </div>
          )}
        </div>
      )}

      <nav className="flex flex-col gap-1">
        {NAV_GROUPS.filter((g) => allowedSections.includes(g.label.toLowerCase())).map((group, groupIdx) => {
          const visibleItems = group.items.filter((item) =>
            canAccessPage(item.page ?? item.href.slice(1)),
          );
          if (visibleItems.length === 0) return null;
          return (
            <div key={group.label}>
              {groupIdx > 0 && (
                <div className={`my-2 border-t border-gray-200 dark:border-slate-800 ${collapsed ? "" : "mx-3"}`} />
              )}
              {!collapsed && (
                <div className="px-3 pt-2 pb-1 text-[10px] font-semibold tracking-widest text-gray-400 dark:text-slate-500 select-none">
                  {group.label}
                </div>
              )}
              {collapsed && groupIdx > 0 && null}
              {visibleItems.map((item) => {
                const active = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    className={`flex items-center ${collapsed ? "justify-center" : "gap-3"} px-3 py-2 rounded-lg text-sm font-medium transition-colors ${active
                        ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300"
                        : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800"
                      }`}
                  >
                    <span>{item.icon}</span>
                    {!collapsed && item.label}
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>
      <div className="mt-auto pt-4 border-t border-gray-200 dark:border-slate-800 flex flex-col gap-1">
        <Link
          href="/settings"
          onClick={onNavigate}
          title={collapsed ? "Settings" : undefined}
          className={`flex items-center ${collapsed ? "justify-center" : "gap-3"} px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
            pathname.startsWith("/settings")
              ? "bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-300"
              : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800"
          }`}
        >
          <span>{"\u2699\uFE0F"}</span>
          {!collapsed && "Settings"}
        </Link>
        {mounted && (
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : theme === "light" ? "system" : "dark")}
            title={collapsed ? (theme === "dark" ? "Light Mode" : theme === "light" ? "System Mode" : "Dark Mode") : undefined}
            className={`flex items-center ${collapsed ? "justify-center" : "gap-3"} px-3 py-2 rounded-lg text-sm font-medium text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors w-full`}
          >
            {theme === "dark" ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" strokeWidth="2"/><path strokeWidth="2" strokeLinecap="round" d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
            ) : theme === "light" ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
            )}
            {!collapsed && (theme === "dark" ? "Light Mode" : theme === "light" ? "System Mode" : "Dark Mode")}
          </button>
        )}
        <button
          onClick={logout}
          title={collapsed ? "Logout" : undefined}
          className={`flex items-center ${collapsed ? "justify-center" : "gap-3"} px-3 py-2 rounded-lg text-sm font-medium text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors w-full`}
        >
          <span>{"\u{1F6AA}"}</span>
          {!collapsed && "Logout"}
        </button>
      </div>
    </aside>
  );
}
