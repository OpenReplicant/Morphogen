// Unit tests of the data layer's pure parts: `npm test` (node --test), also run by tests/test_site.py.
import assert from "node:assert/strict";
import test from "node:test";
import { issueUrl } from "../src/lib/steer.mjs";
import { refName, safeUrl, slugify } from "../src/lib/text.mjs";
import { trialFamily } from "../src/lib/data.mjs";

test("safeUrl keeps http(s) and refuses everything else", () => {
  assert.equal(safeUrl("https://arxiv.org/abs/1"), "https://arxiv.org/abs/1");
  for (const bad of ["javascript:alert(1)", " JaVaScRiPt:alert(1)", "data:text/html,x", "//evil", "", null, 3, "http://"]) {
    assert.equal(safeUrl(bad), null, String(bad));
  }
});

test("issueUrl round-trips title, body and labels", () => {
  const title = 'Prioritise: a & b? #1 "x"', body = "line one\nresearch-action: prioritise\n100% + more & <tags>";
  const url = new URL(issueUrl("OpenReplicant/Morphogen", title, body, ["research:prioritise", "two words"]));
  assert.equal(url.host, "github.com");
  assert.equal(url.pathname, "/OpenReplicant/Morphogen/issues/new");
  assert.ok(!url.href.includes(" ") && !url.href.includes("\n"));
  assert.equal(url.searchParams.get("title"), title);
  assert.equal(url.searchParams.get("body"), body);
  assert.equal(url.searchParams.get("labels"), "research:prioritise,two words");
  assert.equal(new URL(issueUrl("o/r", "t", "b", [])).searchParams.has("labels"), false);
});

test("refs, slugs and trial families", () => {
  assert.equal(refName("component:default/decision-backend"), "decision-backend");
  assert.equal(slugify("arXiv:2610.00346"), "arxiv-2610.00346");
  assert.equal(slugify("../../etc/passwd"), "etc-passwd");
  assert.equal(trialFamily("E-17b"), "E-17");
});

test("the verdict log: reasons, the chain, and an edit", async () => {
  const { parseLog, reasonsOf, shapeVerdict, verifyChain, recordHash, primaryMetric } = await import("../src/lib/optimise.mjs");
  const a = { seq: 1, prev: "0".repeat(64), kind: "verdict", verdict: "fail", cell: "c", outcome: { denied: ["x.py: outside"], metrics: { m: { base: 1, candidate: 2, gain: -0.5, ci95: [-0.6, -0.4], sign_test_p: 0.3, ok: false } } } };
  a.hash = recordHash(a);
  const b = { seq: 2, prev: a.hash, kind: "verdict", verdict: "pass", cell: "c", outcome: { metrics: {} } };
  b.hash = recordHash(b);
  assert.deepEqual(reasonsOf(a), ["changes what the cell may not change: x.py: outside", "m: gain -50.0% (95% interval -60.0% to -40.0%, sign test p=0.3) does not meet the bar"]);
  assert.deepEqual(shapeVerdict(b).reasons, ["the checks passed"]);
  assert.equal(verifyChain([a, b]).links, true);
  assert.deepEqual(verifyChain([a, b]).edited, []);
  assert.deepEqual(verifyChain([a, { ...b, claim: "edited" }]).edited, [2]);
  assert.equal(verifyChain([a, { ...b, prev: "f".repeat(64) }]).brokenAt, 2);
  assert.equal(parseLog(`${JSON.stringify(a)}\n${JSON.stringify(b)}\n`).length, 2); // JSON lines
  assert.equal(parseLog(JSON.stringify({ records: [a] })).length, 1);
  assert.throws(() => parseLog("{not json"), /not valid JSON/);
  assert.deepEqual(primaryMetric({ mape: { lower: true } }), { name: "mape", direction: "lower" });
  assert.deepEqual(primaryMetric("accuracy higher, wall_seconds lower"), { name: "accuracy", direction: "higher" });
});

test("a number is hashed as the file wrote it", async () => {
  const { parseLog, recordHash } = await import("../src/lib/optimise.mjs");
  const text = '[{"seq": 1, "x": 1.0, "prev": "p"}]';
  const [{ raw }] = parseLog(text);
  const plainHash = recordHash(JSON.parse(text));
  assert.notEqual(recordHash(raw), plainHash, "1.0 and 1 hash differently, as in Python's canonical JSON");
});
