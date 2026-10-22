# 0009 Governance: autonomy levels × risk classes

Status: accepted · 2026-10-22

**Decision.** The promoter evaluates every proposal against `intent/policies/autonomy.yaml`: target autonomy level (L0–L4) × change risk class (low, medium, high, irreversible). Irreversible always requires a person. Targets start at L0, promote on a verified record, demote automatically on failed verification or rollback. Guards: kill switch, rate limits, cooldowns with hysteresis, blast-radius budget, precondition re-check, proposal expiry.

**Why.** "Review" must not mean either "a human approves everything" or "nothing is said."
