You are improving one provider of Morphogen's `analyser` slot.

What is wanted: anomaly's step-seconds-mean is 0.1287, over its limit 0.1121. Build a provider of the analyser slot that passes the slot's contract and stays within 0.1121 on the slot's benchmark.

The incumbent provider is copied into /tmp/kk-build-hhxqpv8p/anomaly-xacce4724309a. Change the copy so that:
- it still passes every case of the slot's contract: the case files in /home/user/Morphogen/morphogen/contract/slots/analyser/cases. Run
  `python3 /home/user/Morphogen/morphogen/contract/slots/analyser/runner.py /tmp/kk-build-hhxqpv8p/anomaly-xacce4724309a`: it prints "ok: <case id>" for each passing case and must exit 0.
  The sandbox also loads every case into a database and judges what one real pass of the service submits
  (its `one_pass(conn)` in the package's `__main__`), so the way the service reads the record must find
  everything the rule needs;
- it does better than the incumbent on the slot's benchmark, which measures this:
# How the sandbox measures a provider of this slot (R5-21, R5-23). The sandbox copies the claims with these
# predicates from the record (what the sandbox's role may read) into a fresh database per provider, then
# times full passes of the provider from its own process: `<package>.__main__.<entry>(conn)`, connected as
# the incumbent's login, after `warmup` untimed passes. Before each pass it adds one new window of input,
# as production does, so a pass that skips its work because nothing changed does not help here. The
# metric is the mean of the timed passes, in seconds. Lower is better.
inputs:
  - http://www.w3.org/ns/sosa/hasSimpleResult
  - https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue
entry: one_pass
metric: pass-seconds
better: lower
warmup: 1
passes: 5

- provider.yaml gets an id of its own (urn:kk:provider:<new-name>, lower-case letters, digits and hyphens),
  a name, and keeps the slot, the runner and the service; if you rename the package, the service and the
  slot runner imports <package>.detect.
Keep the agent and role the incumbent uses (AGENT, KK_ROLE) and its migration.sql unchanged. Do not touch
anything outside /tmp/kk-build-hhxqpv8p/anomaly-xacce4724309a.
When you are done, say in one line what you changed.
