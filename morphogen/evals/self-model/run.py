"""Self-model questions on Morphogen (questions.yaml here), with kernel/evals/self-model/run.py's agent,
grader and run files. Only setup differs: Morphogen's install, its providers (--providers morphogen/modules)
and distribution file scanned by the self-encoder, and each managed system's compose file mapped by
encoder-compose.

  python morphogen/evals/self-model/run.py setup DB
  python morphogen/evals/self-model/run.py reference|grade|claude|tool|prompt ...   (as the kernel's, this set by default)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("self_model", ROOT / "kernel" / "evals" / "self-model" / "run.py")
kernel_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kernel_eval)
sys.path[:0] = [str(ROOT / "morphogen" / "modules"), str(ROOT / "morphogen" / "modules" / "encoder-compose")]

SYSTEMS = ROOT / "morphogen" / "intent" / "systems"


def install(db: str) -> None:
    import install as morphogen_install
    morphogen_install.install(db, ["encoder-compose"])
    morphogen_install.kernel.install(db, ["self-encoder"])


def setup(db: str) -> None:
    compose = importlib.import_module("encoder_compose.__main__")
    kernel_eval.setup(db, [str(ROOT / "morphogen" / "distribution.yaml")], [str(ROOT / "morphogen" / "modules")], install)
    for f in sorted(SYSTEMS.glob("*/compose.yaml")):
        compose.scan(f.parent.name, f, ROOT)
    kernel_eval.settle(db)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["setup"] and len(argv) == 2:
        setup(argv[1])
        print(f"ready: {argv[1]}; the agent's login is in {kernel_eval.CACHE / (argv[1] + '.login')}")
        return 0
    if argv[:1] in (["reference"], ["grade"], ["claude"], ["prompt"]) and "--questions" not in argv:
        argv += ["--questions", str(HERE / "questions.yaml")]
    return kernel_eval.main(argv)


if __name__ == "__main__":
    sys.exit(main())
