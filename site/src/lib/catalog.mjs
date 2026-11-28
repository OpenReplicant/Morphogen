// What the catalog page says about an option: its adjustable parameters (a JSON Schema in spec.morphogen.parameters),
// and the figures the compare table sets side by side. Plain JavaScript, so `node --test` reads it too.

const isObj = (v) => v != null && typeof v === "object" && !Array.isArray(v);

/** The properties of a JSON Schema of settings, as rows: name, type, the range or the choices, the default. */
export function parameterRows(schema) {
  const props = isObj(schema) && isObj(schema.properties) ? schema.properties : isObj(schema) ? schema : {};
  const rows = [];
  for (const [name, p] of Object.entries(props)) {
    if (!isObj(p)) continue;
    const lo = p.minimum ?? p.exclusiveMinimum, hi = p.maximum ?? p.exclusiveMaximum;
    const range = lo != null || hi != null ? `${lo ?? "…"} to ${hi ?? "…"}` : "";
    const choices = Array.isArray(p.enum) ? p.enum.map(String).join(" | ") : "";
    rows.push({
      name, type: Array.isArray(p.type) ? p.type.join(" | ") : String(p.type ?? ""), bounds: choices || range,
      default: p.default === undefined ? "" : typeof p.default === "string" ? p.default : JSON.stringify(p.default),
      about: typeof p.description === "string" ? p.description : "",
    });
  }
  return rows;
}

/** The claims about an option that say it is better, worse, or about the same as its baseline: the trade-offs the
 *  papers report, each with the metric. */
export function tradeoffs(site, claims) {
  return site.sorted(claims.filter((c) => !c.ours)).map((c) => {
    const cl = c.spec.claim || {};
    return { claim: c, finding: cl.finding || "none-stated", metric: cl.metric || "", statement: cl.statement || c.title };
  });
}
