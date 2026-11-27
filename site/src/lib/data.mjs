// The site's data: the claim, role and option files named in config.toml, validated, joined into one graph of
// entities with typed references, and the backlinks of every reference. Plain JavaScript with no Astro imports, so
// the pages, the data files and `node --test` all read the same thing.
//
// Entities and their pages:
//   claim     claims/<name>.html     an EvidenceClaim file (schemas/evidence-claim.v1.json)
//   role      roles/<name>.html      a Component with spec.type role
//   option    options/<name>.html    a Component with spec.lifecycle candidate
//   component components/<name>.html any other Component
//   resource  resources/<name>.html  a Resource: a model, engine, GPU or dataset (spec.type)
//   system    systems/<name>.html    a System
//   trial     trials/<id>.html       derived: a claim's source when it is our trial or probe, and every outcome's trial
//   paper     papers/<id>.html       derived: a claim's source when it is a paper (or any other outside source)
//   page      <slug>.html            a Markdown file in site/content (attached by the Astro side, site.mjs)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse as parseToml } from "smol-toml";
import YAML from "yaml";
import { MIXED, OBSERVATION, refKind, refName, slugify, truncate } from "./text.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// site/: astro.config.mjs sets SITE_DIR, since a bundled page no longer sits where this file does.
export const SITE_DIR = process.env.SITE_DIR || path.resolve(HERE, "..", "..");

export const TYPES = {
  claim: { dir: "claims", one: "Claim", many: "Claims" },
  paper: { dir: "papers", one: "Paper", many: "Papers" },
  trial: { dir: "trials", one: "Trial", many: "Trials" },
  option: { dir: "options", one: "Option", many: "Options" },
  role: { dir: "roles", one: "Role", many: "Roles" },
  resource: { dir: "resources", one: "Resource", many: "Resources" },
  component: { dir: "components", one: "Component", many: "Components" },
  system: { dir: "systems", one: "System", many: "Systems" },
  page: { dir: "", one: "Page", many: "Pages" },
};

// Each reference has a name read from both ends: [outgoing, incoming].
export const RELS = {
  about: ["Option", "Claims about it"],
  role: ["Role", "Claims for this role"],
  from: ["Source", "Claims from it"],
  "measured-on": ["Measured on", "Claims measured on it"],
  "assessed-on": ["Assessed on", "Claims assessed with it"],
  "tested-in": ["Outcome from trial", "Outcomes it produced"],
  observed: ["Observations it rests on", "Paper claims it bears on"],
  "see-also": ["See also", "Referred to by"],
  fills: ["Fills the role", "Options for it"],
  "part-of": ["Part of", "Parts"],
  "in-system": ["System", "In this system"],
  mentions: ["Mentions", "Notes and pages"],
  "uses-trial": ["Trial", "Claims from it"],
};

// ---------------------------------------------------------------- reading files

/** YAML documents (the YAML 1.2 core schema: a date stays a YYYY-MM-DD string, and `E-17` stays text, where the
 *  `yaml` package's 1.1 schema would read it as a number). */
export function loadYamlDocs(file) {
  const text = fs.readFileSync(file, "utf8");
  return YAML.parseAllDocuments(text)
    .map((d) => {
      if (d.errors.length) throw new Error(`build: ${file}: ${d.errors[0].message}`);
      return jsonable(d.toJS({ maxAliasCount: 100 }));
    })
    .filter((d) => d && typeof d === "object" && !Array.isArray(d));
}

/** Dates as the schema and JSON want them: a date at midnight UTC is YYYY-MM-DD, any other an ISO string. */
export function jsonable(v) {
  if (v instanceof Date) {
    const iso = v.toISOString();
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso;
  }
  if (Array.isArray(v)) return v.map(jsonable);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [String(k), jsonable(x)]));
  return v;
}

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walk(p));
    else if (/\.ya?ml$/.test(ent.name)) out.push(p);
  }
  return out;
}

function makeValidator(schema) {
  const ajv = new Ajv2020({ allErrors: false, strict: false });
  addFormats(ajv, ["date", "uri"]);
  return ajv.compile(schema);
}

