"""Backfill evaluator configs from legacy grader defaults.

Sets config for known evaluators where config is empty ({}) or NULL.
Does NOT overwrite user-customized configs.

Revision ID: 023
Revises: 022
"""

import json

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

_JSON_ONLY_RESPONSE = (
    'Respond only as JSON: {"pass": true/false, "reason": "short explanation"}'
)

# Same configs as known_evaluators in evaluator_helpers.py sync endpoint
KNOWN_CONFIGS: dict[str, dict] = {
    "sourceRetrieval": {"check_type": "contains_urls"},
    "factualCorrectness": {
        "prompt_template": (
            "You are evaluating factual consistency.\n\n"
            "Determine whether the answer contains claims that directly contradict the "
            "retrieved context.\n\n"
            "Retrieved context:\n{context}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "faithfulness": {
        "prompt_template": (
            "You are evaluating whether an answer is grounded in the retrieved context.\n\n"
            "Determine whether the answer introduces unsupported factual claims.\n\n"
            "Retrieved context:\n{context}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "faithfulnessToSource": {
        "check_type": "regex_match",
        "pattern": r"(?i)(exact|verbatim|quote|from the source|original text|word-for-word|1:1|citation)",
        "prompt_template": (
            "You are evaluating source fidelity.\n\n"
            "The user requested exact or source-faithful information. Determine whether "
            "the answer stays faithful to the provided source content.\n\n"
            "User request:\n{input}\n\nSource content:\n{context}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "answerRelevance": {
        "prompt_template": (
            "You are evaluating answer relevance.\n\n"
            "Determine whether the answer addresses the user's request while taking the "
            "available context into account.\n\n"
            "User request:\n{input}\n\nAvailable context:\n{context}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "helpfulness": {
        "prompt_template": (
            "You are evaluating helpfulness.\n\n"
            "Determine whether the answer is clear, well-structured, and useful given "
            "the available context.\n\n"
            "User request:\n{input}\n\nAvailable context:\n{context}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "conciseness": {
        "check_type": "string_contains",
        "expected_strings": [],
        "prompt_template": (
            "You are evaluating conciseness.\n\n"
            "Determine whether the answer contains unnecessary repetition, filler, or "
            "excessive verbosity.\n\n"
            "User request:\n{input}\n\nAnswer:\n{output}\n\n"
            f"{_JSON_ONLY_RESPONSE}"
        ),
    },
    "imageMissing": {"check_type": "image_missing"},
    "imageOrdering": {"check_type": "image_ordering"},
}


def upgrade() -> None:
    for name, config in KNOWN_CONFIGS.items():
        config_json = json.dumps(config).replace("'", "''")
        op.execute(
            f"""
            UPDATE evaluators
            SET config = '{config_json}'::jsonb,
                updated_at = now()
            WHERE name = '{name}'
              AND (config IS NULL OR config = '{{}}'::jsonb)
            """
        )


def downgrade() -> None:
    # Don't wipe configs on downgrade — they may have been further customized
    pass
