-- LoopLM Database Schema
-- PostgreSQL 15+

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- INTEGRATIONS
-- ============================================================
CREATE TYPE integration_type AS ENUM ('langfuse', 'langsmith');
CREATE TYPE sync_status AS ENUM ('idle', 'syncing', 'error', 'never');

CREATE TABLE integrations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            integration_type NOT NULL,
    name            VARCHAR(255) NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}',
    api_key         BYTEA NOT NULL,                -- encrypted at application layer
    base_url        VARCHAR(2048),
    sync_status     sync_status NOT NULL DEFAULT 'never',
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TRACES
-- ============================================================
CREATE TYPE trace_status AS ENUM ('success', 'failure', 'degraded');

CREATE TABLE traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id  UUID NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    external_id     VARCHAR(512) NOT NULL,
    name            VARCHAR(512),
    input           JSONB,
    output          JSONB,
    metadata        JSONB NOT NULL DEFAULT '{}',
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    duration_ms     INTEGER,
    status          trace_status,
    error_message   TEXT,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (integration_id, external_id)
);

CREATE INDEX idx_traces_integration_id ON traces(integration_id);
CREATE INDEX idx_traces_status ON traces(status);
CREATE INDEX idx_traces_start_time ON traces(start_time DESC);
CREATE INDEX idx_traces_integration_status ON traces(integration_id, status);
CREATE INDEX idx_traces_integration_start_time ON traces(integration_id, start_time DESC);
CREATE INDEX idx_traces_created_at ON traces(created_at DESC);

-- ============================================================
-- SPANS
-- ============================================================
CREATE TYPE span_type AS ENUM ('llm', 'tool', 'retriever', 'chain', 'agent');

CREATE TABLE spans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    parent_span_id  UUID REFERENCES spans(id) ON DELETE SET NULL,
    external_id     VARCHAR(512),
    name            VARCHAR(512),
    type            span_type,
    input           JSONB,
    output          JSONB,
    model           VARCHAR(255),
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    duration_ms     INTEGER,
    status          VARCHAR(64),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_spans_trace_id ON spans(trace_id);
CREATE INDEX idx_spans_type ON spans(type);
CREATE INDEX idx_spans_parent_span_id ON spans(parent_span_id);

-- ============================================================
-- ANALYSES
-- ============================================================
CREATE TABLE analyses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        UUID NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    failure_type    VARCHAR(128),
    root_cause      TEXT,
    confidence      FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    suggested_fixes JSONB NOT NULL DEFAULT '[]',
    applied         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_analyses_trace_id ON analyses(trace_id);

-- ============================================================
-- FIX SUGGESTIONS
-- ============================================================
CREATE TYPE fix_type AS ENUM ('prompt_rewrite', 'tool_config', 'knowledge_gap', 'parameter_change');
CREATE TYPE fix_status AS ENUM ('pending', 'applied', 'dismissed');

CREATE TABLE fix_suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id     UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    type            fix_type NOT NULL,
    title           VARCHAR(512) NOT NULL,
    description     TEXT,
    diff            JSONB,
    status          fix_status NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_fix_suggestions_analysis_id ON fix_suggestions(analysis_id);
CREATE INDEX idx_fix_suggestions_status ON fix_suggestions(status);