/** Every EvidenceClaim under the directories, validated; an invalid one, or a name used twice, stops the build. */
export function loadClaims(dirs, root, schema) {
  const validate = schema ? makeValidator(schema) : null;
  const claims = [];
  const seen = new Map();
  for (const d of dirs) {
    for (const file of walk(d).sort()) {
      for (const doc of loadYamlDocs(file)) {
        if (doc.kind !== "EvidenceClaim") continue;
        const abs = path.resolve(file);
        const rel = abs.startsWith(root + path.sep) ? path.relative(root, abs).split(path.sep).join("/") : path.basename(abs);
        if (validate && !validate(doc)) {
          const err = validate.errors[0];
          const where = err.instancePath.replace(/^\//, "");
          throw new Error(`build: ${rel} is not a valid EvidenceClaim: ${where}: ${err.message}`);
        }
        const name = doc.metadata.name;
        if (seen.has(name)) throw new Error(`build: claim name ${name} is in both ${seen.get(name)} and ${rel}`);
        seen.set(name, rel);
        claims.push({ doc, path: rel });
      }
    }
  }
  return claims;
}

/** queue.json, watch.yaml, seen.jsonl and index.json from the research agent's directory. Each is optional. */
export function loadResearch(dir) {
  const out = {};
  if (!dir || !fs.existsSync(dir)) return out;
  for (const [name, key] of [["queue.json", "queue"], ["index.json", "index"]]) {
    const p = path.join(dir, name);
    if (fs.existsSync(p)) out[key] = JSON.parse(fs.readFileSync(p, "utf8"));
  }
  const watch = path.join(dir, "watch.yaml");
  if (fs.existsSync(watch)) out.watch = loadYamlDocs(watch)[0] || {};
  const seen = path.join(dir, "seen.jsonl");
  if (fs.existsSync(seen)) {
    out.seen = fs.readFileSync(seen, "utf8").split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));
  }
  return out;
}

/** Where to read from: SITE_CONFIG and SITE_ROOT override site/config.toml and the repository root. */
export function locate(env = process.env) {
  const config = path.resolve(env.SITE_CONFIG || path.join(SITE_DIR, "config.toml"));
  const root = path.resolve(env.SITE_ROOT || path.dirname(SITE_DIR));
  return { config, root };
}

// ---------------------------------------------------------------- the graph

export class Site {
  constructor(cfg, root) {
    this.title = cfg.title || "Morphogen research";
    this.repo = cfg.repo;
    this.branch = cfg.branch || "main";
    this.system = cfg.system;
    this.labels = cfg.labels || {};
    this.root = root;
    this.entities = new Map(); // id -> entity
    this.edges = [];
    this.unresolved = [];
    this.research = {};
    this.pages = [];
  }

  // ---- entities and references

  add(type, key, fields) {
    const id = `${type}:${key}`;
    if (this.entities.has(id)) return this.entities.get(id);
    const slug = slugify(key);
    const dir = TYPES[type].dir;
    const url = (dir ? `${dir}/` : "") + `${slug}.html`;
    for (const other of this.entities.values()) {
      if (other.url === url) throw new Error(`build: ${id} and ${other.id} would both be written to ${url}`);
    }
    const ent = { id, type, key, slug, url, title: key, summary: "", out: [], in: [], ...fields };
    this.entities.set(id, ent);
    return ent;
  }

  link(from, to, rel, extra = {}) {
    if (!from || !to) return;
    const edge = { from, to, rel, ...extra };
    this.edges.push(edge);
    from.out.push(edge);
    to.in.push(edge);
  }

  of(type) {
    return [...this.entities.values()].filter((x) => x.type === type);
  }

  get claims() {
    return this.of("claim");
  }

  claim(name) {
    return this.entities.get(`claim:${name}`) || null;
  }

  /** A catalog entity from a Backstage ref (`component:default/x`, `resource:default/x`) or a bare name. */
  catalogRef(ref) {
    if (!ref) return null;
    const kind = refKind(ref);
    const name = refName(ref);
    const types = { component: ["role", "option", "component"], resource: ["resource"], system: ["system"] }[kind]
      || (kind ? [] : ["role", "option", "component", "resource", "system"]);
    for (const t of types) {
      const e = this.entities.get(`${t}:${name}`);
      if (e) return e;
    }
    return null;
  }

  /** A reference from a Markdown page's front matter: `claim:name`, `trial:E-04a`, `paper:arXiv:2610.00346`,
   *  `role:x`, `option:x`, `resource:x`, `system:x`, or a Backstage ref. */
  resolve(ref) {
    const s = String(ref || "").trim();
    const i = s.indexOf(":");
    if (i < 0) return this.catalogRef(s);
    const kind = s.slice(0, i).toLowerCase();
    const rest = s.slice(i + 1);
    if (TYPES[kind] && kind !== "page") {
      const direct = this.entities.get(`${kind}:${refName(rest)}`) || this.entities.get(`${kind}:${rest}`);
      if (direct) return direct;
      const want = slugify(rest);
      return this.of(kind).find((x) => x.slug === want) || null;
    }
    return this.catalogRef(s);
  }

