"use client";

import { Suspense, useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "./sidebar";
import { GlobalFiltersProvider } from "./global-filters-context";
import GlobalFilterHeader from "./global-filter-header";
import { PermissionsProvider, usePermissions } from "./permissions-context";

const FILTER_PATHS = new Set(["/dashboard", "/traces", "/analytics", "/feedback", "/costs"]);

const SECTION_ROUTES: Record<string, string[]> = {
  observe: ["/dashboard", "/traces", "/analytics", "/feedback", "/costs"],
  evaluate: ["/evaluations", "/evaluators", "/datasets"],
  improve: ["/issues", "/advisor", "/routes", "/prompts"],
};

const ROUTE_TO_PAGE: Record<string, string> = {
  "/dashboard": "dashboard",
  "/traces": "traces",
  "/analytics": "analytics",
  "/feedback": "feedback",
  "/costs": "costs",
  "/evaluations": "evaluations",
  "/evaluators": "evaluators",
  "/datasets": "datasets",
  "/issues": "issues",
  "/advisor": "advisor",
  "/routes": "routes",
  "/prompts": "prompts",
};

function findFirstAccessibleRoute(
  allowedSections: string[],
  canAccessPage: (page: string) => boolean,
): string | null {
  for (const s of ["observe", "evaluate", "improve"]) {
    if (!allowedSections.includes(s)) continue;
    for (const route of SECTION_ROUTES[s]) {
      const page = ROUTE_TO_PAGE[route];
      if (!page || canAccessPage(page)) return route;
    }
  }
  return null;
}

function SectionGuard({ children }: { children: React.ReactNode }) {
  const { allowedSections, canAccessPage, loading } = usePermissions();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    // Check section access
    for (const [section, routes] of Object.entries(SECTION_ROUTES)) {
      if (routes.some((r) => pathname.startsWith(r)) && !allowedSections.includes(section)) {
        router.replace(findFirstAccessibleRoute(allowedSections, canAccessPage) || "/settings");
        return;
      }
    }

    // Check page access
    for (const [route, page] of Object.entries(ROUTE_TO_PAGE)) {
      if (pathname.startsWith(route) && !canAccessPage(page)) {
        router.replace(findFirstAccessibleRoute(allowedSections, canAccessPage) || "/settings");
        return;
      }
    }
  }, [pathname, allowedSections, canAccessPage, loading, router]);

  return <>{children}</>;
}

const SIDEBAR_COLLAPSED_KEY = "looplm-sidebar-collapsed";

export default function NavigationWrapper({ children }: { children: React.ReactNode }) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "true") setIsCollapsed(true);
    setMounted(true);
  }, []);

  function toggleCollapsed() {
    setIsCollapsed((prev) => {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(!prev));
      return !prev;
    });
  }

  const pathname = usePathname();
  const showFilters = FILTER_PATHS.has(pathname);

  return (
    <PermissionsProvider>
      <div className="flex min-h-screen bg-gray-50 dark:bg-slate-950 text-gray-900 dark:text-white flex-col md:flex-row">
        {/* Mobile Header */}
        <div className="md:hidden flex items-center justify-between p-4 border-b border-gray-100 dark:border-slate-800 bg-white dark:bg-slate-900 sticky top-0 z-30">
          <span className="text-xl font-bold tracking-tight">
            <span className="text-indigo-600 dark:text-indigo-400">Loop</span>LM
          </span>
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="p-2 text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
          >
            {isSidebarOpen ? "✕" : "☰"}
          </button>
        </div>

        {/* Sidebar Container */}
        <div
          className={`
            fixed inset-y-0 left-0 z-50 bg-white dark:bg-slate-900 border-r border-gray-100 dark:border-slate-800 transform transition-all duration-300 ease-in-out
            md:sticky md:top-0 md:h-screen md:translate-x-0 md:flex md:flex-col
            ${mounted && isCollapsed ? "md:w-16" : "md:w-64"}
            ${isSidebarOpen ? "translate-x-0 w-64" : "-translate-x-full"}
          `}
        >
          <Sidebar onNavigate={() => setIsSidebarOpen(false)} collapsed={mounted && isCollapsed} onToggleCollapse={toggleCollapsed} />
        </div>

        {/* Backdrop for mobile */}
        {isSidebarOpen && (
          <div
            className="fixed inset-0 z-40 bg-black/30 dark:bg-black/50 backdrop-blur-sm md:hidden"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}

        {/* Main Content */}
        <main className="flex-1 p-4 md:p-8 overflow-auto w-full">
          <Suspense>
            <SectionGuard>
              <GlobalFiltersProvider>
                {showFilters && <GlobalFilterHeader />}
                {children}
              </GlobalFiltersProvider>
            </SectionGuard>
          </Suspense>
        </main>
      </div>
    </PermissionsProvider>
  );
}
