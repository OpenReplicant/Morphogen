"""The gap-finder cases must fail when a rule in the shapes is broken: each mutant edits a copy of the kk-tosca shapes
and runs the gap-finder case set (contract/slots/gap-finder) and this provider's own tests with KK_SHAPES_DIR pointing at it.

  python3 tests/shape_mutants.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
SHAPES = ROOT / "kernel" / "packs" / "kk-tosca.shapes.ttl"
RUNNER = ROOT / "kernel" / "contract" / "slots" / "gap-finder" / "runner.py"

MUTANTS = {
    "the unknown-peer rule dropped": ("sh:class kkt:NodeTemplate ;\n    sh:severity sh:Warning ;", "sh:severity sh:Warning ;"),
    "no-image asked of nothing": ("sh:qualifiedMinCount 1 ;\n    sh:severity", "sh:qualifiedMinCount 0 ;\n    sh:severity"),
    "an image setting is any setting": ('kkts:ImageSetting a sh:NodeShape ;\n    sh:property [ sh:path kkt:propertyName ; sh:hasValue "image" ] .',
                                        "kkts:ImageSetting a sh:NodeShape ."),
    "any image counts as pinned": ('sh:pattern "^[A-Za-z0-9._/:-]+@sha256:[0-9a-f]{64}$"', 'sh:pattern "."'),
    "a digest need not be whole": ("[0-9a-f]{64}$", "[0-9a-f]+"),
    "unconnected in a system of one": ("FILTER EXISTS { ?other a kkt:NodeTemplate ; kkt:memberOf ?system . FILTER (?other != $this) }", ""),
    "a caller from another system connects": ("FILTER NOT EXISTS { ?caller kkt:connectsTo $this ; kkt:memberOf ?system }\n",
                                              "FILTER NOT EXISTS { ?caller kkt:connectsTo $this }\n"),
    "a prediction counts as a limit": ("FILTER NOT EXISTS { ?limit ?q ?v . FILTER (?q NOT IN (rdf:value, sosa:observedProperty)) }\n                }\n            }\"\"\" ] ;\n    sh:severity sh:Warning ;\n    dcterms:type <urn:kk:gap-kind:no-limit> ;\n    kk:premisePredicate rdf:type , kkt:memberOf ;\n    sh:order 5 ;\n    sh:message \"What",
                                       "}\n            }\"\"\" ] ;\n    sh:severity sh:Warning ;\n    dcterms:type <urn:kk:gap-kind:no-limit> ;\n    kk:premisePredicate rdf:type , kkt:memberOf ;\n    sh:order 5 ;\n    sh:message \"What"),
    "an entry point is any service": ("SELECT $this WHERE {\n                FILTER NOT EXISTS { ?caller kkt:connectsTo $this ; kkt:memberOf ?system . $this kkt:memberOf ?system }\n",
                                      "SELECT $this WHERE {\n"),
    "the system asked even with an entry point": ("FILTER NOT EXISTS {\n                    ?s a kkt:NodeTemplate ; kkt:memberOf $this .\n                    FILTER NOT EXISTS { ?caller kkt:connectsTo ?s ; kkt:memberOf $this }\n                }\n", ""),
    "a gap is a refusal, not a question": ("kkts:ServiceHasImage a sh:PropertyShape ;", "kkts:ServiceHasImage a sh:PropertyShape ; sh:deactivated true ;"),
    "a warning is not a gap": ("sh:severity sh:Warning ;\n    dcterms:type <urn:kk:gap-kind:unconnected>",
                               "sh:severity sh:Violation ;\n    dcterms:type <urn:kk:gap-kind:unconnected>"),
    "a differing value runs as intended": ("FILTER NOT EXISTS { $this kkt:propertyValue ?got . ?got kkt:propertyName ?name ; rdf:value ?value }",
                                           "FILTER NOT EXISTS { $this kkt:propertyValue ?got . ?got kkt:propertyName ?name }"),
    "drift where nothing of the system runs": ("                FILTER EXISTS { ?running a kkt:NodeRepresentation ; kkt:memberOf ?system }\n", ""),
    "a template with any representation counts as running": ("FILTER NOT EXISTS { ?r a kkt:NodeRepresentation ; kkt:representationOf $this }",
                                                             "FILTER NOT EXISTS { ?r a kkt:NodeRepresentation }"),
    "a representation of something off the map is intended": ("FILTER NOT EXISTS { $this kkt:representationOf ?template . ?template a kkt:NodeTemplate }",
                                                              "FILTER NOT EXISTS { $this kkt:representationOf ?template }"),
}


def main() -> int:
    text = SHAPES.read_text()
    survived = []
    for name, (old, new) in MUTANTS.items():
        if text.count(old) != 1:
            print(f"BAD MUTANT: {name}: the text to change occurs {text.count(old)} times")
            survived.append(name)
            continue
        with tempfile.TemporaryDirectory() as d:
            Path(d, SHAPES.name).write_text(text.replace(old, new))
            Path(d, "packs.yaml").write_text((SHAPES.parent / "packs.yaml").read_text())
            env = {**os.environ, "KK_SHAPES_DIR": d}
            killed = any(subprocess.run([sys.executable, *cmd], cwd=HERE, env=env, capture_output=True).returncode
                         for cmd in ([str(RUNNER), str(HERE)], [str(HERE / "tests" / "test_gaps.py")]))
        print(("killed  " if killed else "SURVIVED"), name)
        if not killed:
            survived.append(name)
    print(f"{len(MUTANTS) - len(survived)}/{len(MUTANTS)} mutants killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
