"""Mutants the runtime slot's case set (morphogen/contract/slots/runtime) must kill (kernel/contract/mutants.py,
`sh morphogen/contract/run.sh --mutants`). Which steps count as approved (a person, the review lane, the reader's
clearance) is the store's and morphogen.plans', which no mutant of this provider reaches; the mutants that trust what
an agent wrote put back the holes the review of R5-44 found. The loop every runtime shares is morphogen.runtime: its
mutants are made in this provider's process (`lib`), so the case set judges them through this provider's engine."""
from pathlib import Path

M = "runtime_compose/__main__.py"
LIB = Path(__file__).resolve().parents[3] / "src" / "morphogen" / "runtime.py"
ANCHOR = "from morphogen import runtime\n"
CALL = 'approved = plans.approval(record["steps"], record["labels"], ACTIONS, self.name, text, base)'


def lib(*edits: tuple[str, str]) -> list:
    """An edit of this provider that re-runs morphogen.runtime's source, with `edits` made, into the module it imports."""
    src = LIB.read_text()
    for old, _ in edits:
        assert src.count(old) == 1, old
    return [(ANCHOR, ANCHOR + f"_s = open(runtime.__file__).read()\nfor _o, _n in {list(edits)!r}:\n    _s = _s.replace(_o, _n)\n"
                              "exec(compile(_s, runtime.__file__, 'exec'), runtime.__dict__)\n")]


def fallback(cond: str) -> list:
    """The runtime also accepts a file when an approved step meets `cond` (s: the step, sha: the file's sha256)."""
    return lib((CALL, CALL + "\n        approved = approved or next(({'decided_at': s['decided_at'], 'step': s['step'], 'claims': s['claims']}"
                            " for s in record['steps'] if s['approved'] and plans.system_of(s['target']) == self.name and ("
                            + cond + ")), None)"))


MUTANTS = [
    ("the step's own hash is trusted (node steps)", M, fallback("s.get('file_sha256') == sha")),
    ("a step on a system counts without its label showing the file", M, fallback("s['value'] == sha")),
    ("any action counts as on the fixed list", M, lib((CALL, CALL.replace(
        "ACTIONS,", '{s["action"]: ACTIONS["urn:kk:action:set-random-delay-max"] for s in record["steps"]},')))),
    ("an approval for any system counts", M, lib((CALL, CALL.replace("self.name, text", "plans.system_of(next((s['target'] for s in record['steps'] if s['approved'] and s['value'] == sha), '')) or self.name, text")))),
    ("the floor counts only files whose approval is still current", M, lib((
        "        if at:", "        if at and any(s['approved'] and sha in (s['value'], s.get('file_sha256')) for s in found):"))),
    ("the work tree is read, not HEAD", M, lib(("""    out = subprocess.run(["git", "-C", str(intent), "show", f"HEAD:./systems/{system}/compose.yaml"], capture_output=True)
    return out.stdout if out.returncode == 0 else None""", """    f = intent / "systems" / system / "compose.yaml"
    return f.read_bytes() if f.exists() else None"""))),
    ("an older approved file runs again", M, lib(("""if approved["decided_at"] < record["floor"].get(self.name, approved["decided_at"]):""",
                                                  """if False:"""))),
    ("the allow list is not applied", M, lib(("""        why = refusal(text.decode("utf-8", "replace"))
        if why:""", """        why = None
        if why:"""))),
    ("a removed system is stopped", M, [("""        with tempfile.TemporaryDirectory(prefix="kk-compose-") as d:""",
                                         """        if text is None:
            return compose(project, Path(tempfile.mkdtemp()), "down")
        with tempfile.TemporaryDirectory(prefix="kk-compose-") as d:""")] + lib((
        """                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")""",
        """                self.engine.apply(self.project, None, None)
                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")"""))),
    ("the run does not record the file applied", M, lib(("""**({"error": error} if error else {"applied": sha})""",
                                                         """**({"error": error} if error else {})"""))),
    ("an unapproved file runs", M, lib(("""        if approved is None:
            return self.refuse(digest, "no approved plan step authorises this file: it was not approved as it is")""",
                                        """        if approved is None:
            approved = {"decided_at": record["floor"].get(self.name) or __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").timezone.utc), "step": None, "claims": []}"""))),
    ("compose is handed another file than the approved one", M, [("""            (workdir / "compose.yaml").write_bytes(text)""",
                                                                  """            (workdir / "compose.yaml").write_bytes(before or text)""")]),
    ("depends_on may name anything (the shared allow list)", M, lib(('        if names is None or not all(isinstance(d, str) and d in doc["services"] and d != name for d in names):', '        if names is None:'))),
]
