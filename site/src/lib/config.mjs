// The site's config file (site/README.md, "The config file"): which catalog, claims, research and content folders to
// build from, whose system it is, the theme and the navigation. Paths in it are relative to the file. Read by
// astro.config.mjs (base, theme), content.config.mjs (the content folder) and data.mjs (everything else).
//
//   MORPHOGEN_SITE_CONFIG  the config file (default: site/config.toml, Morphogen's own demo)
//   MORPHOGEN_SITE_OUT     where the HTML goes (default: site/_build)
//   MORPHOGEN_SITE_BASE    the path the site is served under, e.g. /research (default: none; links are relative)

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseToml } from "smol-toml";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// site/: astro.config.mjs sets SITE_DIR, since a bundled page no longer sits where this file does.
export const SITE_DIR = process.env.SITE_DIR || path.resolve(HERE, "..", "..");

/** The pages the header can list, by id, in the default order. */
export const NAV_PAGES = {
  claims: ["index.html", "Claims"],
  queue: ["queue.html", "Next to test"],
  predictions: ["predictions.html", "Predictions"],
  roles: ["roles.html", "Roles"],
  map: ["map.html", "Map"],
  notes: ["notes.html", "Notes"],
  search: ["search.html", "Search"],
};
const DEFAULT_NAV = ["claims", "queue", "predictions", "roles", "map", "notes"];
const ACTIONS = ["prioritise", "reject", "dispute", "question", "propose-role", "propose-option"];

/** `/research` -> `/research/`; empty -> "" (relative links). */
export function normalizeBase(base) {
  const b = String(base || "").trim();
  if (!b || b === ".") return "";
  if (/^[a-z][a-z0-9+.-]*:|^\/\//i.test(b) || /["'<>\s\\]/.test(b)) throw new Error(`site: --base must be a path such as /research, not ${b}`);
  return `/${b.replace(/^\/+|\/+$/g, "")}/`.replace(/^\/\/$/, "/");
}

/** The directory holding .git above `dir`, or null. Claim files are linked on GitHub by their path from there. */
function gitRoot(dir) {
  for (let d = path.resolve(dir); ; d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, ".git"))) return d;
    if (path.dirname(d) === d) return null;
  }
}

const list = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

/** Read and check the config file; every path comes back absolute. */
export function loadConfig(file = process.env.MORPHOGEN_SITE_CONFIG || path.join(SITE_DIR, "config.toml")) {
  const config = path.resolve(file);
  if (!fs.existsSync(config)) throw new Error(`site: no config file at ${config} (morphogen site init writes one)`);
  const dir = path.dirname(config);
  const raw = parseToml(fs.readFileSync(config, "utf8"));
  const at = (p) => (p == null || p === "" ? null : path.resolve(dir, String(p)));
  const s = raw.site || {};
  const src = raw.sources || {};
  const theme = raw.theme || {};
  for (const k of ["repo", "system"]) {
    if (!s[k]) throw new Error(`site: ${config} needs [site] ${k} (e.g. ${k === "repo" ? '"you/your-repo"' : '"system:default/yours"'})`);
  }
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(s.repo)) throw new Error(`site: [site] repo must be owner/name, not ${s.repo}`);
  const labels = raw.labels || {};
  for (const k of Object.keys(labels)) {
    if (!ACTIONS.includes(k)) throw new Error(`site: [labels] ${k} is not one of ${ACTIONS.join(", ")}`);
  }
  const nav = list(raw.nav?.pages ?? DEFAULT_NAV).map((x) => {
    const id = typeof x === "string" ? x : x?.page;
    if (!NAV_PAGES[id]) throw new Error(`site: [nav] pages: ${id} is not one of ${Object.keys(NAV_PAGES).join(", ")}`);
    return { id, href: NAV_PAGES[id][0], text: (typeof x === "object" && x.text) || NAV_PAGES[id][1] };
  });
  const files = { css: at(theme.css), logo: at(theme.logo) };
  for (const [k, f] of Object.entries(files)) {
    if (f && !fs.existsSync(f)) throw new Error(`site: [theme] ${k} = ${theme[k]}: no such file`);
  }
  if (files.logo && !/\.(svg|png|webp|jpe?g)$/i.test(files.logo)) throw new Error("site: [theme] logo must be .svg, .png, .webp or .jpg");
  return {
    config,
    // claim files are linked on GitHub by their path from the repository root
    root: at(s.repo_dir) || gitRoot(dir) || dir,
    title: s.title || "Research",
    description: s.description || "Claims from papers about options for the system's roles, with conditions, transfer predictions and outcomes.",
    owner: s.owner || s.repo.split("/")[0],
    repo: s.repo,
    branch: s.branch || "main",
    system: s.system,
    labels,
    sources: {
      claims: list(src.claims).map(at),
      catalog: list(src.catalog).map(at),
      research: at(src.research),
      content: at(src.content),
      schema: at(src.schema) || path.resolve(SITE_DIR, "..", "schemas", "evidence-claim.v1.json"),
    },
    theme: files,
    nav,
    base: normalizeBase(process.env.MORPHOGEN_SITE_BASE),
  };
}

/** The theme's files as they are served: {"theme.css": abs, "logo.svg": abs}, under assets/user/. */
export function themeFiles(theme) {
  const out = {};
  if (theme.css) out["theme.css"] = theme.css;
  if (theme.logo) out[`logo${path.extname(theme.logo).toLowerCase()}`] = theme.logo;
  return out;
}
