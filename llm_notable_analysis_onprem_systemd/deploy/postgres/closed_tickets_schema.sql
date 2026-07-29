CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS notable_closed_tickets;

CREATE TABLE IF NOT EXISTS notable_closed_tickets.sync_state (
    job_name text PRIMARY KEY,
    cursor_value timestamptz NOT NULL,
    cursor_sys_id text NOT NULL DEFAULT '',
    last_reconciled_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notable_closed_tickets.servicenow_tickets (
    ticket_id text PRIMARY KEY,
    ticket_number text,
    source_table text NOT NULL,
    source_url text,
    state text,
    is_active boolean NOT NULL DEFAULT true,
    closed_at timestamptz,
    source_updated_at timestamptz NOT NULL,
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    journals_payload jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_hash text NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    index_status text NOT NULL DEFAULT 'pending',
    index_error text,
    last_indexed_at timestamptz,

    CONSTRAINT servicenow_tickets_index_status_check
        CHECK (index_status IN ('pending', 'ready', 'failed', 'not_indexed'))
);

CREATE INDEX IF NOT EXISTS servicenow_tickets_source_updated_at_idx
    ON notable_closed_tickets.servicenow_tickets (source_updated_at DESC);

CREATE INDEX IF NOT EXISTS servicenow_tickets_ticket_number_idx
    ON notable_closed_tickets.servicenow_tickets (ticket_number);

CREATE INDEX IF NOT EXISTS servicenow_tickets_is_active_idx
    ON notable_closed_tickets.servicenow_tickets (is_active);

CREATE INDEX IF NOT EXISTS servicenow_tickets_expires_at_idx
    ON notable_closed_tickets.servicenow_tickets (expires_at);

CREATE INDEX IF NOT EXISTS servicenow_tickets_index_status_idx
    ON notable_closed_tickets.servicenow_tickets (index_status);

CREATE TABLE IF NOT EXISTS notable_closed_tickets.attachments (
    attachment_id text PRIMARY KEY,
    ticket_id text NOT NULL REFERENCES notable_closed_tickets.servicenow_tickets(ticket_id) ON DELETE CASCADE,
    file_name text,
    content_type text,
    size_bytes bigint,
    source_updated_at timestamptz,
    storage_path text,
    content_hash text,
    download_status text NOT NULL DEFAULT 'pending',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS attachments_ticket_id_idx
    ON notable_closed_tickets.attachments (ticket_id);

CREATE INDEX IF NOT EXISTS attachments_download_status_idx
    ON notable_closed_tickets.attachments (download_status);

-- Attachment semantic extraction fields (semantic_description, semantic_extraction_status)
-- are stored in metadata jsonb; file bytes live on disk at storage_path only.

CREATE TABLE IF NOT EXISTS notable_closed_tickets.ticket_chunks (
    chunk_id text PRIMARY KEY,
    ticket_id text NOT NULL REFERENCES notable_closed_tickets.servicenow_tickets(ticket_id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
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
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ticket_chunks_ticket_id_idx
    ON notable_closed_tickets.ticket_chunks (ticket_id);

CREATE INDEX IF NOT EXISTS ticket_chunks_search_vector_gin_idx
    ON notable_closed_tickets.ticket_chunks USING gin (search_vector);

CREATE INDEX IF NOT EXISTS ticket_chunks_embedding_hnsw_idx
    ON notable_closed_tickets.ticket_chunks USING hnsw (embedding vector_cosine_ops);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'notable_analyzer') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA notable_closed_tickets TO notable_analyzer';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES '
            || 'IN SCHEMA notable_closed_tickets TO notable_analyzer';
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA notable_closed_tickets '
            || 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO notable_analyzer';
    END IF;
END $$;
