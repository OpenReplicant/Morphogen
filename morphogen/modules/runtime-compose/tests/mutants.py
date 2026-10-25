"""Mutants the runtime slot's case set (morphogen/contract/slots/runtime) must kill (kernel/contract/mutants.py,
`sh morphogen/contract/run.sh --mutants`). Which steps count as approved (a person, the review lane, the reader's
clearance) is the store's and morphogen.plans', which no mutant of this provider reaches; the mutants that trust what
an agent wrote put back, inside this provider, the holes the review of R5-44 found."""
M = "runtime_compose/__main__.py"
CALL = 'approved = plans.approval(record["steps"], record["labels"], ACTIONS, self.name, text, base)'


def fallback(cond: str) -> list:
    """The runtime also accepts a file when an approved step meets `cond` (s: the step, sha: the file's sha256)."""
    return [(CALL, CALL + "\n        approved = approved or next(({'decided_at': s['decided_at'], 'step': s['step'], 'claims': s['claims']}"
                          " for s in record['steps'] if s['approved'] and plans.system_of(s['target']) == self.name and ("
                          + cond + ")), None)")]


MUTANTS = [
    ("the step's own hash is trusted (node steps)", M, fallback("s.get('file_sha256') == sha")),
    ("a step on a system counts without its label showing the file", M, fallback("s['value'] == sha")),
    ("any action counts as on the fixed list", M, [(CALL, CALL.replace(
        "ACTIONS,", '{s["action"]: ACTIONS["urn:kk:action:set-random-delay-max"] for s in record["steps"]},'))]),
    ("an approval for any system counts", M, [(CALL, CALL.replace("self.name, text", "plans.system_of(next((s['target'] for s in record['steps'] if s['approved'] and s['value'] == sha), '')) or self.name, text"))]),
    ("the floor counts only files whose approval is still current", M, [(
        "        if at:", "        if at and any(s['approved'] and sha in (s['value'], s.get('file_sha256')) for s in found):")]),
    ("the work tree is read, not HEAD", M, [("""    out = subprocess.run(["git", "-C", str(intent), "show", f"HEAD:./systems/{system}/compose.yaml"], capture_output=True)
    return out.stdout if out.returncode == 0 else None""", """    f = intent / "systems" / system / "compose.yaml"
    return f.read_bytes() if f.exists() else None""")]),
    ("an older approved file runs again", M, [("""if approved["decided_at"] < record["floor"].get(self.name, approved["decided_at"]):""",
                                               """if False:""")]),
    ("the allow list is not applied", M, [("""        why = refusal(text.decode("utf-8", "replace"))
        if why:""", """        why = None
        if why:""")]),
    ("a removed system is stopped", M, [("""                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")""",
                                         """                compose(self.project, Path(tempfile.mkdtemp()), "down")
                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")""")]),
    ("the run does not record the file applied", M, [("""**({"error": error} if error else {"applied": sha})""",
                                                      """**({"error": error} if error else {})""")]),
    ("an unapproved file runs", M, [("""        if approved is None:
            return self.refuse(digest, "no approved plan step authorises this file: it was not approved as it is")""",
                                     """        if approved is None:
            approved = {"decided_at": record["floor"].get(self.name) or __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").timezone.utc), "step": None, "claims": []}""")]),
]
