"""The system structure: containment, interfaces, scopes, boundaries, checks, comparison, rendering.

Run: uv run python -m unittest discover -s tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import Structure, StructureError, compare
from morphogen.render import mermaid

ROOT = Path(__file__).resolve().parents[1]

AGENT = {
    "cells": {
        "agent": {"provides": ["answer"]},
        "retrieval": {"parent": "agent", "provides": ["retrieve"], "consumes": ["memory-read"],
                      "parameters": {"top_k": {"file": "config.yaml", "key": "retrieve.top_k",
                                               "owner": "agent", "range": [1, 50]}}},
        "memory": {"parent": "agent", "provides": ["memory-read"]},
        "answerer": {"parent": "agent", "consumes": ["retrieve", "llm"]},
        "store": {"parent": "memory", "provides": ["rows"]},
        "index": {"parent": "memory", "consumes": ["rows"]},
    },
    "interfaces": {
        "answer": {"tests": ["test_answer"], "external": "consumes"},
        "retrieve": {"tests": ["test_retrieve"]},
        "memory-read": {"tests": ["test_memory_read"]},
        "rows": {"tests": []},
        "llm": {"tests": ["test_llm_contract"], "external": "provides"},
    },
}


def structure(data=None):
    return Structure.from_dict(json.loads(json.dumps(data or AGENT)))


class Containment(unittest.TestCase):
    def test_roots_children_and_scope(self):
        s = structure()
        self.assertEqual(s.roots(), ["agent"])
        self.assertEqual(s.children("agent"), ["answerer", "memory", "retrieval"])
        self.assertEqual(s.scope("memory"), {"memory", "store", "index"})
        self.assertEqual(s.scope("retrieval"), {"retrieval"})
        self.assertEqual(s.scope("agent"), set(AGENT["cells"]))

    def test_unknown_cell(self):
        with self.assertRaises(KeyError):
            structure().scope("nope")


class Connection(unittest.TestCase):
    def test_providers_consumers_neighbours(self):
        s = structure()
        self.assertEqual(s.providers("retrieve"), ["retrieval"])
        self.assertEqual(s.consumers("retrieve"), ["answerer"])
        self.assertEqual(s.neighbours("retrieval"), ["answerer", "memory"])

    def test_boundary_is_computed(self):
        s = structure()
        # memory's scope: rows is internal (store to index); memory-read crosses to retrieval
        self.assertEqual(s.touched(s.scope("memory")), ["memory-read", "rows"])
        self.assertEqual(s.boundary(s.scope("memory")), ["memory-read"])
        # the whole system's boundary: what the world consumes and what it provides
        self.assertEqual(s.boundary(s.scope("agent")), ["answer", "llm"])

    def test_tests_for_a_scope_cover_internal_and_boundary_interfaces(self):
        s = structure()
        self.assertEqual(s.tests_for({"retrieval"}), ["test_memory_read", "test_retrieve"])
        self.assertEqual(s.tests_for(s.scope("agent")),
                         ["test_answer", "test_llm_contract", "test_memory_read", "test_retrieve"])


class Checks(unittest.TestCase):
    def kinds(self, data):
        return {(f.kind, f.subject) for f in structure(data).check()}

    def test_clean_structure_has_only_coverage_warnings(self):
        findings = structure().check()
        self.assertEqual([(f.kind, f.subject) for f in findings], [("untested", "rows")])

    def test_gap_unused_unattached_unknown(self):
        data = json.loads(json.dumps(AGENT))
        data["cells"]["answerer"]["consumes"].append("ranker")       # nothing provides it
        data["interfaces"]["ranker"] = {"tests": ["t"]}
        data["cells"]["memory"]["provides"].append("dump")            # nothing consumes it
        data["interfaces"]["dump"] = {"tests": ["t"]}
        data["interfaces"]["orphan"] = {"tests": ["t"]}               # nothing attached
        data["cells"]["index"]["consumes"].append("undeclared")
        found = self.kinds(data)
        self.assertIn(("gap", "ranker"), found)
        self.assertIn(("unused", "dump"), found)
        self.assertIn(("unattached", "orphan"), found)
        self.assertIn(("unknown-interface", "index"), found)

    def test_external_roles_are_not_gaps(self):
        found = self.kinds(AGENT)
        self.assertNotIn(("gap", "llm"), found)
        self.assertNotIn(("unused", "answer"), found)

    def test_cycles_and_unknown_parents(self):
        data = {"cells": {"a": {"parent": "b"}, "b": {"parent": "a"}, "c": {"parent": "missing"}}}
        found = self.kinds(data)
        self.assertIn(("cycle", "a"), found)
        self.assertIn(("unknown-parent", "c"), found)

    def test_coverage(self):
        cov = structure().coverage()
        self.assertEqual((cov["interfaces"], cov["tested"], cov["untested"]), (5, 4, ["rows"]))

    def test_schema_errors_name_the_problem(self):
        with self.assertRaises(StructureError) as e:
            Structure.from_dict({"cells": {"x": {"parameters": {"p": {"file": "f", "owner": "agent"}}}}})
        self.assertIn("exactly one of name", str(e.exception))
        with self.assertRaises(StructureError):
            Structure.from_dict({"cells": {"x": {"parameters": {"p": {"file": "f", "name": "P",
                                                                      "owner": "someone"}}}}})


class Comparison(unittest.TestCase):
    def test_convergence_absence_divergence(self):
        observed = json.loads(json.dumps(AGENT))
        del observed["cells"]["index"]                                  # built? not seen running
        observed["cells"]["answerer"]["consumes"].append("cache")       # seen, never intended
        observed["interfaces"]["cache"] = {}
        observed["cells"]["cache"] = {"parent": "agent", "provides": ["cache"]}
        c = compare(structure(), structure(observed))
        self.assertEqual(c["cells"]["index"], "absence")
        self.assertEqual(c["cells"]["cache"], "divergence")
        self.assertEqual(c["cells"]["retrieval"], "convergence")
        self.assertEqual(c["attachments"]["answerer consumes cache"], "divergence")
        self.assertEqual(c["attachments"]["index consumes rows"], "absence")
        self.assertEqual(c["interfaces"]["cache"], "divergence")
        self.assertEqual(c["containment"]["index in memory"], "absence")


class Rendering(unittest.TestCase):
    def test_nested_boxes_edges_and_hubs(self):
        text = mermaid(structure())
        self.assertTrue(text.startswith("flowchart LR"))
        self.assertIn('subgraph c_agent["agent"]', text)
        self.assertIn('subgraph c_memory["memory"]', text)
        self.assertIn('c_retrieval -->|"retrieve"| c_answerer', text)       # one to one: an edge
        self.assertIn('c_store -->|"rows"| c_index', text)
        self.assertIn('c_agent -->|"answer"| outside', text)                 # open to the world
        self.assertIn('outside -->|"llm"| c_answerer', text)

    def test_overlay_marks_absences_and_divergences(self):
        observed = json.loads(json.dumps(AGENT))
        del observed["cells"]["index"]
        text = mermaid(structure(), compare(structure(), structure(observed)), notes={"retrieval": "p95 120 ms"})
        self.assertIn("class c_index absence", text)
        self.assertIn("p95 120 ms", text)
        self.assertIn("linkStyle", text)                                    # the rows edge is dashed

    def test_hub_for_shared_interfaces(self):
        data = json.loads(json.dumps(AGENT))
        data["cells"]["index"]["consumes"].append("memory-read")
        text = mermaid(structure(data))
        self.assertIn('i_memory_read(("memory-read"))', text)


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "morphogen", *args], capture_output=True, text=True, cwd=ROOT)

    def test_check_scope_render(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "cells.yaml"
            f.write_text(yaml.safe_dump(AGENT))
            r = self.run_cli("structure", "check", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["coverage"]["tested"], 4)
            r = self.run_cli("structure", "scope", str(f), "memory")
            self.assertEqual(json.loads(r.stdout)["boundary"], ["memory-read"])
            r = self.run_cli("structure", "render", str(f))
            self.assertIn("flowchart LR", r.stdout)

    def test_check_fails_on_errors(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "cells.yaml"
            f.write_text(yaml.safe_dump({"cells": {"a": {"consumes": ["x"]}}, "interfaces": {"x": {}}}))
            self.assertEqual(self.run_cli("structure", "check", str(f)).returncode, 1)
            f.write_text("cells: [")
            self.assertEqual(self.run_cli("structure", "check", str(f)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
