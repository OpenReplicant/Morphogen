// The Optimise page's data: the cells in the map (what may change, how each is scored, who may merge a pass) and the
// judge's verdict log. Plain JavaScript with no Astro imports, so `node --test` reads it too.
//
// The verdict log is the judge's evidence log (morphogen/evidence.py), exported with
//     morphogen evidence --limit 100000 > verdicts.json
// (a JSON array, newest first, as that command prints it) or as JSON lines. Each record is a JSON object chained to
// the one before it by `prev` and `hash`; a verdict has `kind: verdict`, `verdict: pass|fail`, `refs` (base and
// candidate commit), `parameters`, `gate`, and an `outcome` whose keys depend on the method (morphogen/judge.py;
// schemas/evidence-record.v1.json). The judge's own `reasons` are not stored, so the reasons shown are rebuilt from
// the outcome the same way the judge words them.
import crypto from "node:crypto";
import fs from "node:fs";
import { refName } from "./text.mjs";

/** A number as the file wrote it: Python writes 1.0 and 1e-05 where JavaScript would write 1 and 0.00001, and a
 *  hash is of the text. */
class Raw {
  constructor(source) {
    this.source = source;
  }
}

const isObj = (v) => v != null && typeof v === "object" && !Array.isArray(v);
const list = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v) => (typeof v === "string" ? v : v == null ? "" : String(v));

// ---------------------------------------------------------------- the log

/** The same canonical JSON the log hashes (morphogen/evidence.py `canonical`): keys sorted, no spaces, UTF-8. */
export function canonical(v) {
  if (v instanceof Raw) return v.source;
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (isObj(v)) return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}

export function recordHash(rec) {
  const { hash, ...rest } = rec;
  return crypto.createHash("sha256").update(canonical(rest)).digest("hex");
}

function parseBoth(t, what) {
  try {
    const plain = JSON.parse(t);
    let raw = plain;
    try {
      raw = JSON.parse(t, (k, v, ctx) => (typeof v === "number" && ctx?.source ? new Raw(ctx.source) : v));
    } catch {
      raw = plain; // no number sources in this runtime: hashes are checked on the numbers JavaScript writes
    }
    return { plain, raw };
  } catch (e) {
    throw new Error(`build: ${what} is not valid JSON: ${e.message}`);
  }
}

/** Parse a log file's text: a JSON array, `{records: [...]}`, or JSON lines; each row twice, as plain values and with
 *  its numbers as written. Throws on text that is none of them. */
export function parseLog(text, name = "the verdict log") {
  const t = text.trim();
  let rows, raws;
  if (!t) rows = raws = [];
  else if (t.startsWith("[") || (t.startsWith("{") && !t.includes("\n{"))) {
    const { plain, raw } = parseBoth(t, name);
    const pick = (j) => (Array.isArray(j) ? j : Array.isArray(j?.records) ? j.records : [j]);
    rows = pick(plain);
    raws = pick(raw);
  } else {
    const parsed = t.split("\n").filter((l) => l.trim()).map((l, i) => parseBoth(l, `${name}, line ${i + 1}`));
    rows = parsed.map((x) => x.plain);
    raws = parsed.map((x) => x.raw);
  }
  return rows.map((r, i) => ({ row: r, raw: raws[i] }));
}

/** Whether the records form the log's chain: each one's `prev` is the one before's `hash`, `seq` counts up by one, and
 *  its hash recomputes from the record as written. `edited` lists the records whose hash does not recompute. */
export function verifyChain(sorted, raws = new Map()) {
  let links = true, brokenAt = null;
  const edited = [];
  sorted.forEach((r, i) => {
    if (i > 0) {
      const p = sorted[i - 1];
      if (r.prev !== p.hash || r.seq !== p.seq + 1) {
        if (links) brokenAt = r.seq;
        links = false;
      }
    }
    if (typeof r.hash !== "string" || recordHash(raws.get(r) || r) !== r.hash) edited.push(r.seq);
  });
  const first = sorted[0];
  return {
    records: sorted.length, from: first?.seq ?? null, to: sorted.at(-1)?.seq ?? null,
    complete: !!first && first.seq === 1 && /^0{64}$/.test(str(first.prev)),
    links, brokenAt, edited,
  };
}

const EVIDENCE_FIELDS = ["signature", "signatures", "attestation", "attestations", "transparency", "transparency_log", "tlog",
  "rekor", "log_index", "inclusion_proof", "bundle", "sigstore"];

/** Any signature or transparency-log entry a record carries, as [field, text] (shortened). Nothing in the judge's own
 *  records has one yet; the log is open to fields a caller adds. */
export function proofsOf(rec) {
  const out = [];
  for (const k of Object.keys(rec)) {
    if (!EVIDENCE_FIELDS.includes(k.toLowerCase())) continue;
    const v = rec[k];
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) continue;
    const text = typeof v === "string" ? v : canonical(v);
    out.push([k, text.length > 240 ? `${text.slice(0, 240)}…` : text]);
  }
  return out;
}

