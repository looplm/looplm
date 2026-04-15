"""Backfill llm_usage_records from historical eval runs, feedback evals, prompt reviews, etc.

Revision ID: 031
Revises: 030
Create Date: 2026-03-26

Estimates platform LLM costs from historical records. Token counts are
approximations since exact usage was not recorded prior to cost tracking.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '031'
down_revision: Union[str, None] = '030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. OpenCodeAnalysis — direct cost data available
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            oca.project_id,
            'code_agent',
            'analyze_eval_run',
            'claude_agent_sdk',
            'claude-sonnet-4-20250514',
            0, 0, 0,
            oca.total_cost_usd,
            jsonb_build_object('backfilled', true, 'analysis_id', oca.id::text, 'num_turns', oca.num_turns),
            COALESCE(oca.completed_at, oca.created_at)
        FROM opencode_analyses oca
        WHERE oca.total_cost_usd IS NOT NULL
          AND oca.status = 'completed'
    """))

    # 2. EvalRun LLM judge calls — count non-skipped LLM judge grader entries per result
    #    Each grader entry in eval_results.graders that is not skipped = 1 LLM call.
    #    We group by run to get one record per run with estimated totals.
    #    Estimate ~1500 input tokens + ~200 output tokens per judge call (prompt + response).
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            er.project_id,
            'eval_runners',
            '_run_llm_judge',
            'openai',
            'gpt-4o-mini',
            (judge_calls * 1500),
            (judge_calls * 200),
            (judge_calls * 1700),
            (judge_calls * 1500 * 0.15 + judge_calls * 200 * 0.60) / 1000000.0,
            jsonb_build_object('backfilled', true, 'eval_run_id', er.id::text, 'judge_calls', judge_calls),
            er.created_at
        FROM eval_runs er
        JOIN LATERAL (
            SELECT COUNT(*) AS judge_calls
            FROM eval_results res,
                 jsonb_each(res.graders) AS g(key, val)
            WHERE res.run_id = er.id
              AND (val->>'skipped')::boolean IS NOT TRUE
              AND val->>'reason' IS NOT NULL
              AND val->>'reason' NOT LIKE 'Grading error%'
        ) counts ON true
        WHERE er.source != 'auto-grade'
          AND judge_calls > 0
    """))

    # 3. Auto-grade runs (from eval_grader background loop) — same estimation
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            er.project_id,
            'eval_grader',
            'grade_trace',
            'openai',
            'gpt-4o-mini',
            (er.total * 1500),
            (er.total * 200),
            (er.total * 1700),
            (er.total * 1500 * 0.15 + er.total * 200 * 0.60) / 1000000.0,
            jsonb_build_object('backfilled', true, 'eval_run_id', er.id::text),
            er.created_at
        FROM eval_runs er
        WHERE er.source = 'auto-grade'
          AND er.total > 0
    """))

    # 4. FeedbackEvaluation — batch_size=5, so ceil(evaluated_count/5) LLM calls
    #    Estimate ~2000 input tokens + ~300 output tokens per batch call.
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            fe.project_id,
            'feedback_eval_worker',
            'run_feedback_evaluation',
            'openai',
            'gpt-4o-mini',
            (batch_count * 2000),
            (batch_count * 300),
            (batch_count * 2300),
            (batch_count * 2000 * 0.15 + batch_count * 300 * 0.60) / 1000000.0,
            jsonb_build_object('backfilled', true, 'evaluation_id', fe.id::text, 'evaluated_count', fe.evaluated_count),
            COALESCE(fe.completed_at, fe.started_at, now())
        FROM feedback_evaluations fe
        JOIN LATERAL (
            SELECT GREATEST(CEIL(fe.evaluated_count::numeric / 5), 0)::int AS batch_count
        ) bc ON true
        WHERE fe.status = 'completed'
          AND fe.evaluated_count > 0
    """))

    # 5. PromptReview — 1 LLM call per review
    #    Estimate ~1000 input tokens + ~500 output tokens.
    #    Need project_id via prompts → integrations → projects.
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            i.project_id,
            'prompt_analysis',
            'review_prompt',
            'openai',
            CASE WHEN pr.model != '' THEN pr.model ELSE 'gpt-4o-mini' END,
            1000, 500, 1500,
            (1000 * 0.15 + 500 * 0.60) / 1000000.0,
            jsonb_build_object('backfilled', true, 'prompt_review_id', pr.id::text),
            pr.reviewed_at
        FROM prompt_reviews pr
        JOIN prompts p ON pr.prompt_id = p.id
        JOIN integrations i ON p.integration_id = i.id
    """))

    # 6. AdvisorAnalysis — 1 LLM call per analysis
    #    Estimate ~3000 input tokens + ~800 output tokens (larger prompts with graph data).
    conn.execute(sa.text("""
        INSERT INTO llm_usage_records (
            id, project_id, service_name, function_name, provider, model,
            input_tokens, output_tokens, total_tokens, cost_usd,
            request_metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            i.project_id,
            'architecture_advisor',
            'analyze_architecture',
            'openai',
            'gpt-4o-mini',
            3000, 800, 3800,
            (3000 * 0.15 + 800 * 0.60) / 1000000.0,
            jsonb_build_object('backfilled', true, 'advisor_analysis_id', aa.id::text),
            aa.analyzed_at
        FROM advisor_analyses aa
        JOIN integrations i ON aa.integration_id = i.id
    """))


def downgrade() -> None:
    # Remove all backfilled records
    op.execute("DELETE FROM llm_usage_records WHERE request_metadata->>'backfilled' = 'true'")