  /** The distinct entities an entity links to (or from) by one kind of reference, in file order. */
  outs(ent, rel) {
    return uniq(ent.out.filter((x) => x.rel === rel).map((x) => x.to));
  }

  ins(ent, rel) {
    return uniq(ent.in.filter((x) => x.rel === rel).map((x) => x.from));
  }

  // ---- claim status

  assessments(c) {
    return (c.spec.assessments || []).filter((a) => a.system === this.system);
  }

  predictions(c) {
    return this.assessments(c).filter((a) => a.prediction).map((a) => a.prediction);
  }

  /** The distinct statuses of its assessments, in file order; a filter matches a claim on any of them. */
  statuses(c) {
    if (c.ours) return [OBSERVATION];
    const out = [];
    for (const a of this.assessments(c)) if (!out.includes(a.status)) out.push(a.status);
    return out.length ? out : ["untested"];
  }

  /** One status, or `mixed` when its assessments disagree. */
  status(c) {
    const s = this.statuses(c);
    return s.length === 1 ? s[0] : MIXED;
  }

  /** The models an assessment was made on, in a few words ("Inkling 2 Mini"), else every resource's name. */
  configLabel(a) {
    const names = [];
    for (const ref of a.against || []) {
      const res = this.catalogRef(ref);
      if (res && res.type === "resource" && res.kind === "model") names.push(res.title);
    }
    return (names.length ? names : (a.against || []).map(refName)).join(", ");
  }

  /** The models an assessment was made on, as entities (resources of type model), for links. */
  configModels(a) {
    return (a.against || []).map((r) => this.catalogRef(r)).filter((r) => r && r.type === "resource" && r.kind === "model");
  }

  /** The breakdown in words, for an issue body: `replicated (Inkling 2 Mini); did-not-transfer (LFM3 1.7B)`. */
  statusText(c) {
    if (c.ours || this.statuses(c).length === 1) return this.status(c);
    return this.assessments(c).map((a) => `${a.status} (${this.configLabel(a) || "unnamed configuration"})`).join("; ");
  }

  date(c) {
    const dates = [];
    for (const a of c.spec.assessments || []) dates.push(a.date, a.prediction?.date, a.outcome?.date);
    return dates.filter(Boolean).map(String).sort().at(-1) || "";
  }

  /** Newest first: the latest assessment, prediction or outcome date; then the source id; then the name. */
  sorted(claims = this.claims) {
    const key = (c) => [this.date(c), String(c.source.id || ""), c.name];
    return [...claims].sort((x, y) => {
      const a = key(x), b = key(y);
      for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i] ? 1 : -1;
      return 0;
    });
  }

  /** Every (claim, assessment) for the system with an outcome or a prediction: the rows of a "tested on" table. */
  results(claims = this.claims) {
    const rows = [];
    for (const c of claims) {
      this.assessments(c).forEach((a, i) => rows.push({ claim: c, a, i }));
    }
    return rows;
  }

  // ---- the agent's files

  queue() {
    return [...(this.research.queue?.queue || [])];
  }

  queueRank(name) {
    const q = this.queue();
    const i = q.findIndex((x) => x.claim === name);
    return i < 0 ? null : [i + 1, q[i]];
  }

  /** Where index.json and the claim files disagree (the agent rewrites the index from the files). */
  checkIndex() {
    const index = this.research.index;
    if (!index) return [];
    const listed = new Set((index.claims || []).map((c) => c.name));
    const found = new Set(this.claims.map((c) => c.name));
    return [...[...listed].filter((n) => !found.has(n)).sort().map((n) => `index.json lists ${n}, which no claim file holds`),
      ...[...found].filter((n) => !listed.has(n)).sort().map((n) => `${n} is not in index.json`)];
  }

  /** watch.yaml's topics that name a role: the open questions the agent reads papers for. */
  topicsFor(roleName) {
    return (this.research.watch?.topics || []).filter((t) => (t.roles || []).map(refName).includes(roleName));
  }

  // ---- predictions and calibration

  /** {p, held, claim, a} for each assessment whose prediction was written before an outcome it now has. */
  calibrationPairs() {
    const out = [];
    for (const c of this.claims) {
      for (const a of this.assessments(c)) {
        const pr = a.prediction || {};
        if (pr.before_outcome && a.outcome && (a.status === "replicated" || a.status === "did-not-transfer")) {
          out.push({ p: Number(pr.p_transfer), held: a.status === "replicated" ? 1 : 0, claim: c, a });
        }
      }
    }
    return out;
  }

  fileUrl(p) {
    return `https://github.com/${this.repo}/blob/${this.branch}/${p}`;
  }
}

