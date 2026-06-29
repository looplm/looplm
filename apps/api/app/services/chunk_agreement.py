"""Gold resolution and inter-annotator agreement for chunk relevance labels.

With multiple annotators judging the same chunks, two things are needed:

* **Gold resolution** — collapse each chunk's per-annotator votes into one verdict the
  retrieval metrics score against. An adjudicated override wins; otherwise it's a majority
  vote, with ties left unresolved (the chunk stays *unjudged* until someone adjudicates).
* **Agreement** — Cohen's kappa over the chunks two annotators both judged, to document how
  consistently the relevance criteria are applied and surface disagreements for adjudication.

All functions here are pure (no DB): the router assembles the label rows and overrides and
passes them in, which keeps the statistics unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterable

from app.models.chunk_labels import RELEVANT_GRADE
from app.schemas.retrieval import (
    AgreementReport,
    AnnotatorAgreement,
    Disagreement,
    PairwiseKappa,
    VoteEntry,
)

Item = tuple[str, str]  # (test_id, chunk_id)


def _is_relevant(grade: int) -> bool:
    """Binarize a graded relevance for the set-based metrics and kappa (grade >= 1)."""
    return grade >= RELEVANT_GRADE


def resolve_gold(
    rows: Iterable[tuple[str, str, int, Hashable]],
    overrides: dict[Item, int] | None = None,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, int]]]:
    """Collapse per-annotator graded votes into gold sets + a gold grade per chunk, per test_id.

    ``rows`` are ``(test_id, chunk_id, relevance, annotator)`` tuples — ``relevance`` is the
    graded 0..3 judgment (annotator may be ``None`` for unattributed labels, which collapse to a
    single vote). ``overrides`` maps an adjudicated ``(test_id, chunk_id)`` to its gold grade,
    which wins over the votes.

    Returns ``(relevant_by_test, nonrelevant_by_test, grade_by_test)``:
    * ``relevant_by_test`` — chunk ids whose gold grade is relevant (>= 1).
    * ``nonrelevant_by_test`` — chunk ids judged irrelevant (gold grade 0).
    * ``grade_by_test`` — ``test_id -> {chunk_id: gold grade}`` for the relevant chunks, the
      graded gains nDCG scores against.

    Without an override the gold grade is the rounded mean of the votes; relevant when the
    *binarized* majority is relevant, irrelevant when it's not, and **unjudged** (in neither
    set) on an exact relevant/irrelevant tie — so a contested chunk isn't silently scored.
    """
    overrides = overrides or {}
    votes: dict[Item, dict[Hashable, int]] = {}
    for test_id, chunk_id, relevance, annotator in rows:
        votes.setdefault((test_id, chunk_id), {})[annotator] = relevance

    relevant_by_test: dict[str, set[str]] = {}
    nonrelevant_by_test: dict[str, set[str]] = {}
    grade_by_test: dict[str, dict[str, int]] = {}
    for (test_id, chunk_id), ann_votes in votes.items():
        override = overrides.get((test_id, chunk_id))
        if override is not None:
            grade: int | None = override
        else:
            vals = list(ann_votes.values())
            rel = sum(1 for v in vals if _is_relevant(v))
            non = len(vals) - rel
            if rel == non:
                grade = None  # contested tie → leave unjudged
            elif rel > non:
                grade = max(RELEVANT_GRADE, round(sum(vals) / len(vals)))
            else:
                grade = 0
        if grade is None:
            continue
        if _is_relevant(grade):
            relevant_by_test.setdefault(test_id, set()).add(chunk_id)
            grade_by_test.setdefault(test_id, {})[chunk_id] = grade
        else:
            nonrelevant_by_test.setdefault(test_id, set()).add(chunk_id)
    return relevant_by_test, nonrelevant_by_test, grade_by_test


def cohen_kappa(a: dict[Any, bool], b: dict[Any, bool]) -> tuple[float | None, int]:
    """Cohen's kappa between two annotators over the items both judged (binary labels).

    Returns ``(kappa, n_overlap)``. ``kappa`` is ``None`` when there is no overlap. When both
    annotators put every shared item in one class (so chance agreement ``pe`` = 1) kappa is
    undefined; by convention it returns 1.0 on full agreement, else 0.0.
    """
    items = a.keys() & b.keys()
    n = len(items)
    if n == 0:
        return None, 0
    agree = sum(1 for i in items if a[i] == b[i])
    po = agree / n
    a_pos = sum(1 for i in items if a[i]) / n
    b_pos = sum(1 for i in items if b[i]) / n
    pe = a_pos * b_pos + (1 - a_pos) * (1 - b_pos)
    if pe >= 1.0:
        return (1.0 if po >= 1.0 else 0.0), n
    return (po - pe) / (1 - pe), n


@dataclass
class Vote:
    """One annotator's graded judgment of one chunk, with display info for the report."""

    test_id: str
    chunk_id: str
    relevance: int
    annotator_id: Hashable
    annotator_name: str
    title: str | None = None


