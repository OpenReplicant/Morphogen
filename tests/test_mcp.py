"""The MCP server: its tools, what an agent may and may not write, and a real stdio session."""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

from morphogen import mcp_server
from tests.fixture import CLASSIFY, ScoredProject

ROOT = Path(__file__).resolve().parents[1]

TOOLS = {
    "structure_check": ["file"], "structure_scope": ["cell", "file"], "structure_render": ["file"],
    "measure": ["target", "ref"], "probe": ["target", "candidate", "base", "cases", "rounds"],
    "judge": ["target", "candidate", "base", "labels"],
    "tune": ["target", "optimizer", "steps", "trials", "rounds", "base", "seed"],
    "evidence_query": ["contains", "by", "limit"],
    "evidence_note": ["claim", "source", "trust", "supports", "challenges"], "evidence_verify": [],
    "optimizers_list": [],
}


def call(name, args):
    r = asyncio.run(mcp_server.server.call_tool(name, args))
    return json.loads(r.content[0].text)


class Tools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = ScoredProject()
        cls.old = os.environ.get("MORPHOGEN_PROJECT")
        os.environ["MORPHOGEN_PROJECT"] = str(cls.p.repo)

    @classmethod
    def tearDownClass(cls):
        if cls.old is None:
            os.environ.pop("MORPHOGEN_PROJECT", None)
        else:
            os.environ["MORPHOGEN_PROJECT"] = cls.old
        cls.p.close()

    def test_the_tools_and_their_parameters(self):
        tools = {t.name: t for t in asyncio.run(mcp_server.server.list_tools())}
        self.assertEqual(set(tools), set(TOOLS))
        for name, params in TOOLS.items():
            have = set((tools[name].input_schema or {}).get("properties", {}))
            self.assertEqual(have, set(params), name)

    def test_judge_through_the_server(self):
        branch = self.p.branch("t50-mcp", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")})
        r = call("judge", {"target": self.p.target, "candidate": branch})
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual(call("evidence_verify", {})["chain"], "intact")

    def test_an_agent_cannot_write_measured_evidence(self):
        self.assertIn("error", call("evidence_note", {"claim": "it is faster", "trust": "measured"}))
        self.assertIn("error", call("evidence_note", {"claim": "docs say so", "trust": "stated"}))
        rec = call("evidence_note", {"claim": "docs say so", "trust": "stated", "source": "https://example.org"})
        self.assertEqual((rec["by"], rec["trust"]), ("agent", "stated"))

    def test_errors_come_back_as_results(self):
        self.assertIn("error", call("structure_check", {"file": "missing.yaml"}))
        self.assertIn("error", call("judge", {"target": "nowhere", "candidate": "main"}))


class Stdio(unittest.TestCase):
    def test_a_client_lists_the_tools_over_stdio(self):
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def run():
            params = StdioServerParameters(command=sys.executable, args=["-m", "morphogen.mcp_server"],
                                           cwd=str(ROOT), env={**os.environ, "MORPHOGEN_PROJECT": str(ROOT)})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return [t.name for t in (await session.list_tools()).tools]

        self.assertEqual(set(asyncio.run(run())), set(TOOLS))


if __name__ == "__main__":
    unittest.main()