export function brier(pairs) {
  return pairs.length ? pairs.reduce((s, x) => s + (x.p - x.held) ** 2, 0) / pairs.length : null;
}

function uniq(list) {
  return [...new Set(list)];
}

/** A resource's short name: its description up to the first comma, semicolon or colon ("Inkling 2 Mini"), else its name. */
function shortTitle(desc, name) {
  const head = String(desc || "").split(/[,;:]/)[0].trim();
  return head && head.length <= 50 ? head : name;
}

function fills(option) {
  const f = option.spec?.morphogen?.fills || [];
  return Array.isArray(f) ? f : [f];
}

/** A trial's family: E-17b, E-17c and E-17d are all E-17. */
export function trialFamily(id) {
  return String(id).replace(/(\d)[a-z]+$/i, "$1");
}

function sourceKey(src) {
  return String(src.id || src.url || src.title || "unnamed source");
}

/** Read everything and build the graph. Throws on an invalid claim. */
export function loadSite({ config, root } = locate()) {
  const cfg = parseToml(fs.readFileSync(config, "utf8"));
  const srcs = cfg.sources || {};
  const schema = srcs.schema ? JSON.parse(fs.readFileSync(path.join(root, srcs.schema), "utf8")) : null;
  const raw = loadClaims((srcs.claims || []).map((d) => path.join(root, d)), root, schema);
  const docs = [];
  const warnings = [];
  for (const p of srcs.catalog || []) {
    const f = path.join(root, p);
    if (fs.existsSync(f)) docs.push(...loadYamlDocs(f));
    else warnings.push(`${p} does not exist; skipped`);
  }
  const site = new Site(cfg, root);
  site.research = loadResearch(srcs.research ? path.join(root, srcs.research) : null);
  site.warnings = warnings;

  // catalog entities
  for (const d of docs) {
    const md = d.metadata || {};
    const spec = d.spec || {};
    if (!md.name) continue;
    const base = { doc: d, name: md.name, title: md.name, summary: md.description || "", spec };
    if (d.kind === "System") site.add("system", md.name, base);
    else if (d.kind === "Resource") {
      site.add("resource", md.name, { ...base, kind: spec.type || "resource", title: shortTitle(md.description, md.name) });
    } else if (d.kind === "Component") {
      const type = spec.type === "role" ? "role" : spec.lifecycle === "candidate" ? "option" : "component";
      site.add(type, md.name, base);
    }
  }
  // catalog references
  for (const ent of [...site.entities.values()]) {
    const spec = ent.spec || {};
    if (ent.type === "option") for (const r of fills(ent)) refEdge(site, ent, r, "fills");
    if (spec.subcomponentOf) refEdge(site, ent, spec.subcomponentOf, "part-of");
    if (spec.system && ent.type !== "system") refEdge(site, ent, `system:${refName(spec.system)}`, "in-system");
  }

  // claims, and the papers and trials they come from
  for (const { doc, path: rel } of raw) {
    const spec = doc.spec;
    const src = spec.source || {};
    const ours = src.kind === "trial" || src.kind === "probe";
    const c = site.add("claim", doc.metadata.name, {
      doc, spec, source: src, ours, name: doc.metadata.name, path: rel,
      title: doc.metadata.description || spec.claim?.statement || doc.metadata.name,
      summary: spec.claim?.statement || "",
    });
    let from;
    if (ours) {
      const key = String(src.id || doc.metadata.name);
      from = site.add("trial", key, { title: key, summary: src.title || "", url_ext: src.url, family: trialFamily(key), sourceKind: src.kind });
      if (!from.summary && src.title) from.summary = src.title;
    } else {
      const key = sourceKey(src);
      from = site.add("paper", key, { title: src.title || key, summary: "", source: src, url_ext: src.url });
    }
    site.link(c, from, "from");
  }
  for (const c of site.claims) {
    const spec = c.spec;
    refEdge(site, c, spec.about, "about");
    refEdge(site, c, spec.role, "role");
    const cond = spec.conditions || {};
    for (const m of cond.models || []) if (m.ref) refEdge(site, c, m.ref, "measured-on");
    for (const k of ["engine", "dataset", "hardware"]) if (cond[k]?.ref) refEdge(site, c, cond[k].ref, "measured-on");
    (spec.assessments || []).forEach((a, i) => {
      const extra = { i, status: a.status, system: a.system };
      for (const r of a.against || []) refEdge(site, c, r, "assessed-on", extra);
      const t = a.outcome?.trial;
      if (t?.id) {
        const trial = site.add("trial", String(t.id), { title: String(t.id), summary: "", url_ext: t.url, family: trialFamily(t.id) });
        if (!trial.url_ext && t.url) trial.url_ext = t.url;
        site.link(c, trial, "tested-in", extra);
      }
      for (const n of a.outcome?.observed || []) claimEdge(site, c, n, "observed", extra);
      for (const n of a.see_also || []) claimEdge(site, c, n, "see-also", extra);
    });
  }
  // the papers the agent saw (seen.jsonl), for a paper page's date, category and abstract
  const seen = new Map((site.research.seen || []).map((x) => [String(x.id), x]));
  for (const p of site.of("paper")) {
    const id = String(p.source?.id || "").replace(/^arxiv:/i, "");
    if (seen.has(id)) p.seen = seen.get(id);
  }
  return site;
}

