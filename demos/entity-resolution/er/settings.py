"""Settings Morphogen may tune. Each is declared as a parameter in cells.yaml (file, name, owner,
range or choices), so the judge can read it in base and candidate and refuse a change it may not
make. Plain constants only: a value computed by an expression cannot be read by the judge."""

# Which backend fills the `backend` cell (agent, choices: see er.BACKENDS).
BACKEND = "tfidf"

# A candidate is returned by resolve() only at or above this score (agent, range [0.5, 0.99]).
THRESHOLD = 0.5

# Blocking: a known record is compared only if it shares a token whose document frequency is at
# most this fraction of all known records (agent, range [0.01, 0.5]).
BLOCK_MAX_DF = 0.2

# Most candidates scored per mention, after blocking (agent, range [5, 200]).
BLOCK_LIMIT = 50

# Score multiplier when both names carry model codes and none agree (agent, range [0.0, 1.0]).
MODEL_MISMATCH = 0.2

# Score multiplier when each name has distinctive words the other lacks, such as two editions of
# one product (agent, range [0.0, 1.0]).
WORD_MISMATCH = 0.5

# Two words count as the same if their similarity ratio is at least this, so typos still agree
# (agent, range [0.6, 1.0]).
TYPO_RATIO = 0.8

# Abbreviations expanded before comparing (operator: a vocabulary, not a tunable).
ALIASES = {"ms": "microsoft", "hp": "hewlett packard"}

# Words that never distinguish two names (operator: a vocabulary).
STOPWORDS = {"and", "the", "with", "for", "of", "by", "in", "a", "an"}
