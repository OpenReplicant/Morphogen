-- Extensions. pgvector and AGE are for cognee search and the graph tier (decisions 0005, 0011);
-- the claim store itself needs neither, so a plain Postgres also works for development.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'age') THEN
    CREATE EXTENSION IF NOT EXISTS age;
  END IF;
END $$;

-- Roles: one writer (ingestors), one reader (PostgREST, MCP read tools, watchers),
-- one promoter (approvals, policy state). Passwords are placeholders; use secrets.
CREATE ROLE morphogen_ingestor LOGIN PASSWORD 'change-me';
CREATE ROLE morphogen_reader   LOGIN PASSWORD 'change-me';
CREATE ROLE morphogen_promoter LOGIN PASSWORD 'change-me';

GRANT CONNECT, CREATE ON DATABASE morphogen TO morphogen_ingestor;
GRANT CONNECT ON DATABASE morphogen TO morphogen_reader, morphogen_promoter;

-- Read API for the UI (PostgREST serves only this schema, read-only). The ingestor creates the
-- map views here at startup (src/morphogen/store/schema.sql).
CREATE SCHEMA IF NOT EXISTS api;
GRANT USAGE, CREATE ON SCHEMA api TO morphogen_ingestor;
GRANT USAGE ON SCHEMA api TO morphogen_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE morphogen_ingestor IN SCHEMA api GRANT SELECT ON TABLES TO morphogen_reader;

-- Promoter-owned state: proposals, approvals, policy state. Not graph data.
CREATE SCHEMA IF NOT EXISTS governance AUTHORIZATION morphogen_promoter;

CREATE TABLE governance.proposals (
  id             text PRIMARY KEY,
  target         text NOT NULL,
  risk           text NOT NULL CHECK (risk IN ('low','medium','high','irreversible')),
  event          jsonb NOT NULL,
  state          text NOT NULL DEFAULT 'pending'
                 CHECK (state IN ('pending','approved','rejected','expired','committed','verified','rolled_back')),
  decision       text,          -- what policy said: report | approve | auto | auto_notify
  note           text,          -- why it is where it is (guard, reviewer reason)
  decided_by     text,
  commit_sha     text,
  committed_at   timestamptz,
  affected_slots jsonb NOT NULL DEFAULT '[]',
  received_at    timestamptz NOT NULL DEFAULT now(),
  expires_at     timestamptz NOT NULL
);

CREATE TABLE governance.targets (
  id          text PRIMARY KEY,
  autonomy    text NOT NULL DEFAULT 'L0' CHECK (autonomy IN ('L0','L1','L2','L3','L4')),
  kill_switch boolean NOT NULL DEFAULT false
);

ALTER TABLE governance.proposals OWNER TO morphogen_promoter;
ALTER TABLE governance.targets OWNER TO morphogen_promoter;
INSERT INTO governance.targets (id) VALUES ('morphogen-self');

GRANT USAGE ON SCHEMA governance TO morphogen_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA governance TO morphogen_reader;

-- Review queue and target state for the UI and the plugin's session hook.
CREATE VIEW api.targets AS SELECT id, autonomy, kill_switch FROM governance.targets;
CREATE VIEW api.proposals AS
  SELECT id, target, risk, state, decision, note, decided_by, commit_sha, committed_at,
         affected_slots, received_at, expires_at, event->'data'->>'summary' AS summary,
         event->'data'->>'hypothesis' AS hypothesis
  FROM governance.proposals;
GRANT SELECT ON api.targets, api.proposals TO morphogen_reader;