function refEdge(site, from, ref, rel, extra) {
  if (!ref) return;
  const to = site.catalogRef(ref);
  if (to) site.link(from, to, rel, extra);
  else site.unresolved.push(`${from.id} ${rel} ${ref}`);
}

function claimEdge(site, from, name, rel, extra) {
  const to = site.claim(name);
  if (to) site.link(from, to, rel, extra);
  else site.unresolved.push(`${from.id} ${rel} claim ${name}`);
}

/** Markdown pages (from the Astro content collection) as entities, with their `refs:` resolved. An unknown ref
 *  stops the build: a page is written by a person, and a broken link there is a mistake to fix. */
export function attachPages(site, pages) {
  for (const p of pages) {
    const ent = site.add("page", p.slug, { title: p.title, summary: p.description || "", kind: p.kind, date: p.date, page: p });
    ent.url = `${p.slug}.html`;
    for (const r of p.refs || []) {
      const to = site.resolve(r);
      if (!to) throw new Error(`build: site/content/${p.slug}.md refers to ${r}, which is not on the site`);
      site.link(ent, to, "mentions");
    }
  }
  site.pages = pages;
  return site;
}

// ---------------------------------------------------------------- data files

export function claimsJson(site) {
  return {
    system: site.system,
    claims: site.sorted().map((c) => ({
      name: c.name, path: c.path, status: site.status(c), statuses: site.statuses(c), date: site.date(c), record: c.doc,
    })),
  };
}

export function graphJson(site) {
  const pairs = site.calibrationPairs();
  return {
    system: site.system,
    nodes: [...site.entities.values()].map((x) => ({ id: x.id, type: x.type, title: x.title, url: x.url, ...(x.kind ? { kind: x.kind } : {}) })),
    edges: site.edges.map((x) => ({ from: x.from.id, to: x.to.id, rel: x.rel, ...(x.status ? { status: x.status } : {}) })),
    claims: Object.fromEntries(site.claims.map((c) => [c.name, { status: site.status(c), statuses: site.statuses(c), status_text: site.statusText(c) }])),
    calibration: {
      pairs: pairs.map((x) => ({ claim: x.claim.name, p: x.p, held: x.held, config: site.configLabel(x.a) })),
      brier: brier(pairs),
    },
    unresolved: site.unresolved,
    index_problems: site.checkIndex(),
  };
}

/** The search index: one row per entity, with the words a search should find it by. */
export function searchJson(site) {
  return [...site.entities.values()].map((x) => {
    const words = [x.key, x.title, x.summary];
    if (x.type === "claim") {
      const cl = x.spec.claim || {};
      words.push(cl.metric, x.source.id, x.source.title, refName(x.spec.about), refName(x.spec.role));
      for (const m of x.spec.conditions?.models || []) words.push(m.name);
    }
    if (x.type === "paper") words.push(x.source?.id);
    const status = x.type === "claim" ? site.statuses(x).join(" ") : "";
    return {
      u: x.url, t: truncate(x.title, 140), k: x.type, ...(x.kind ? { s: x.kind } : {}), ...(status ? { st: status } : {}),
      d: truncate(x.summary, 200), w: words.filter(Boolean).join(" ").toLowerCase(),
    };
  });
}
