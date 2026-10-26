"""The runtime slot's own runner (set.yaml `runner:`): one provider, a record, an intent repository and a stub engine;
the provider's service runs once after each step, and what reached the engine is judged. Prints "ok: <case id>" per
passing case. Never imports the provider.

What reached the engine is every file named in its arguments, read as the engine reads it (`model`): a compose file,
or a `.quadlets` bundle of Quadlet units (a container unit per service, a network). Either becomes the same model:
per service by name, its image, environment, command, entrypoint, ports, labels, working directory, user, depends_on
and restart, plus any other top-level key of a compose file. A unit key the runner does not map back (AddCapability,
Volume, PodmanArgs, Wants, a network of the host, a unit name not the system's own, ...) stays in the model under its
own name, so it never equals an approved file's. Health checks, which run inside the container, are not judged.

  python3 runner.py <provider directory>
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "kernel" / "contract" / "slots"))
from harness import Record, check, meta  # noqa: E402

C = "urn:kk:contract:runtime/"
SOSA, PPLAN = "http://www.w3.org/ns/sosa/", "http://purl.org/net/p-plan#"
RDF_TYPE, DCT_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://purl.org/dc/terms/type"
CHECKSUM = "http://spdx.org/rdf/terms#checksumValue"
IMAGE = "redis:7.4.2-alpine@sha256:" + "1" * 64
OTHER = "redis:7.4.2-alpine@sha256:" + "2" * 64
NODE_ACTION = "urn:kk:action:set-random-delay-max"     # on Morphogen's fixed list: applies to a node, PODINFO_RANDOM_DELAY_MAX
ENGINES = ("docker", "podman", "systemctl", "kubectl", "nomad")
STUB = """#!{python}
# A stub engine for the runtime contract: logs what it is asked to do, and every file it is handed, then succeeds.
import json, os, sys
args = sys.argv[1:]
files = {{}}
for a in args:
    if os.path.isfile(a):
        try:
            files[a] = open(a).read()
        except OSError:
            files[a] = None
with open({log!r}, "a") as out:
    out.write(json.dumps({{"engine": {name!r}, "args": args, "files": files}}) + "\\n")
