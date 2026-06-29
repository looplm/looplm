// Graded relevance scale (TREC-style): 0 irrelevant … 3 highly relevant. Any grade >= 1
// counts as relevant for the set-based metrics; nDCG uses the grade as gain.
export const GRADES: { value: number; label: string; selected: string; hover: string }[] = [
  { value: 0, label: "Irrelevant", selected: "bg-red-500 border-red-500 text-white", hover: "hover:border-red-400" },
  { value: 1, label: "Marginally relevant", selected: "bg-amber-500 border-amber-500 text-white", hover: "hover:border-amber-400" },
  { value: 2, label: "Relevant", selected: "bg-emerald-500 border-emerald-500 text-white", hover: "hover:border-emerald-400" },
  { value: 3, label: "Highly relevant", selected: "bg-emerald-600 border-emerald-600 text-white", hover: "hover:border-emerald-500" },
];

export function gradeLabel(grade: number): string {
  return GRADES.find((g) => g.value === grade)?.label ?? String(grade);
}

// Row background tint by grade: irrelevant red, any-relevant emerald, unjudged none.
export function gradeTint(grade: number | null | undefined): string {
  if (grade == null) return "";
  return grade >= 1 ? "bg-emerald-500/5" : "bg-red-500/5";
}
