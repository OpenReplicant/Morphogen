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
