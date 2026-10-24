# intent/

Desired state that orchestrators reconcile. Written only by the intent actuator, after a proposal is
approved in the review lane. Commit messages start with `change-set:<id>` so the record links intent to
evidence. Outcomes are observed, never claimed by the actuator.

| Path | Contents |
| --- | --- |
| `base/` | Shared definitions per slot provider |
| `environments/<sandbox|staging|production>/` | What runs where, with which config |
| `experiments/<id>/` | Short-lived sandbox setups for candidate providers |
| `catalogs/<name>.yaml` | Component sets catalog lookup searches, of any kind (R5-30); written by people |
| `policies/` | Lane policy, catalog rules (read-only to agents) |
