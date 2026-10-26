"""Mutants runtime-quadlet must fail (kernel/contract/mutants.py, `sh morphogen/contract/run.sh --mutants`): the runtime
case set kills those that change what reaches the engine; its own tests (`"own"`) those the stub's model cannot see
(quoting, `%`, starting the units, a removed service). The loop every runtime shares is morphogen.runtime: a few of its
mutants are made in this provider's process (`lib`), to show this provider runs through it."""
from pathlib import Path

M = "runtime_quadlet/__main__.py"
LIB = Path(__file__).resolve().parents[3] / "src" / "morphogen" / "runtime.py"
ANCHOR = "from morphogen import runtime\n"


def lib(*edits: tuple[str, str]) -> list:
    """An edit of this provider that re-runs morphogen.runtime's source, with `edits` made, into the module it imports."""
    src = LIB.read_text()
    for old, _ in edits:
        assert src.count(old) == 1, old
    return [(ANCHOR, ANCHOR + f"_s = open(runtime.__file__).read()\nfor _o, _n in {list(edits)!r}:\n    _s = _s.replace(_o, _n)\n"
                              "exec(compile(_s, runtime.__file__, 'exec'), runtime.__dict__)\n")]


MUTANTS = [
    ("the units are rendered from the file the system ran before", M, [(
        "            units = render(project, text)", "            units = render(project, before or text)")]),
    ("a service's environment is left out", M, [(
        """            container.append(f"Environment={quote(f'{k}={v}')}")""", """            pass""")]),
    ("a service joins the host's network", M, [('f"Network={project}.network"', '"Network=host"')]),
    ("a key the file does not have reaches the unit", M, [(
        'f"NetworkAlias={name}"]', 'f"NetworkAlias={name}", "AddCapability=ALL"]')]),
    ("values are not quoted for systemd", M, [(
        """    return '"' + s.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"').replace("%", "%%") + '"'""",
        """    return s""")], "own"),
    ("% is not doubled", M, [('    return s.replace("%", "%%")', '    return s')], "own"),
    ("a raw key is quoted (the quotes stay in the value)", M, [(
        """container.append(f"WorkingDir={raw(svc['working_dir'])}")""",
        """container.append(f"WorkingDir={quote(svc['working_dir'])}")""")], "own"),
    ("the units are installed but not started", M, [(
        """        return self.run("systemctl", *user, "restart", """, """        return out or self.run("systemctl", *user, "restart", """)], "own"),
    ("a service the new file no longer has keeps running", M, [("        if gone:", "        if False:")], "own"),
    ("a removed system is stopped", M, [("""        try:
            units = render(project, text)""", """        if text is None:
            return self.run("podman", "quadlet", "rm", "--force", "--recursive", project)
        try:
            units = render(project, text)""")] + lib((
        """                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")""",
        """                self.engine.apply(self.project, None, None)
                self.say(event="unmanaged", reason="no compose file at HEAD: the system is left as it runs")"""))),
    ("the work tree is read, not HEAD (the shared loop)", M, lib(("""    out = subprocess.run(["git", "-C", str(intent), "show", f"HEAD:./systems/{system}/compose.yaml"], capture_output=True)
    return out.stdout if out.returncode == 0 else None""", """    f = intent / "systems" / system / "compose.yaml"
    return f.read_bytes() if f.exists() else None"""))),
    ("an unapproved file runs (the shared loop)", M, lib(("""        if approved is None:
            return self.refuse(digest, "no approved plan step authorises this file: it was not approved as it is")""",
                                                         """        if approved is None:
            approved = {"decided_at": record["floor"].get(self.name) or __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").timezone.utc), "step": None, "claims": []}"""))),
    ("depends_on may name anything (the shared allow list)", M, lib(('        if names is None or not all(isinstance(d, str) and d in doc["services"] and d != name for d in names):', '        if names is None:'))),
    ("render does not check depends_on names", M, [("""            if not isinstance(dep, str) or not runtime.NAME.fullmatch(dep) or dep not in services:""",
                                                    """            if False:""")], "own"),
    ("% in an image reference is not doubled", M, [("""[f"Image={raw(svc['image'])}",""", """[f"Image={svc['image']}",""")], "own"),
    ("a malformed file raises out of the engine (the loop must survive it)", M, [("""        except Exception as e:                    # anything the file cannot become is this system's failure""",
                                                                                  """        except ValueError as e:""")], "own"),
]
