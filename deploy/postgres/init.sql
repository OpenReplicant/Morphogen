-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;

-- Roles: one writer (ingestors), one reader (PostgREST, MCP read tools, watchers),
-- one promoter (approvals, policy state). Passwords are placeholders; use secrets.
CREATE ROLE morphogen_ingestor LOGIN PASSWORD 'change-me';
CREATE ROLE morphogen_reader   LOGIN PASSWORD 'change-me';
CREATE ROLE morphogen_promoter LOGIN PASSWORD 'change-me';

GRANT ALL ON DATABASE morphogen TO morphogen_ingestor;
GRANT CONNECT ON DATABASE morphogen TO morphogen_reader, morphogen_promoter;

-- Read API for the UI (PostgREST serves only this schema, read-only).
CREATE SCHEMA IF NOT EXISTS api;
GRANT USAGE ON SCHEMA api TO morphogen_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA api GRANT SELECT ON TABLES TO morphogen_reader;

-- Promoter-owned state: proposals, approvals, policy state. Not graph data.
CREATE SCHEMA IF NOT EXISTS governance AUTHORIZATION morphogen_promoter;

CREATE TABLE governance.proposals (
  id            text PRIMARY KEY,
  target        text NOT NULL,
  risk          text NOT NULL CHECK (risk IN ('low','medium','high','irreversible')),
  event         jsonb NOT NULL,
  state         text NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending','approved','rejected','expired','committed','verified','rolled_back')),
  decided_by    text,
  commit_sha    text,
  received_at   timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL
);

CREATE TABLE governance.targets (
  id         text PRIMARY KEY,
  autonomy   text NOT NULL DEFAULT 'L0' CHECK (autonomy IN ('L0','L1','L2','L3','L4')),
  kill_switch boolean NOT NULL DEFAULT false
);

GRANT USAGE ON SCHEMA governance TO morphogen_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA governance TO morphogen_reader;

-- Live UI updates: the promoter and ingestors NOTIFY on these channels.
-- Channels: morphogen_completions, morphogen_proposals
