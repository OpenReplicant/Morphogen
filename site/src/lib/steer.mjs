// Steering: buttons open a prefilled GitHub new-issue page. Each body ends with the lines the research agent reads
// first (morphogen/research.py, parse_issue): `research-action:`, `system:`, and for a claim `research-claim:`,
// `claim-file:`, `status:` and `p_transfer:`. Only names and paths go in, never text from a paper: an issue body is
// rendered as Markdown, and a paper's words could mention people or carry links.

/** A prefilled new-issue URL. GitHub reads `title`, `body` and comma-separated `labels` from the query. */
export function issueUrl(repo, title, body, labels) {
  const enc = (s) => encodeURIComponent(s).replace(/[!'()*]/g, (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase());
  const repoPath = String(repo).split("/").map(enc).join("/");
  const q = [["title", title], ["body", body]];
  if (labels && labels.length) q.push(["labels", labels.join(",")]);
  return `https://github.com/${repoPath}/issues/new?` + q.map(([k, v]) => `${k}=${enc(v)}`).join("&");
}

/** The body of a steering issue; `claim` is a graph claim entity or null. */
export function issueBody(action, site, claim, extra = []) {
  const lines = [...extra, "", "---", `research-action: ${action}`, `system: ${site.system}`];
  if (claim) {
    lines.push(`research-claim: ${claim.name}`, `claim-file: ${site.fileUrl(claim.path)}`, `status: ${site.statusText(claim)}`);
    const preds = site.predictions(claim);
    if (preds.length === 1) lines.push(`p_transfer: ${preds[0].p_transfer}`);
  }
  return lines.join("\n").trim() + "\n";
}

export function issue(site, action, title, body) {
  return issueUrl(site.repo, title, body, site.labels[action] || []);
}

export const CLAIM_BUTTONS = [
  ["prioritise", "Prioritise", "Test this claim next", ["Please test this claim sooner.", "", "Why it is worth a trial now:", ""]],
  ["reject", "Reject", "Reject it",
    ["Please drop this claim from the queue.", "", "Why (does not apply here, already known, not a real gain):", ""]],
  ["dispute", "Dispute prediction", "Dispute the prediction",
    ["I think the transfer prediction is wrong.", "", "My probability that it holds here:", "", "Which conditions it gets wrong:", ""]],
];

/** The steering buttons for one claim: [action, url, text]. None for a claim of our own. */
export function claimButtons(site, c) {
  if (c.ours) return [];
  return CLAIM_BUTTONS.filter(([action]) => action !== "dispute" || site.predictions(c).length)
    .map(([action, verb, text, extra]) => [action, issue(site, action, `${verb}: ${c.name}`, issueBody(action, site, c, extra)), text]);
}

export function questionUrl(site) {
  return issue(site, "question", "Question to watch: ", issueBody("question", site, null, [
    "What should the research agent look for? A method, a role, an open question from the system's docs.", "",
    "Question:", "", "Why it matters here:", ""]));
}

export function proposeRoleUrl(site) {
  return issue(site, "propose-role", "Role to watch: ", issueBody("propose-role", site, null, [
    "A part of the system the research agent should read papers for.", "", "The part, and what it does:", "",
    "What a better option would improve:", ""]));
}

export function proposeOptionUrl(site, role) {
  return issue(site, "propose-option", `Option to watch for ${role}: `, issueBody("propose-option", site, null, [
    `An option, paper or method the research agent should look at for the role \`${role}\`.`, "",
    "Option or paper:", "", "Why it might help here:", "", `role: ${role}`]));
}
