export const ALL_SECTIONS = ["observe", "evaluate", "improve"] as const;

export const SECTION_PAGES: Record<string, string[]> = {
  observe: ["dashboard", "traces", "analytics", "feedback", "costs", "data-sources"],
  evaluate: ["evaluations", "evaluators", "datasets", "coverage", "pipeline", "labeling"],
  improve: ["issues", "advisor", "routes", "prompts"],
};

export const ALL_PAGES = Object.values(SECTION_PAGES).flat();

export function pagesForSections(sections: string[]): string[] {
  return sections.flatMap((s) => SECTION_PAGES[s] || []);
}
