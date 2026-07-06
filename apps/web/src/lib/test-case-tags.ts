// Reserved tag marking a negative test case: the query intentionally has no relevant
// documents (e.g. a UI command), so retrieval ground truth is never attached to it and
// retrieval metrics exclude it. Mirrors NO_RETRIEVAL_TAG in apps/api/app/models/datasets.py.
export const NO_RETRIEVAL_TAG = "no-retrieval-expected";

export function isNoRetrievalExpected(tags: string[] | null | undefined): boolean {
  return !!tags && tags.includes(NO_RETRIEVAL_TAG);
}
