"""Improvement strategies: the catalog, the archive they search, their payoff, and auto selection.

A strategy only proposes: where the next candidate starts (parent), what to
try (candidates), and what to remember (after). It never changes the judge,
the budgets, or the adoption rule (a candidate is merged only after it passes
the judge against the trunk and the operator approves).

Cards are Markdown files with YAML front matter, shipped in the plugin's
`strategies/` directory. A project can add or override cards in its own
`strategies/` directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import documents
from .config import plugin_root

PREFERENCE = ("hill-climb", "archive-search")  # order auto tries before stopping
STALL_TRIALS = 4  # this many verdicts in a row without a pass means a strategy has stalled
SIMPLIFY_MIN_LINES = 20


def _card(path: Path) -> dict:
    return documents.load("strategy", path)


def catalog(root: Path) -> dict[str, dict]:
    """Strategy cards: the plugin's, then the project's (which win on name clashes)."""
    cards: dict[str, dict] = {}
    for d in (plugin_root() / "strategies", root / "strategies"):
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                c = _card(f)
                if c:
                    cards[c["name"]] = c
    return cards


def _primary_gain(outcome: dict) -> float | None:
    for m in (outcome.get("metrics") or {}).values():
        if m.get("primary"):
            return m.get("gain")
    return None


def archive(evidence, target: str) -> list[dict]:
    """Every judged variant of `target`, oldest first, with lineage and labels."""
    want = target.rstrip("/")
    out = []
    for r in evidence.dump():
        if r.get("by") != "judge" or r.get("kind") != "verdict":
            continue
        subj = r.get("subject") or {}
        if want not in (subj.get("path"), subj.get("system")):
            continue
        labels = r.get("labels") or {}
        out.append({
            "seq": r["seq"], "at": r.get("at"), "verdict": r.get("verdict"),
            "base": r["refs"]["base"], "candidate": r["refs"]["candidate"],
            "gain": _primary_gain(r.get("outcome") or {}),
            "strategy": labels.get("strategy", "unlabelled"),
            "approach": labels.get("approach"), "family": labels.get("family"),
            "parent": labels.get("parent"),
            "trust": r.get("trust"), "interface": r.get("interface", "direct"),
            "reasons": r.get("outcome", {}).get("forbidden") or None,
        })
    return out


def children(variants: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in variants:
        counts[v["base"]] = counts.get(v["base"], 0) + 1
    return counts


def payoff(variants: list[dict]) -> dict[str, dict]:
    """Per strategy: trials, passes, and total primary gain of passes per trial."""
    table: dict[str, dict] = {}
    for v in variants:
        t = table.setdefault(v["strategy"], {"trials": 0, "passes": 0, "gain_sum": 0.0})
        t["trials"] += 1
        if v["verdict"] == "pass":
            t["passes"] += 1
            t["gain_sum"] += v["gain"] or 0.0
    for t in table.values():
        t["gain_per_trial"] = round(t["gain_sum"] / t["trials"], 4) if t["trials"] else 0.0
        t["gain_sum"] = round(t["gain_sum"], 4)
    return table


def stalled(variants: list[dict], strategy: str) -> bool:
    mine = [v for v in variants if v["strategy"] == strategy]
    tail = mine[-STALL_TRIALS:]
    return len(tail) >= STALL_TRIALS and not any(v["verdict"] == "pass" for v in tail)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _merged(repo: Path, commit: str, trunk: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", commit, trunk).returncode == 0


def _diff_lines(repo: Path, base: str, cand: str, rel: str) -> int:
    p = _git(repo, "diff", "--numstat", base, cand, "--", rel)
    total = 0
    for line in p.stdout.splitlines():
        a, d, _ = (line.split("\t") + ["", "", ""])[:3]
        total += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    return total


def choose(root: Path, cfg: dict, evidence, target: str) -> dict:
    """Pick the strategy for the next round on `target`, with the reason."""
    cards = catalog(root)
    variants = archive(evidence, target)
    pay = payoff(variants)
    setting = (cfg.get("strategies") or {}).get(target) or cfg.get("strategy", "auto")

    def pick(name: str, reason: str) -> dict:
        card = cards.get(name)
        return {"strategy": name, "reason": reason, "card": card["body"] if card else None,
                "available": sorted(cards), "payoff": pay, "recent": variants[-8:]}

    if setting != "auto":
        if setting not in cards:
            return pick(setting, f"set in morphogen.yaml, but there is no card named {setting!r}")
        return pick(setting, "set in morphogen.yaml")
    if not variants:
        return pick("hill-climb", "no trials on this target yet")

    repo = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip() or root)
    trunk = cfg.get("trunk", "main")
    rel = str((root / target).resolve().relative_to(repo.resolve()))
    simplified = {v["parent"] for v in variants if v["strategy"] == "simplify" and v["parent"]}
    for v in reversed(variants):
        if v["verdict"] != "pass" or v["strategy"] == "simplify" or any(v["candidate"].startswith(p) for p in simplified):
            continue
        if _merged(repo, v["candidate"], trunk):
            continue
        lines = _diff_lines(repo, v["base"], v["candidate"], rel)
        if lines > SIMPLIFY_MIN_LINES and "simplify" in cards:
            return pick("simplify", f"pass {v['candidate'][:12]} changes {lines} lines and has not been "
                                    "simplified; a smaller version may clear the same bar")
        break

    live = [s for s in PREFERENCE if s in cards and not stalled(variants, s)]
    if not live:
        return pick("stop", f"{' and '.join(PREFERENCE)} have each gone {STALL_TRIALS} trials without a pass; "
                            "report to the operator, or add a strategy card")
    tried = [s for s in live if pay.get(s, {}).get("trials", 0) >= STALL_TRIALS]
    if len(tried) >= 2:
        best = max(tried, key=lambda s: pay[s]["gain_per_trial"])
        return pick(best, f"best gain per trial so far ({pay[best]['gain_per_trial']:+.1%}) among strategies "
                          "that have not stalled")
    if live[0] != PREFERENCE[0]:
        return pick(live[0], f"{PREFERENCE[0]} has gone {STALL_TRIALS} trials without a pass")
    return pick(live[0], "the default first choice; it has not stalled")
