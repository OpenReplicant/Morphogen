-- Map store schema (decision 0011). Idempotent; run by the ingestor role at startup.
CREATE SCHEMA IF NOT EXISTS map;

CREATE TABLE IF NOT EXISTS map.claims (
  id              uuid PRIMARY KEY,
  key             text NOT NULL,
  kind            text NOT NULL,
  status          text NOT NULL CHECK (status IN ('observed','intended','hypothetical')),
  environment     text NOT NULL CHECK (environment IN ('sandbox','staging','production')),
  level           text NOT NULL CHECK (level IN ('instance','type')),
  provenance      text NOT NULL CHECK (provenance IN ('discovered','asserted','inferred')),
  confidence      double precision NOT NULL,
  source_event_id text NOT NULL,
  valid_from      timestamptz NOT NULL,
  valid_to        timestamptz,            -- null: valid until further notice
  recorded_at     timestamptz NOT NULL,
  record_to       timestamptz,            -- null: still part of what the system believes
  retracted       boolean NOT NULL DEFAULT false,
  content         jsonb NOT NULL
);

-- At most one open version per identity.
CREATE UNIQUE INDEX IF NOT EXISTS claims_open_identity
  ON map.claims (key, status, environment) WHERE valid_to IS NULL AND record_to IS NULL;
CREATE INDEX IF NOT EXISTS claims_key ON map.claims (key);
CREATE INDEX IF NOT EXISTS claims_kind_status ON map.claims (kind, status, environment);

-- Observation freshness: operational, not a claim (touching it changes no belief).
CREATE TABLE IF NOT EXISTS map.seen (
  key       text PRIMARY KEY,
  last_seen timestamptz NOT NULL
);

-- Read API for PostgREST and the UI: current claims only.
CREATE SCHEMA IF NOT EXISTS api;

CREATE OR REPLACE VIEW api.claims AS
  SELECT c.id, c.key, c.kind, c.status, c.environment, c.level, c.provenance, c.confidence,
         c.source_event_id, c.valid_from, c.recorded_at, s.last_seen, c.content
  FROM map.claims c LEFT JOIN map.seen s USING (key)
  WHERE c.record_to IS NULL AND c.valid_to IS NULL AND NOT c.retracted;

CREATE OR REPLACE VIEW api.slots AS
  SELECT key, status, environment, provenance, confidence, last_seen,
         content->>'name' AS name, content->>'role' AS role, content->>'parent' AS parent
  FROM api.claims WHERE kind = 'Slot';

CREATE OR REPLACE VIEW api.couplings AS
  SELECT key, status, environment, provenance, confidence, last_seen,
         content->>'coupling_type' AS coupling_type,
         content->>'source_slot' AS source_slot, content->>'target_slot' AS target_slot,
         content->>'source_port' AS source_port, content->>'target_port' AS target_port,
         content->>'contract' AS contract
  FROM api.claims WHERE kind = 'Coupling';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'morphogen_reader') THEN
    GRANT USAGE ON SCHEMA map, api TO morphogen_reader;
    GRANT SELECT ON ALL TABLES IN SCHEMA map TO morphogen_reader;
    GRANT SELECT ON api.claims, api.slots, api.couplings TO morphogen_reader;
  END IF;
END $$;
