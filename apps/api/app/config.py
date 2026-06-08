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

    # Eval runner
    eval_target_endpoint: str = ""
    eval_default_concurrency: int = 2

    # Sync — max traces fetched per sync run (bounds the time-window pagination)
    sync_max_traces: int = 5000
    # Sync — overall timeout (seconds) for one background sync run
    sync_timeout_seconds: int = 1800

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
