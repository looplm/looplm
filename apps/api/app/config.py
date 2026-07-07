from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopLM API"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://looplm:looplm@localhost:5432/looplm"
    redis_url: str = "redis://localhost:6379/0"
    api_secret_key: str = "change-me-in-production"
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3100"

    # Analysis LLM
    analysis_llm_provider: Literal["openai", "azure_openai"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str = ""

    # Query embeddings (for vector/hybrid retrieval probing) — reuse the analysis-LLM creds
    # above, with a dedicated embedding deployment/model. Must match the model that built the
    # index's vector field, or ANN results are meaningless. Empty deployment => embedding off.
    azure_openai_embedding_deployment: str = ""
    openai_embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072

    # Eval runner
    eval_target_endpoint: str = ""
    eval_default_concurrency: int = 2
    # Hard ceiling on parallel test runners, enforced server-side (clamps every
    # trigger/rerun path, including stored job configs that bypass schema validation).
    # The target's RAG pipeline embeds each expanded query against a shared Azure
    # OpenAI embeddings deployment; too many concurrent runners throttle it (429),
    # so the target silently falls back to keyword-only retrieval (no vector/rerank)
    # and eval grades a degraded path that is NOT representative of prod. Keep this
    # low enough to stay under the throttle knee. Confirm via the target's
    # `retrievalDiagnostics.retrievalMode` in the eval response: it must stay
    # `hybrid`/`mixed`, never `keyword-fallback`. Raise only alongside more
    # embeddings capacity (or a dedicated eval deployment).
    eval_max_concurrency: int = 3
    # Process-wide ceiling on concurrent target calls across ALL eval jobs/sessions.
    # eval_max_concurrency caps a single run; this caps the sum, so several evals
    # running in parallel can't stack their per-run concurrency into the target
    # embeddings throttle. Enforced via a shared semaphore in model_resilience.
    eval_global_max_concurrency: int = 3
    # Outbound retry policy for transient target/model failures — real 429/5xx/timeout
    # AND a detected `keyword-fallback` degrade (which arrives as HTTP 200, so it is only
    # retryable because we raise on it). max_retries counts attempts AFTER the first try;
    # delay is base * 2**(attempt-1) plus uniform jitter, so retries spread out rather
    # than synchronising into a fresh burst against the same throttled deployment.
    eval_target_max_retries: int = 3
    eval_backoff_base_seconds: float = 1.0
    eval_backoff_jitter_seconds: float = 0.5
    # Ceiling on the exponential term so a raised retry count can't produce
    # minutes-long sleeps (delay = min(base * 2**(attempt-1), max) + jitter).
    eval_backoff_max_seconds: float = 30.0
    # Explicit retry budget for LoopLM's own OpenAI/Azure SDK clients (judges,
    # query embeddings). The SDK retries 429/5xx/timeout internally with backoff;
    # set this instead of relying on the invisible default (2) so grading and
    # embedding calls survive transient throttling deterministically.
    model_max_retries: int = 3

    # AI judge (chunk relevance grader) — chunks go out in FULL, never truncated. To stay under
    # the model's context window the judge splits the pool into token-budgeted batches (mirroring
    # the retrieval app's ChunkRelevanceJudge) and merges the per-batch grades.
    ai_judge_context_tokens: int = 128000          # judge model's usable context window
    ai_judge_response_reserve_tokens: int = 2048   # held back for the model's JSON reply
    ai_judge_chars_per_token: float = 4.0          # conservative token estimate (under-fills)
    ai_judge_max_batch_chunks: int = 40            # cap chunks per call (guards grading quality)

    # Sync — max traces fetched per sync run (bounds the time-window pagination)
    sync_max_traces: int = 5000
    # Sync — overall timeout (seconds) for one background sync run
    sync_timeout_seconds: int = 1800
    # Sync — commit every N persisted traces (one fsync per batch, not per trace)
    sync_commit_batch_size: int = 200

    # First-party tracing ingest (push-based SDK → /api/v1/ingest)
    ingest_enabled: bool = True
    ingest_max_batch: int = 100          # max traces accepted per ingest request
    ingest_max_spans_per_trace: int = 1000

    # Auto-grading
    auto_grade_enabled: bool = False
    auto_grade_interval_minutes: int = 5
    auto_grade_batch_size: int = 20
    auto_grade_min_output_length: int = 50

    # Behavioral signal classification (LLM-labels traces with refusal/frustration/etc.)
    signal_classify_enabled: bool = False     # off by default — it spends LLM tokens
    signal_classify_interval_minutes: int = 10
    signal_classify_batch_size: int = 20      # max LLM classifications per tick
    signal_classify_scan_limit: int = 400     # candidate traces scanned per tick
    signal_classify_sample_pct: int = 20      # % of non-failure traces to classify

    # Autonomous issue detection (clusters signals into issues on a schedule)
    issue_detection_enabled: bool = False     # off by default
    issue_detection_interval_minutes: int = 30
    issue_detection_window_days: int = 7

    # SMTP (optional — used for sending invitation emails)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Frontend URL for building invite links
    frontend_url: str = "http://localhost:3100"

    # Update check (GitHub releases lookup for the About settings panel)
    update_check_enabled: bool = True
    github_token: str = ""

    # Platform admin: email whose account is treated as platform admin even
    # when its user row hasn't been promoted yet. Useful for first-time setups
    # and recovery. Leave blank to rely solely on the User.is_platform_admin flag.
    instance_owner_email: str = ""

    # GitHub App — used by the Code Agent to clone connected repos.
    # All optional; the feature is disabled when app_id is unset.
    github_app_id: str = ""
    github_app_name: str = ""              # slug used to build install URLs: github.com/apps/<slug>
    github_app_client_id: str = ""
    github_app_client_secret: str = ""
    github_app_private_key: str = ""       # PEM contents (use \n escapes in .env)
    github_app_private_key_path: str = ""  # alternative: path to a mounted PEM file
    github_clone_dir: str = "/var/looplm/repos"
    github_api_base_url: str = "https://api.github.com"
    github_oauth_base_url: str = "https://github.com"

    # Connector credentials
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    langsmith_api_key: str = ""
    langchain_endpoint: str = "https://api.smith.langchain.com"
    langchain_project: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
