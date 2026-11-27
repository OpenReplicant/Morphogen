// Small helpers shared by the data layer and the pages. Plain JavaScript, so `node --test` runs them without Astro.

export const STATUSES = ["untested", "predicted", "replicated", "did-not-transfer", "not-testable"];
export const OBSERVATION = "observation"; // a claim of this system's own (source.kind trial or probe): it has no status
export const MIXED = "mixed"; // a claim whose assessments for the system disagree
export const STATUS_TEXT = {
  untested: "Untested",
  predicted: "Predicted",
  replicated: "Replicated",
  "did-not-transfer": "Did not transfer",
  "not-testable": "Not testable",
  [OBSERVATION]: "Our observation",
  [MIXED]: "Mixed",
};
export const STATUS_HELP = {
  untested: "Catalogued, with the reason it has not been tried here.",
  predicted: "A probability that it holds here was written before any outcome.",
  replicated: "Tried on this system's setup, and the finding held.",
  "did-not-transfer": "Tried on this system's setup, and the finding did not hold.",
  "not-testable": "Cannot be tried here, and why.",
  [OBSERVATION]: "A measurement this system ran itself, which a paper's outcome links to.",
  [MIXED]: "Tried on more than one configuration, with different results.",
};
export const QUOTE_SHORT = { checked: "quote checked", unchecked: "quote unchecked", none: "no quote" };
export const QUOTE_TEXT = {
  checked: "Quote checked against the source",
  unchecked: "Quote copied, not yet checked",
  none: "No verbatim quote taken",
};

/** The URL if it is http(s) with a host, else null: a file must not be able to write a javascript: link. */
export function safeUrl(url) {
  if (typeof url !== "string") return null;
  const s = url.trim();
  if (!/^https?:\/\//i.test(s)) return null;
  let parts;
  try {
    parts = new URL(s);
  } catch {
    return null;
  }
  if ((parts.protocol !== "http:" && parts.protocol !== "https:") || !parts.host) return null;
  return s;
}

/** `component:default/decision-backend` -> `decision-backend`. */
export function refName(ref) {
  if (!ref) return "";
  const s = String(ref);
  const afterKind = s.includes(":") ? s.slice(s.indexOf(":") + 1) : s;
  return afterKind.includes("/") ? afterKind.slice(afterKind.indexOf("/") + 1) : afterKind;
}

/** `component:default/x` -> `component`; a bare name has no kind. */
export function refKind(ref) {
  const s = String(ref || "");
  const i = s.indexOf(":");
  return i > 0 && !s.slice(0, i).includes("/") ? s.slice(0, i).toLowerCase() : "";
}

/** A file-name-safe slug: lower case, runs of anything but letters, digits, dots and dashes become one dash. */
export function slugify(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9.\-]+/g, "-")
    .replace(/\.{2,}/g, ".")
    .replace(/^[-.]+|[-.]+$/g, "") || "x";
}

export function truncate(text, n) {
  const s = String(text ?? "").split(/\s+/).filter(Boolean).join(" ");
  return s.length <= n ? s : s.slice(0, n - 1).trimEnd() + "…";
}

export function fmtNumber(value) {
  if (value === null || value === undefined) return "not stated";
  if (typeof value === "object") {
    const over = value.over ? ` over ${value.over}` : "";
    return `${value.min} to ${value.max}${over}`;
  }
  return String(value);
}

export function fmtInterval(iv) {
  if (!iv) return "";
  const how = [iv.level ? `${Math.round(iv.level * 100)}%` : "", iv.method || ""].filter(Boolean).join(", ");
  return `[${iv.low}, ${iv.high}]` + (how ? ` (${how})` : "");
}

/** One measure as [label, value] rows. */
export function measureRows(m) {
  const better = { higher: "higher is better", lower: "lower is better" }[m.better || ""] || "";
  const unit = m.unit ? ` ${m.unit}` : "";
  const hasValue = m.value !== null && m.value !== undefined;
  const value = fmtNumber(m.value) + (hasValue ? unit : "");
  const rows = [["Metric", (m.metric || "") + (better ? ` (${better})` : "")]];
  rows.push(["Value", value + (m.interval ? " " + fmtInterval(m.interval) : "")]);
  if (m.where) rows.push(["Where", m.where]);
  const b = m.baseline;
  if (b) {
    const bval = b.value === null || b.value === undefined ? "" : `: ${fmtNumber(b.value)}`;
    rows.push(["Against", `${b.name || ""}${bval}` + (b.interval ? " " + fmtInterval(b.interval) : "")]);
  }
  return rows;
}

/** A value from a file as display text (objects as compact JSON). */
export function asText(v) {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v);
}

/** `stated | repo@commit:path | "quote"` lines -> [source, quote]. */
export function parseEvidence(annotation) {
  const out = [];
  for (const line of String(annotation || "").split("\n")) {
    const i = line.indexOf("|");
    const j = i < 0 ? -1 : line.indexOf("|", i + 1);
    if (i < 0 || j < 0) continue;
    out.push([line.slice(i + 1, j).trim(), line.slice(j + 1).trim().replace(/^"+|"+$/g, "")]);
  }
  return out;
}

/** `../` repeated once per directory below the site root, for relative links (the site may live under /Repo/). */
export function up(depth) {
  return "../".repeat(depth);
}
