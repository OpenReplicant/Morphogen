# intent/

Desired state that orchestrators reconcile. **Written only by the promoter.** Agents have no write access (decision 0008). In production this folder becomes its own repository with branch protection; it lives here for Milestone 1.

| Path | Contents |
| --- | --- |
| `base/<slot>/` | Shared definitions per slot/provider (compose service, Nomad job, k8s manifests) |
| `environments/<env>/` | Overlays: what runs in sandbox, staging, production, with which config |
| `experiments/<id>/` | Short-lived sandbox setups; removed after a verdict |
| `policies/` | Autonomy levels, risk classes, guards (read-only mount for agents) |

Rules:
- One proposal = one branch; the promoter merges.
- Every commit message starts with `proposal:<id>` so the map links intent to evidence.
- Each orchestrator adapter watches only its environment's folder.
- Promotion staging → production is a commit copying an overlay forward.
