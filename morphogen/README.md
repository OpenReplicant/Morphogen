# Morphogen distribution

`distribution.yaml` lists the kernel slots Morphogen uses, the application slots it declares (design,
monitor, analyse, plan, execute, verify, catalog lookup) and their default providers.

| Path | What |
| --- | --- |
| `modules/` | Providers for Morphogen's slots. A module moves to `kernel/providers/` when another distribution needs it |
| `intent/` | Desired state orchestrators reconcile. Written only by the intent actuator after approval |
| `intent/policies/autonomy.yaml` | Lane policy: autonomy level × risk class |
| `ui/` | Window-manager shell; views are providers |
| `deploy/` | Compose stack |
