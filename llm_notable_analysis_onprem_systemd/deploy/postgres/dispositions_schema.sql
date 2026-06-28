CREATE SCHEMA IF NOT EXISTS notable_dispositions;

CREATE TABLE IF NOT EXISTS notable_dispositions.sync_state (
    job_name text PRIMARY KEY,
    cursor_value timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notable_dispositions.servicenow_closed_incidents (
    snow_sys_id text PRIMARY KEY,
    snow_number text NOT NULL,
    snow_table text NOT NULL,
    state text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    closed_at timestamptz,
    sys_updated_on timestamptz NOT NULL,
    disposition_normalized text NOT NULL,
    disposition_raw text,
    close_notes text,
    short_description text,
    search_name text,
    correlation_id text,
    correlation_display text,
    source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload_hash text NOT NULL,
    case_id text,
    synced_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,

    CONSTRAINT servicenow_closed_incidents_disposition_check
        CHECK (disposition_normalized IN ('likely_malicious', 'likely_benign', 'unknown'))
);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_closed_at_idx
    ON notable_dispositions.servicenow_closed_incidents (closed_at DESC);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_sys_updated_on_idx
    ON notable_dispositions.servicenow_closed_incidents (sys_updated_on DESC);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_disposition_idx
    ON notable_dispositions.servicenow_closed_incidents (disposition_normalized);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_correlation_id_idx
    ON notable_dispositions.servicenow_closed_incidents (correlation_id);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_case_id_idx
    ON notable_dispositions.servicenow_closed_incidents (case_id);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_snow_number_idx
    ON notable_dispositions.servicenow_closed_incidents (snow_number);

CREATE INDEX IF NOT EXISTS servicenow_closed_incidents_expires_at_idx
    ON notable_dispositions.servicenow_closed_incidents (expires_at);