const short = (sha) => str(sha).slice(0, 12);

function pct(x) {
  const n = num(x);
  return n == null ? "" : `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
}

/** The measures of a verdict: one row per metric the judge compared, from outcome.metrics. */
function measuresOf(outcome) {
  const m = isObj(outcome.metrics) ? outcome.metrics : {};
  return Object.entries(m).filter(([, c]) => isObj(c)).map(([name, c]) => ({
    name, base: num(c.base), candidate: num(c.candidate), gain: num(c.gain), ci95: Array.isArray(c.ci95) ? c.ci95.map(num) : null,
    p: num(c.sign_test_p), ok: c.ok === true ? true : c.ok === false ? false : null,
  }));
}

/** Why, in the judge's own words, from what a verdict record keeps. */
export function reasonsOf(rec) {
  const o = isObj(rec.outcome) ? rec.outcome : {};
  const why = [];
  const denied = list(o.denied).map(str).filter(Boolean);
  if (denied.length) why.push(`changes what the cell may not change: ${denied.join("; ")}`);
  const forbidden = list(o.forbidden).map(str).filter(Boolean);
  if (forbidden.length) why.push(`changes files that shadow standard modules or customise Python: ${forbidden.join(", ")}`);
  for (const v of list(o.parameter_violations)) why.push(str(v));
  if (o.check === false) why.push("the base's tests fail on the candidate");
  const system = isObj(o.system) ? o.system : null;
  if (system && system.ok === false) why.push(`the enclosing system (${str(system.cell || system.target)}) gets worse`);
  for (const x of list(o.interfaces)) if (isObj(x) && x.passed === false) why.push(`interface ${str(x.interface)}: its test fails on the candidate`);
  for (const x of list(o.tests)) if (isObj(x) && x.passed === false) why.push(`${x.interface ? `interface ${str(x.interface)}` : `cell ${str(x.cell)}`}: its test fails on the candidate`);
  const wrong = num(o.wrong) || 0, failed = num(o.failed) || 0;
  if (wrong || failed) why.push(`${wrong} wrong and ${failed} failed outputs on ${num(o.generated_inputs) ?? "?"} generated inputs`);
  if (num(o.timed_output_mismatches)) why.push(`${o.timed_output_mismatches} timed runs gave different output from the base`);
  for (const m of measuresOf(o)) {
    if (m.ok === false) {
      const ci = m.ci95 && m.ci95.length === 2 ? ` (95% interval ${pct(m.ci95[0])} to ${pct(m.ci95[1])}${m.p != null ? `, sign test p=${m.p}` : ""})` : "";
      why.push(`${m.name}: gain ${pct(m.gain)}${ci} does not meet the bar`);
    }
  }
  return why;
}

/** The cells a record is about: `cell`, else `cells`, else the names in subject.system. */
function cellsIn(rec) {
  if (rec.cell) return [str(rec.cell)];
  if (Array.isArray(rec.cells) && rec.cells.length) return rec.cells.map(str);
  const sys = str(rec.subject?.system);
  return sys ? sys.split(",").map((x) => x.trim()).filter(Boolean) : [];
}

/** One verdict record, as the page shows it. */
export function shapeVerdict(rec) {
  const o = isObj(rec.outcome) ? rec.outcome : {};
  const passed = rec.verdict === "pass";
  const params = isObj(rec.parameters)
    ? Object.entries(rec.parameters).filter(([, p]) => isObj(p)).map(([name, p]) => ({ name, owner: str(p.owner), base: p.base, candidate: p.candidate }))
    : [];
  const files = isObj(o.files) ? Object.keys(o.files).sort() : [];
  const reasons = reasonsOf(rec);
  const measures = measuresOf(o);
  return {
    seq: rec.seq, at: str(rec.at), by: str(rec.by), trust: str(rec.trust), claim: str(rec.claim), method: str(rec.method),
    verdict: passed ? "pass" : "fail", cells: cellsIn(rec), subject: str(rec.subject?.path),
    base: str(rec.refs?.base), candidate: str(rec.refs?.candidate), baseShort: short(rec.refs?.base), candidateShort: short(rec.refs?.candidate),
    gate: str(rec.gate?.decision), sandbox: str(rec.sandbox), request: isObj(rec.request) ? str(rec.request.digest) : "",
    measures, changed: params.filter((p) => JSON.stringify(p.base) !== JSON.stringify(p.candidate)), params, files,
    reasons: reasons.length ? reasons : passed ? (measures.length ? ["every measure met its bar"] : ["the checks passed"]) : ["the record gives no reason"],
    proofs: proofsOf(rec), hash: str(rec.hash), prev: str(rec.prev), generated: num(o.generated_inputs) ?? (isObj(o.generated_inputs) ? num(o.generated_inputs.cases) : null),
  };
}

/** Read a verdict log. `file` is null in the result when it does not exist; a file that is not a log stops the build. */
export function loadVerdicts(file) {
  const none = { file: null, records: [], all: [], chain: null, problems: [] };
  if (!file || !fs.existsSync(file)) return none;
  const parsed = parseLog(fs.readFileSync(file, "utf8"), file);
  const problems = [];
  const raws = new Map();
  const all = parsed.filter((p, i) => (isObj(p.row) ? true : (problems.push(`record ${i + 1} is not an object`), false)))
    .map((p, i) => {
      const r = { ...p.row, seq: Number.isInteger(p.row.seq) ? p.row.seq : i + 1 };
      raws.set(r, { ...p.raw, seq: p.raw.seq instanceof Raw ? p.raw.seq : r.seq });
      return r;
    })
    .sort((a, b) => a.seq - b.seq);
  const verdicts = all.filter((r) => r.kind === "verdict" && (r.verdict === "pass" || r.verdict === "fail")).map(shapeVerdict);
  return { file, records: verdicts, all, chain: all.length ? verifyChain(all, raws) : null, problems };
}

// ---------------------------------------------------------------- the cells

/** The metric a cell's `better` names first, and its direction: "mape lower" or {mape: {lower: true}}. */
export function primaryMetric(better) {
  if (typeof better === "string") {
    const first = better.split(",")[0].trim().split(/\s+/);
    return first[0] ? { name: first[0], direction: first[1] || "" } : null;
  }
  if (isObj(better)) {
    const [name, spec] = Object.entries(better)[0] || [];
    if (!name) return null;
    const dir = typeof spec === "string" ? spec : isObj(spec) ? (spec.lower || spec.direction === "lower" ? "lower" : spec.higher || spec.direction === "higher" ? "higher" : "") : "";
    return { name, direction: dir };
  }
  return null;
}

function metricsText(better) {
  if (typeof better === "string") return better;
  if (isObj(better)) return Object.entries(better).map(([k, v]) => `${k} ${primaryMetric({ [k]: v }).direction}`.trim()).join(", ");
  return "";
}

/** Everything in `change` as {target, bounds}: `path#NAME in 0..100`, `path:key`, a path or a glob. */
function changeOf(change) {
  return list(change).map(str).map((c) => {
    const m = /^(.*?)\s+in\s+(.+)$/.exec(c);
    return { target: m ? m[1] : c, bounds: m ? m[2] : "" };
  });
}

/** The cells in the map: a component or system with a `run` (or `tests`) under `spec.morphogen`, with the System's
 *  `defaults` underneath. A role or an option is never a cell; an entity with neither is structure. */
export function cellsOf(site) {
  const system = site.of("system").find((s) => s.spec?.morphogen) || null;
  const settings = system?.spec?.morphogen || {};
  const defaults = isObj(settings.defaults) ? settings.defaults : {};
  const out = [];
  for (const ent of site.entities.values()) {
    if (ent.type !== "component" && ent.type !== "system") continue;
    const own = ent.spec?.morphogen;
    if (!isObj(own) || !(own.run || own.tests)) continue;
    const r = { ...defaults, ...Object.fromEntries(Object.entries(own).filter(([, v]) => v !== null)) };
    const lifecycle = str(ent.spec?.lifecycle);
    const auto = isObj(settings.autonomy) ? settings.autonomy : {};
    const decision = auto[lifecycle] === "merge" ? "merge" : "review";
    const owner = ent.out.find((e) => e.rel === "owned-by")?.to || null;
    out.push({
      ent, name: ent.name, lifecycle, owner, rules: r,
      description: str(r.description),
      change: changeOf(r.change), keep: list(r.keep).map(str),
      judged: !!r.run, run: str(r.run), score: str(r.score), tests: list(r.tests).map(str),
      better: metricsText(r.better), primary: primaryMetric(r.better), observe: isObj(r.observe) ? canonical(r.observe) : str(r.observe),
      autonomy: decision, autonomyNote: decision === "merge"
        ? `a pass on a ${lifecycle || "this"} cell may be merged by an agent`
        : `a pass on a ${lifecycle || "this"} cell goes to a person: the judge never merges, and the project's autonomy does not name this lifecycle as merge`,
    });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

/** Verdicts by cell name (a verdict on several cells is listed under each), and the ones whose cell is not in the map. */
export function verdictsByCell(site, cells) {
  const known = new Set(cells.map((c) => c.name));
  const by = new Map();
  const strays = new Map();
  for (const v of site.verdicts.records) {
    const names = v.cells.length ? v.cells : [v.subject || "(unnamed)"];
    for (const n0 of names) {
      const n = refName(n0);
      const bucket = known.has(n) ? by : strays;
      if (!bucket.has(n)) bucket.set(n, []);
      bucket.get(n).push(v);
    }
  }
  for (const m of [by, strays]) for (const l of m.values()) l.sort((a, b) => b.seq - a.seq);
  return { by, strays };
}

/** What the judge last measured for a cell: the newest verdict's measures (what was observed, as the judge took it). */
export function lastMeasured(verdicts) {
  return (verdicts || []).find((v) => v.measures.length) || null;
}