"""


def compose(env: str = "600", extra: str = "", image: str = IMAGE) -> str:
    return (f"services:\n  web:\n    image: {image}\n{extra}    environment:\n      PODINFO_RANDOM_DELAY_MAX: \"{env}\"\n"
            f"  cache:\n    image: {IMAGE}\n")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=someone", "-c", "user.email=someone@example.invalid",
                           *args], check=True, capture_output=True, text=True).stdout


class World:
    def __init__(self, provider: Path, rec: Record, tmp: Path):
        self.provider, self.rec, self.tmp = provider, rec, tmp
        self.intent, self.log = tmp / "intent", tmp / "engine.log"
        self.bin = tmp / "bin"
        self.bin.mkdir()
        for name in ENGINES:
            f = self.bin / name
            f.write_text(STUB.format(python=sys.executable, log=str(self.log), name=name))
            f.chmod(0o755)
        self.intent.mkdir()
        git(self.intent, "init", "-q")
        self.seen, self.n = 0, 0
        self.proposer = rec.agent("kkc_rt_proposer", "urn:kk:agent:contract-proposer")
        self.person = rec.agent("kkc_rt_person", "urn:kk:agent:contract-person", kind="person", grants=("kk_agent", "kk_reviewer"))

    def commit(self, system: str, text: str | None, add: bool = True) -> None:
        f = self.intent / "systems" / system / "compose.yaml"
        if text is None:
            git(self.intent, "rm", "-q", str(f.relative_to(self.intent)))
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
            if not add:
                return
            git(self.intent, "add", "-A")
        git(self.intent, "commit", "-qm", f"{system} by someone")

    def propose(self, target: str, value=None, file_sha: str | None = None, scope: str = "urn:kk:scope:default",
                shows: str | None = None, action: str | None = None) -> str:
        """A plan with one step on `target`, in the review lane, its label showing `shows` (a step on a system shows
        the file it names); returns its change set id."""
        self.n += 1
        plan = f"urn:kk:plan:contract-runtime-{self.n}"
        step = f"{plan}:step:1"
        def c(s, p, o, q=None):
            op = {"op": "add_claim", "subject": s, "predicate": p, "object": o, "evidence_type": "testimony",
                  "references": [{"source_uri": f"urn:test:{plan}"}]}
            return {**op, "qualifiers": q} if q else op
        result = {"value": {"@value": value}}
        action = action or (NODE_ACTION if target.startswith("urn:kk:node:") else "urn:kk:action:adopt-system")
        ops = [c(plan, RDF_TYPE, {"entity": PPLAN + "Plan"}), c(step, RDF_TYPE, {"entity": SOSA + "Actuation"}),
               c(plan, "http://www.w3.org/2000/01/rdf-schema#label", {"value": {"@value": f"Run {target}:\n\n{shows or ''}"}}),
               c(step, PPLAN + "isStepOfPlan", {"entity": plan}), c(step, DCT_TYPE, {"entity": action}),
               c(step, SOSA + "hasFeatureOfInterest", {"entity": target}),
               c(step, SOSA + "hasSimpleResult", result, {CHECKSUM: file_sha} if file_sha else None)]
        return self.rec.submit(self.proposer, ops, scope=scope, lane="review")["id"]

    def withdraw(self, cs: str) -> None:
        """The proposer deprecates every claim its change set `cs` recorded (an agent may withdraw its own step)."""
        ids = [str(r["id"]) for r in self.rec.rows("select id from kernel.claim where change_set = %s", (cs,))]
        self.rec.submit(self.proposer, [{"op": "set_status", "claim": i, "status": "deprecated", "reason": "retracted"} for i in ids])

    def approve(self, cs: str) -> None:
        with self.rec.connect(self.person) as conn:
            conn.execute("select api.review(%s, true, 'contract case')", (cs,))

    def env(self, stub: bool = True) -> dict:
        """The provider's environment, but for its login: the stub engine first on PATH (stub=False: the real one)."""
        return {"PATH": os.pathsep.join([str(self.bin)] * stub + [os.environ.get("PATH", "")]), "HOME": str(self.tmp),
                "PYTHONPATH": os.pathsep.join([str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"), str(self.provider)]),
                "KK_INTENT_DIR": str(self.intent),
                "DOCKER_HOST": "unix:///nonexistent" if stub else os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")}

    def run(self) -> tuple[list[dict], list[dict]]:
        """One pass of the provider; (the engine calls it made, the events it printed)."""
        out = self.rec.service_once(self.provider, args=("--intent", str(self.intent), "--all"), env=self.env())
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        calls, self.seen = [json.loads(x) for x in lines[self.seen:]], len(lines)
        events = [json.loads(x) for x in out.stdout.splitlines() if x.startswith("{")]
        return calls, events


def ran(calls: list[dict]) -> list[str]:
    """What the engine was asked to run (compose up, podman quadlet install, ...), each file as a model."""
    return [model(t) for c in calls if not stops(c) for t in c["files"].values() if t]


UNJUDGED = {"HealthCmd", "HealthInterval", "HealthRetries", "HealthTimeout", "HealthStartPeriod"}   # run inside the container
MAPPED = {"Image": "image", "Exec": "command", "Entrypoint": "entrypoint", "PublishPort": "ports",
          "Environment": "environment", "Label": "labels", "WorkingDir": "working_dir", "User": "user"}
RESTART = {"always": "always", "unless-stopped": "always", "on-failure": "on-failure", "no": "no"}


def unquote(value: str) -> list[str]:
    """The words of a setting Quadlet splits as systemd does (Environment, Label, Exec): double quotes and backslash
    escapes, `%%` a literal `%`."""
    return [w.replace("%%", "%") for w in shlex.split(value, posix=True)]


def canonical(m: dict) -> str:
    return json.dumps(m, sort_keys=True)


def model(text: str) -> str:
    """One system as the engine would run it (see the docstring), as canonical JSON; unreadable text is itself."""
    if text.startswith("# FileName="):
        return quadlets(text)
    try:
        doc = yaml.safe_load(text)
        services = dict(doc["services"])
    except (yaml.YAMLError, KeyError, TypeError, ValueError):
        return text
    out = {k: v for k, v in doc.items() if k != "services"}           # any other top-level key stays, as itself
    out["services"] = {}
    for name, svc in services.items():
        m = {k: v for k, v in svc.items() if k != "healthcheck"}
        for key in ("environment", "labels"):
            if key in m:
                v = m[key]
                m[key] = dict(sorted((str(a), str(b)) for a, b in (v.items() if isinstance(v, dict) else (x.split("=", 1) for x in v))))
        for key in ("command", "entrypoint"):
            if key in m:
                m[key] = [str(x) for x in m[key]] if isinstance(m[key], list) else shlex.split(str(m[key]))
        for key in ("working_dir", "user"):
            if key in m:
                m[key] = str(m[key])
        if "depends_on" in m:
            m["depends_on"] = sorted(m["depends_on"])
        if "restart" in m:
            m["restart"] = RESTART.get(str(m["restart"]), m["restart"])
        out["services"][str(name)] = m
    return canonical(out)


def quadlets(text: str) -> str:
    """A `.quadlets` bundle as the same model: one `<p>.network` with nothing in it, and per service a
    `<p>-<name>.container` whose ContainerName is `<p>-<name>`, NetworkAlias `<name>` and Network `<p>.network`;
    Requires and After name the same `<p>-<dep>.service` units (depends_on), Restart is restart, WantedBy is
    default.target. Anything else, or any of these otherwise, stays in the model under its own name."""
    files = {}
    for part in text.split("\n---\n"):
        lines = part.strip("\n").splitlines()
        name = lines[0].removeprefix("# FileName=").strip() if lines and lines[0].startswith("# FileName=") else "?"
        sections, head = {}, None
        for line in lines[1:]:
            if line.startswith("[") and line.endswith("]"):
                head = line[1:-1]
                sections.setdefault(head, [])
            elif line.strip() and head:
                k, _, v = line.partition("=")
                sections[head].append((k.strip(), v.strip()))
            elif line.strip():
                sections.setdefault("", []).append(("", line))
        files[name] = sections
    nets = [n for n in files if n.endswith(".network")]
    prefix = nets[0].removesuffix(".network") if len(nets) == 1 and files[nets[0]] == {"Network": []} else None
    out: dict = {"services": {}}
    for name, sections in files.items():
        if prefix is not None and name == f"{prefix}.network":
            continue
        settings = [(h, k, v) for h, body in sections.items() for k, v in body]
        alias = [v for h, k, v in settings if (h, k) == ("Container", "NetworkAlias")]
        svc = alias[0] if len(alias) == 1 else None
        unit = f"{prefix}-{svc}"
        if prefix is None or svc is None or name != f"{unit}.container":
            out[f"file:{name}"] = sections
            continue
        m: dict = {}
        requires, after = [], []
        for head, k, v in settings:
            if head == "Container" and (k, v) in (("NetworkAlias", svc), ("ContainerName", unit), ("Network", f"{prefix}.network")):
                continue
            if head == "Container" and k in UNJUDGED:
                continue
            if (head, k) in (("Unit", "Requires"), ("Unit", "After")) and v.startswith(f"{prefix}-") and v.endswith(".service"):
                (requires if k == "Requires" else after).append(v[len(prefix) + 1:-len(".service")])
            elif (head, k, v) == ("Install", "WantedBy", "default.target"):
                continue
            elif (head, k) == ("Service", "Restart"):
                m["restart"] = v
            elif head != "Container" or k not in MAPPED:
                m.setdefault(f"{head}:{k}", []).append(v)
            elif k in ("Environment", "Label"):
                m.setdefault(MAPPED[k], {}).update(w.split("=", 1) for w in unquote(v))
            elif k == "PublishPort":
                m.setdefault("ports", []).append(v)
            elif k == "Entrypoint":
                m["entrypoint"] = json.loads(v.replace("%%", "%"))
            elif k == "Exec":
                m["command"] = unquote(v)
            else:                                             # taken as written: quotes would stay in the value
                m[MAPPED[k]] = v.replace("%%", "%")
        if requires or after:
            m["depends_on"] = sorted(requires)
            if sorted(after) != sorted(requires):
                m["Unit:After"] = sorted(after)
        own = {"com.docker.compose.project": prefix, "com.docker.compose.service": svc}   # as Compose labels its containers
        if all(m.get("labels", {}).get(k) == v for k, v in own.items()):
            for k in own:
                del m["labels"][k]
            if not m["labels"]:
                del m["labels"]
        for key in ("environment", "labels"):
            if key in m:
                m[key] = dict(sorted(m[key].items()))
        out["services"][svc] = m
    return canonical(out)


def stops(c: dict) -> bool:
    return any(a in ("down", "stop", "rm", "kill", "delete", "disable") for a in c["args"])


def refused(events: list[dict], system: str) -> bool:
    return any(e.get("system") == system and e.get("event") == "refused" for e in events)


def main(provider: Path) -> int:
    rec = Record("kkc_runtime", [provider])
    tmp = Path(tempfile.mkdtemp(prefix="kkc-runtime-"))
    ok = True
    try:
        w = World(provider, rec, tmp)
        first = compose()
        w.commit("demo", first)
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "unapproved-not-run", f"{calls} {events}")

        adopt = w.propose("urn:kk:system:demo", sha(first), shows=first)
        calls, events = w.run()
        ok &= check(not ran(calls), C + "awaiting-not-run", str(calls))

        w.approve(adopt)
        calls, events = w.run()
        ok &= check(ran(calls) == [model(first)], C + "approved-runs", f"{calls} {events}")
        runs = rec.rows("""select r.outputs, r.used, r.plan_step from kernel.run r join kernel.agent a on a.iri = r.agent
                           where a.db_role = %s and r.status = 'succeeded' and r.outputs ? 'applied'""",
                        (meta(provider).get("role"),))
        step_claims = {str(r["id"]) for r in rec.rows("select id from kernel.claim where change_set = %s and subject like %s",
                                                         (adopt, "%:step:1"))}
        ok &= check(len(runs) == 1 and runs[0]["outputs"].get("system") == "demo" and runs[0]["outputs"].get("applied") == sha(first)
                    and str(runs[0]["plan_step"]).endswith(":step:1")
                    and step_claims and step_claims <= {str(u) for u in runs[0]["used"]}, C + "recorded", str(runs))

        edited = compose("150")
        w.commit("demo", edited)
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "edited-not-run", f"{calls} {events}")

        shown = compose("300", image=OTHER)
        w.approve(w.propose("urn:kk:system:demo", sha(compose("300")), shows=shown))
        w.commit("demo", compose("300"))
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "label-shows-file", f"{calls} {events}")

        w.commit("demo", first)                           # back to the approved file, then a node step for 150
        w.run()
        step = w.propose("urn:kk:node:demo:web", 150, file_sha=sha(edited))
        w.approve(step)
        w.commit("demo", edited, add=False)
        calls, events = w.run()
        ok &= check(model(edited) not in ran(calls), C + "worktree-not-run", str(calls))
        git(w.intent, "commit", "-qam", "delay 150")
        calls, events = w.run()
        ok &= check(ran(calls) == [model(edited)], C + "node-step-runs", f"{calls} {events}")

        swapped = compose("75", image=OTHER)              # the step says 75; its hash names a file with another image
        w.approve(w.propose("urn:kk:node:demo:web", 75, file_sha=sha(swapped)))
        w.commit("demo", swapped)
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "node-hash-not-trusted", f"{calls} {events}")

        w.approve(w.propose("urn:kk:node:demo:web", 80, action="urn:kk:action:contract"))
        w.commit("demo", compose("80"))
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "listed-action", f"{calls} {events}")

        w.commit("demo", first)
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "no-rollback", f"{calls} {events}")

        w.withdraw(step)                                  # the step that approved the newer file, withdrawn by its proposer
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "demo"), C + "floor-kept", f"{calls} {events}")

        w.commit("other", first)                          # the bytes demo's adopt step approved, as another system
        calls, events = w.run()
        ok &= check(model(first) not in ran(calls) and refused(events, "other"), C + "per-system", f"{calls} {events}")

        secret = rec.scope("urn:kk:scope:contract-runtime-secret", readers=(w.proposer, w.person))
        hidden = compose("75")
        w.approve(w.propose("urn:kk:system:hidden", sha(hidden), scope=secret, shows=hidden))
        w.commit("hidden", hidden)
        calls, events = w.run()
        ok &= check(model(hidden) not in ran(calls) and refused(events, "hidden"), C + "clearance", f"{calls} {events}")

        bad = compose("600", "    privileged: true\n")
        w.approve(w.propose("urn:kk:system:bad", sha(bad), shows=bad))
        w.commit("bad", bad)
        calls, events = w.run()
        ok &= check(model(bad) not in ran(calls) and refused(events, "bad"), C + "allow-list", f"{calls} {events}")

        sneaky = compose("600", '    depends_on: ["cache\\n[Service]\\nExecStartPre=/bin/touch /tmp/kkc-runtime"]\n')
        w.approve(w.propose("urn:kk:system:sneaky", sha(sneaky), shows=sneaky))
        w.commit("sneaky", sneaky)
        calls, events = w.run()
        ok &= check(not ran(calls) and refused(events, "sneaky"), C + "depends-on-own-services", f"{calls} {events}")

        w.commit("demo", None)
        calls, events = w.run()
        ok &= check(not any(stops(c) for c in calls) and not ran(calls)
                    and any(e.get("system") == "demo" and e.get("event") == "unmanaged" for e in events),
                    C + "removed-left-running", f"{calls} {events}")
        return 0 if ok else 1
    finally:
        rec.drop()
        subprocess.run(["rm", "-rf", str(tmp)])


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
