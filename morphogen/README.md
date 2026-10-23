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

Morphogen's own structure in the record (T4), with the self-encoder from the kernel:

```sh
python3 kernel/providers/install.py <db> pack-loader validator-shacl belief-corroboration self-encoder
PYTHONPATH=kernel/src:kernel/providers/self-encoder DATABASE_URL=dbname=<db> \
  python3 -m self_encoder scan --repo . --distribution morphogen/distribution.yaml
# validator and belief services apply and score it; then:
python3 -m self_encoder answer              # which provider fills each slot, cited to file and line
```
