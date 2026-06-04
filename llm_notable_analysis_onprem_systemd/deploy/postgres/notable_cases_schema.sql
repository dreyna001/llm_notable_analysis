CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS notable_cases;

CREATE TABLE IF NOT EXISTS notable_cases.cases (
    case_id text PRIMARY KEY,
    finding_id text,
    source_filename text NOT NULL,
    processed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    correlation_id text,
    capability_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    archive_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,

    alert_payload jsonb,
    analysis jsonb,
    case_schema_version integer NOT NULL,
    analysis_schema_version integer NOT NULL,

    verdict text,
    confidence numeric,
    search_name text,
    risk_score numeric,

    report_md_path text,
    report_html_path text,

    retrieval_status text NOT NULL DEFAULT 'pending',
    backfill_status text NOT NULL DEFAULT 'native',
    source_completeness text NOT NULL DEFAULT 'complete',

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT cases_retrieval_status_check
        CHECK (retrieval_status IN ('pending', 'ready', 'failed', 'not_indexed')),
    CONSTRAINT cases_backfill_status_check
        CHECK (backfill_status IN ('native', 'backfilled', 'legacy_summary')),
    CONSTRAINT cases_source_completeness_check
        CHECK (source_completeness IN ('complete', 'missing_alert', 'missing_analysis', 'markdown_only'))
);

CREATE INDEX IF NOT EXISTS cases_processed_at_idx
    ON notable_cases.cases (processed_at DESC);

CREATE INDEX IF NOT EXISTS cases_processed_at_case_id_idx
    ON notable_cases.cases (processed_at DESC, case_id ASC);

CREATE INDEX IF NOT EXISTS cases_expires_at_idx
    ON notable_cases.cases (expires_at);

CREATE INDEX IF NOT EXISTS cases_verdict_idx
    ON notable_cases.cases (verdict);

CREATE INDEX IF NOT EXISTS cases_search_name_idx
    ON notable_cases.cases (search_name);

CREATE OR REPLACE FUNCTION notable_cases.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cases_set_updated_at ON notable_cases.cases;
CREATE TRIGGER cases_set_updated_at
BEFORE UPDATE ON notable_cases.cases
FOR EACH ROW EXECUTE FUNCTION notable_cases.set_updated_at();

CREATE TABLE IF NOT EXISTS notable_cases.case_chunks (
    chunk_id text PRIMARY KEY,
    case_id text NOT NULL REFERENCES notable_cases.cases(case_id) ON DELETE CASCADE,
    source_lane text NOT NULL,
    section text NOT NULL,
    field_path text NOT NULL,
    text text NOT NULL,
    embedding vector(768),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english'::regconfig, section || ' ' || field_path || ' ' || text)
    ) STORED,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_schema_version integer NOT NULL,
    embedding_model text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT case_chunks_source_lane_check
        CHECK (source_lane IN ('alert_payload', 'case_analysis', 'legacy_summary'))
);

CREATE INDEX IF NOT EXISTS case_chunks_case_id_idx
    ON notable_cases.case_chunks (case_id);

CREATE INDEX IF NOT EXISTS case_chunks_section_idx
    ON notable_cases.case_chunks (section);

ALTER TABLE notable_cases.case_chunks
    ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english'::regconfig, section || ' ' || field_path || ' ' || text)
    ) STORED;

CREATE INDEX IF NOT EXISTS case_chunks_search_vector_gin_idx
    ON notable_cases.case_chunks USING gin (search_vector);

CREATE INDEX IF NOT EXISTS case_chunks_embedding_hnsw_idx
    ON notable_cases.case_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS notable_cases.chat_sessions (
    session_id text PRIMARY KEY,
    user_id text,
    mode text NOT NULL,
    selected_case_id text,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notable_cases.chat_messages (
    message_id text PRIMARY KEY,
    session_id text NOT NULL REFERENCES notable_cases.chat_sessions(session_id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    cited_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT chat_messages_role_check
        CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS chat_messages_session_id_idx
    ON notable_cases.chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS chat_sessions_expires_at_idx
    ON notable_cases.chat_sessions (expires_at);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notable_analyzer') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA notable_cases TO notable_analyzer';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES '
            || 'IN SCHEMA notable_cases TO notable_analyzer';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA notable_cases '
            || 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO notable_analyzer';
    END IF;
END $$;