def build_agreement_report(
    votes: Iterable[Vote], overrides: dict[Item, int] | None = None
) -> AgreementReport:
    """Cohen's kappa + disagreements over the chunks judged by more than one annotator.

    Votes with no annotator identity are skipped (agreement needs to know who judged what).
    Kappa is computed over the *binarized* (relevant / not, grade >= 1) judgments, since it's a
    nominal-agreement statistic; the disagreement list, however, flags any chunk whose raw
    grades differ, with the current gold grade (if adjudicated), so an expert can settle both
    relevant/not conflicts and grade-value differences.
    """
    overrides = overrides or {}
    ann_maps: dict[Hashable, dict[Item, bool]] = {}
    ann_name: dict[Hashable, str] = {}
    item_votes: dict[Item, dict[Hashable, int]] = {}
    title_by_item: dict[Item, str] = {}

    for v in votes:
        if v.annotator_id is None:
            continue
        item = (v.test_id, v.chunk_id)
        ann_maps.setdefault(v.annotator_id, {})[item] = _is_relevant(v.relevance)
        ann_name[v.annotator_id] = v.annotator_name
        item_votes.setdefault(item, {})[v.annotator_id] = v.relevance
        if v.title:
            title_by_item[item] = v.title

    judged_items = len(item_votes)
    overlap = [it for it, vs in item_votes.items() if len(vs) >= 2]

    ids = sorted(ann_maps, key=lambda a: ann_name[a])
    pairwise: list[PairwiseKappa] = []
    kappas: list[float] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            k, n = cohen_kappa(ann_maps[ids[i]], ann_maps[ids[j]])
            if k is not None and n > 0:
                pairwise.append(
                    PairwiseKappa(a=ann_name[ids[i]], b=ann_name[ids[j]], kappa=round(k, 3), n=n)
                )
                kappas.append(k)

    disagreements: list[Disagreement] = []
    for item in overlap:
        vs = item_votes[item]
        if len(set(vs.values())) > 1:
            disagreements.append(
                Disagreement(
                    test_id=item[0],
                    chunk_id=item[1],
                    title=title_by_item.get(item),
                    votes=[
                        VoteEntry(labeler=ann_name[a], relevance=r) for a, r in vs.items()
                    ],
                    gold=overrides.get(item),
                )
            )

    return AgreementReport(
        available=bool(pairwise),
        annotators=sorted(
            (AnnotatorAgreement(name=ann_name[a], judged_count=len(m)) for a, m in ann_maps.items()),
            key=lambda a: a.name,
        ),
        judged_items=judged_items,
        overlap_count=len(overlap),
        double_judged_pct=round(len(overlap) / judged_items, 3) if judged_items else 0.0,
        pairwise=pairwise,
        average_kappa=round(sum(kappas) / len(kappas), 3) if kappas else None,
        disagreements=disagreements,
    )
