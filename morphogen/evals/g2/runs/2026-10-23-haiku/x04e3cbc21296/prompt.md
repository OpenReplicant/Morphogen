You are improving one provider of Morphogen's `analyser` slot.

What is wanted: anomaly's step-seconds-mean is 0.1441, over its limit 0.12. Build a provider of the analyser slot that passes the slot's contract and stays within 0.12 on the slot's benchmark.

The incumbent provider is copied into /tmp/tmp5wb1m3l8/intent/experiments/x04e3cbc21296/anomaly-x04e3cbc21296. Change the copy so that:
- it still passes every case of the slot's contract: the case files in /home/user/Morphogen/morphogen/contract/slots/analyser/cases. Run
  `KK_CASES=/home/user/Morphogen/morphogen/contract/slots/analyser python3 tests/contract.py` in /tmp/tmp5wb1m3l8/intent/experiments/x04e3cbc21296/anomaly-x04e3cbc21296: it prints "ok: <case id>" for each passing case
  and must exit 0;
- it does better than the incumbent on the slot's benchmark, which measures this:
# How the sandbox measures a provider of this slot (R5-21). The sandbox copies the claims with these
# predicates from the record (what the sandbox's role may read) into a fresh database per provider, runs
# the provider's service there for `seconds` with `env`, and takes the mean of `metric` from the
# provider's own telemetry (kk.telemetry). Lower is better.
inputs:
  - http://www.w3.org/ns/sosa/hasSimpleResult
  - https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue
metric: kk.step.duration
better: lower
seconds: 8
env:
  KK_SWEEP_SECONDS: "1"
  KK_POLL_SECONDS: "0.5"

- provider.yaml gets an id of its own (urn:kk:provider:<new-name>, lower-case letters, digits and hyphens),
  a name, and keeps the slot, the runner and the service; if you rename the package, the service and the
  runner's imports must name the new package.
Keep the agent and role the incumbent uses (AGENT, KK_ROLE). Do not touch anything outside /tmp/tmp5wb1m3l8/intent/experiments/x04e3cbc21296/anomaly-x04e3cbc21296.
When you are done, say in one line what you changed.
