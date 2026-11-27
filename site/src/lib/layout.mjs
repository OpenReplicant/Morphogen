// The map's layout, computed at build time: one column per kind of entity, nodes ordered within a column by the
// mean position of their neighbours (a few sweeps of the barycentre heuristic), edges drawn as curves. The page is
// a plain SVG of links, so it works without JavaScript; assets/site.js only adds highlighting and filters.
import { truncate } from "./text.mjs";

export const COLUMNS = [
  { key: "resources", label: "Models and setup", types: ["resource"] },
  { key: "sources", label: "Papers and trials", types: ["paper", "trial"] },
  { key: "claims", label: "Claims", types: ["claim"] },
  { key: "options", label: "Options", types: ["option", "component"] },
  { key: "roles", label: "Roles", types: ["role", "system"] },
];

const OUTCOME = new Set(["replicated", "did-not-transfer", "not-testable"]);

/** Which references the map draws: where a claim comes from, what it is about, what it was tested in and on (only
 *  assessments with a result, or every claim would point at every model), and how options and roles fit. */
export function mapEdges(site) {
  return site.edges.filter((e) => {
    if (["from", "about", "fills", "part-of", "tested-in", "measured-on"].includes(e.rel)) return true;
    if (e.rel === "assessed-on") return OUTCOME.has(e.status);
    return false;
  });
}

export function layout(site, { colWidth = 230, rowHeight = 22, top = 40, nodeWidth = 180 } = {}) {
  const edges = mapEdges(site);
  const cols = COLUMNS.map((c) => ({ ...c, nodes: [] }));
  const colOf = new Map();
  for (const ent of site.entities.values()) {
    const i = cols.findIndex((c) => c.types.includes(ent.type));
    if (i < 0) continue;
    cols[i].nodes.push(ent);
    colOf.set(ent.id, i);
  }
  const drawn = edges.filter((e) => colOf.has(e.from.id) && colOf.has(e.to.id) && e.from !== e.to);
  const nbrs = new Map();
  for (const e of drawn) {
    for (const [a, b] of [[e.from.id, e.to.id], [e.to.id, e.from.id]]) {
      if (!nbrs.has(a)) nbrs.set(a, new Set());
      nbrs.get(a).add(b);
    }
  }
  // start: claims by role then option, others by type then name
  for (const c of cols) c.nodes.sort((a, b) => (a.type + (a.spec?.role || "") + (a.spec?.about || "") + a.key).localeCompare(b.type + (b.spec?.role || "") + (b.spec?.about || "") + b.key));
  const pos = new Map();
  const index = () => cols.forEach((c) => c.nodes.forEach((n, i) => pos.set(n.id, i / Math.max(1, c.nodes.length - 1))));
  index();
  const order = [2, 1, 3, 0, 4, 2, 1, 3, 0, 4, 2];
  for (const ci of order) {
    const c = cols[ci];
    const bary = (n) => {
      const ns = [...(nbrs.get(n.id) || [])].filter((x) => pos.has(x));
      return ns.length ? ns.reduce((s, x) => s + pos.get(x), 0) / ns.length : pos.get(n.id);
    };
    const keyed = c.nodes.map((n) => [bary(n), n]);
    keyed.sort((a, b) => a[0] - b[0]);
    c.nodes = keyed.map((x) => x[1]);
    index();
  }
  const height = top + Math.max(...cols.map((c) => c.nodes.length)) * rowHeight + 20;
  const nodes = [];
  const at = new Map();
  cols.forEach((c, ci) => {
    const offset = top + ((height - top - 20) - c.nodes.length * rowHeight) / 2;
    c.x = 10 + ci * colWidth;
    c.nodes.forEach((n, i) => {
      const y = offset + i * rowHeight;
      const node = { ent: n, x: c.x, y, w: nodeWidth, h: rowHeight - 6, label: truncate(n.type === "claim" ? n.key : n.title, 26) };
      nodes.push(node);
      at.set(n.id, node);
    });
  });
  const seen = new Set();
  const paths = [];
  for (const e of drawn) {
    const a = at.get(e.from.id), b = at.get(e.to.id);
    const k = `${e.from.id}|${e.to.id}|${e.rel}`;
    if (seen.has(k)) continue;
    seen.add(k);
    const [l, r] = a.x <= b.x ? [a, b] : [b, a];
    let d;
    if (l.x === r.x) {
      const x0 = l.x + l.w, y0 = l.y + l.h / 2, y1 = r.y + r.h / 2;
      d = `M${x0} ${y0.toFixed(1)} C${x0 + 30} ${y0.toFixed(1)} ${x0 + 30} ${y1.toFixed(1)} ${x0} ${y1.toFixed(1)}`;
    } else {
      const x0 = l.x + l.w, y0 = l.y + l.h / 2, x1 = r.x, y1 = r.y + r.h / 2, mx = (x0 + x1) / 2;
      d = `M${x0} ${y0.toFixed(1)} C${mx.toFixed(1)} ${y0.toFixed(1)} ${mx.toFixed(1)} ${y1.toFixed(1)} ${x1} ${y1.toFixed(1)}`;
    }
    paths.push({ d, from: e.from.id, to: e.to.id, rel: e.rel, status: e.status || "" });
  }
  return { width: 10 + (cols.length - 1) * colWidth + nodeWidth + 10, height, cols, nodes, paths };
}
