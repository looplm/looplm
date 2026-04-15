"""Add IMAGE placeholder exception to faithfulness grader prompts.

The LLM judge was treating IMAGE_XX references (e.g. IMAGE_10) as hallucinated
content even when they appear in the source context. This adds an explicit
exception so image placeholders from the context are not flagged.

Works on both old prompts (from migration 023) and newer synced prompts.

Revision ID: 035
Revises: 034
Create Date: 2026-03-31
"""

from alembic import op

revision: str = "035"
down_revision: str = "034"
branch_labels = None
depends_on = None

IMAGE_EXCEPTION = (
    "NICHT als Verstoß werten:\\n"
    "- Bild-Platzhalter wie IMAGE_1, IMAGE_10 etc. die im Kontext als "
    "Markdown-Bilder (z.B. ![...](IMAGE_10)) vorkommen. "
    "Diese Referenzen sind Teil des Quelltextes und keine erfundenen Informationen.\\n\\n"
)

# These anchors exist in both old (migration 023) and newer (synced) prompt versions
ANCHORS = {
    "faithfulness": "Abgerufener Kontext:\\n{context}",
    "faithfulnessToSource": "Benutzeranfrage: {input}",
}


def upgrade() -> None:
    for name, anchor in ANCHORS.items():
        op.execute(
            f"""
            UPDATE evaluators
            SET config = jsonb_set(
                config,
                '{{prompt_template}}',
                to_jsonb(
                    replace(
                        config->>'prompt_template',
                        '{anchor}',
                        '{IMAGE_EXCEPTION}{anchor}'
                    )
                )
            ),
            updated_at = now()
            WHERE name = '{name}'
              AND config->>'prompt_template' IS NOT NULL
              AND config->>'prompt_template' LIKE '%{anchor}%'
              AND config->>'prompt_template' NOT LIKE '%Bild-Platzhalter%'
            """
        )


def downgrade() -> None:
    for name, anchor in ANCHORS.items():
        op.execute(
            f"""
            UPDATE evaluators
            SET config = jsonb_set(
                config,
                '{{prompt_template}}',
                to_jsonb(
                    replace(
                        config->>'prompt_template',
                        '{IMAGE_EXCEPTION}{anchor}',
                        '{anchor}'
                    )
                )
            ),
            updated_at = now()
            WHERE name = '{name}'
              AND config->>'prompt_template' LIKE '%Bild-Platzhalter%'
            """
        )
