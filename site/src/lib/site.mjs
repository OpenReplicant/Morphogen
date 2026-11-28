// The Astro side of the data layer: the graph from data.mjs, with the Markdown pages of the `pages` collection
// attached so every entity a page names links back to it. Built once per build (again on every request in dev, so
// an edited YAML file shows on reload).
import { getCollection } from "astro:content";
import { attachPages, loadSite } from "./data.mjs";

const RESERVED = new Set(["index", "queue", "predictions", "roles", "map", "catalog", "optimise", "search", "notes", "404"]);
let cached = null;
let warned = false;

export async function getSite() {
  if (cached && import.meta.env.PROD) return cached;
  const site = loadSite();
  const entries = await getCollection("pages", (e) => !e.data.draft);
  for (const e of entries) {
    if (RESERVED.has(e.id)) throw new Error(`build: ${e.id}.md in the content folder would replace the generated ${e.id}.html`);
  }
  attachPages(site, entries.map((e) => ({ ...e.data, slug: e.id, entry: e })));
  if (!warned) {
    for (const w of [...site.warnings, ...site.unresolved.map((u) => `unresolved reference: ${u}`), ...site.checkIndex()]) {
      console.warn(`build: ${w}`);
    }
    warned = true;
  }
  cached = site;
  return site;
}
