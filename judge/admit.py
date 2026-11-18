"""Admission: refuse a change before anything runs unless its card fits the base's policy and every
changed path lies inside both scopes and outside everything protected. A change that touches nothing
in the policy's scope is not judged (see `triage`).

The policy is read from the protected base, never from the change. The changed paths come from git
(`git diff --raw -z --no-renames base...head`), never from the change's own account of itself.
"""

import re
import subprocess

from . import schemas

# Protected whatever the policy says: the forge's workflow files, the judge's own home, git's own
# control files, and the files the Python interpreter runs on its own at start-up.
ALWAYS_PROTECTED = (
    ".github/**", ".gitea/**", ".forgejo/**", ".woodpecker/**", ".woodpecker.yml", ".woodpecker.yaml",
    ".morphogen/**", ".gitattributes", "**/.gitattributes", ".gitmodules", "**/sitecustomize.py",
    "**/usercustomize.py", "**/*.pth",
)
LINK, SUBMODULE = "120000", "160000"


def _glob_re(glob):
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:[^/]+/)*"); i += 3
        elif glob.startswith("**", i):
            out.append(".*"); i += 2
        elif glob[i] == "*":
            out.append("[^/]*"); i += 1
        elif glob[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(glob[i])); i += 1
    return re.compile("".join(out) + r"\Z")


def matches(path, globs):
    return any(_glob_re(g).match(path) for g in globs)


def changes(repo, base, head):
    """Changed paths between the merge base of `base` and `head`, as git records them."""
    raw = subprocess.run(["git", "-C", str(repo), "diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                          f"{base}...{head}"], check=True, capture_output=True).stdout.decode("utf-8", "surrogateescape")
    fields, out = raw.split("\0"), []
    for meta, path in zip(fields[0::2], fields[1::2]):
        if not meta:
            continue
        _, new_mode, _, _, status = meta[1:].split(" ")
        out.append({"path": path, "mode": new_mode, "status": status[0]})
    return out


def check_card(card, policy):
    """Reasons the card does not fit the policy (empty when it does)."""
    reasons = schemas.errors("card", card)
    if reasons:
        return ["card: " + r for r in reasons]
    sets = policy["case_sets"]
    name = card["cases"]["set"]
    if name not in sets:
        return [f"card names case set {name!r}, which the policy does not list"]
    rules = sets[name]
    kpis = {k["name"]: k for k in card["kpis"]}
    if len(kpis) != len(card["kpis"]):
        reasons.append("card lists a KPI twice")
    required = {k["name"]: k for k in rules["required_kpis"]}
    allowed = {k["name"]: k["source"] for k in rules.get("allowed_kpis", [])}
    for n, want in required.items():
        got = kpis.get(n)
        if got is None:
            reasons.append(f"card drops required KPI {n!r}")
            continue
        for field in ("source", "direction"):
            if got[field] != want[field]:
                reasons.append(f"KPI {n!r}: {field} is {got[field]!r}, policy says {want[field]!r}")
        if want["role"] == "decide" and got["role"] != "decide":
            reasons.append(f"KPI {n!r}: policy makes it decide, card makes it {got['role']!r}")
        if got["role"] == "decide" and got["floor"] < want["floor"] and want["role"] == "decide":
            reasons.append(f"KPI {n!r}: floor {got['floor']} is below the policy's {want['floor']}")
        if got["role"] == "bound" and got["floor"] > want["floor"]:
            reasons.append(f"KPI {n!r}: tolerance {got['floor']} is looser than the policy's {want['floor']}")
    for n, got in kpis.items():
        if n in required:
            continue
        if allowed.get(n) != got["source"]:
            reasons.append(f"KPI {n!r} with source {got['source']!r} is not one the policy allows")
    if not any(k["role"] == "decide" for k in card["kpis"]):
        reasons.append("card has no deciding KPI")
    for host in card.get("network", []):
        if host not in policy.get("network", []):
            reasons.append(f"card grants network host {host!r}, which the policy does not allow")
    return reasons


def check_paths(card, policy, changed):
    reasons = []
    protected = list(ALWAYS_PROTECTED) + list(policy["protected"])
    if not changed:
        reasons.append("the change changes nothing")
    for c in changed:
        p = c["path"]
        if c["mode"] == LINK:
            reasons.append(f"{p}: is a symbolic link")
        elif c["mode"] == SUBMODULE:
            reasons.append(f"{p}: is a submodule")
        if matches(p, protected):
            reasons.append(f"{p}: is protected")
        elif not matches(p, card["scope"]):
            reasons.append(f"{p}: is outside the card's scope")
        elif not matches(p, policy["scope"]):
            reasons.append(f"{p}: is outside the policy's scope")
    return reasons


def triage(policy, changed):
    """Is the change judged, and if not, may it pass unjudged? Returns (judged, reasons).

    A change is judged when any changed path lies in the policy's scope (a move out of the scope
    counts: without renames it is a deletion inside it). Any other change passes unjudged, unless it
    touches what the judge relies on (its workflows, its rules, the protected paths, the files the
    interpreter runs by itself) or is a link or submodule: those are refused, because the judge never
    passes a change to its own ground; a person reviews and merges them.
    """
    if any(matches(c["path"], policy["scope"]) for c in changed):
        return True, []
    protected = list(ALWAYS_PROTECTED) + list(policy["protected"])
    reasons = []
    for c in changed:
        p = c["path"]
        if c["mode"] in (LINK, SUBMODULE):
            reasons.append(f"{p}: is a {'symbolic link' if c['mode'] == LINK else 'submodule'}")
        elif matches(p, protected):
            reasons.append(f"{p}: is protected")
    if reasons:
        reasons[0] = "not judged, and it touches what the judge relies on, which is a person's to merge: " + reasons[0]
    return False, reasons


def admit(card, policy, changed):
    """Return the reasons to refuse; an empty list admits the change."""
    schemas.check("policy", policy)
    reasons = check_card(card, policy)
    if reasons:
        return reasons
    return check_paths(card, policy, changed)


CARD_FENCE = re.compile(r"```morphogen-card[ \t]*\r?\n(.*?)\r?\n```", re.S)


def card_from_body(body):
    """The card is the one ```morphogen-card fenced block in the pull request's description."""
    found = CARD_FENCE.findall(body or "")
    if len(found) != 1:
        raise schemas.Invalid(f"the pull request must carry exactly one morphogen-card block, found {len(found)}")
    return schemas.loads_strict(found[0])


def main(argv=None):
    import argparse
    import json
    import os
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Admit a change or refuse it, before anything runs.")
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--policy", required=True, type=Path, help="read from the base checkout")
    ap.add_argument("--body-env", default="PR_BODY", help="environment variable holding the PR description")
    ap.add_argument("--card-out", required=True, type=Path)
    a = ap.parse_args(argv)
    policy = schemas.check("policy", schemas.loads_strict(a.policy.read_text()))
    changed = changes(a.repo, a.base, a.head)
    judged, reasons = triage(policy, changed)
    card = None
    if judged:
        try:
            card = card_from_body(os.environ.get(a.body_env, ""))
        except (schemas.Invalid, ValueError) as e:
            reasons = [str(e)]
        else:
            reasons = admit(card, policy, changed)
    a.card_out.write_text(json.dumps({"card": card, "refused": reasons, "judged": judged}, indent=2))
    print(json.dumps({"judged": judged, "admitted": not reasons, "reasons": reasons}, indent=2))
    return 1 if reasons else 0


if __name__ == "__main__":
    raise SystemExit(main())
