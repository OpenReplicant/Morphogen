"""The documents people write, and the one way they are read.

Documents are the files a person (or the agent, on a branch) writes and git
versions: morphogen.yaml, target.yaml, catalogs.yaml and strategy cards. Each
has a schema here; `load` reads a file, checks it against its schema and
returns plain data, or raises DocumentError naming the file and every problem.

Schemas check structure and types only. What a value means (whether a metric
may decide a verdict, whether a simulated target says what it simulates) is
checked where it is used, by the judge. Unknown keys are kept, so a document
written for a newer version still loads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator


class DocumentError(ValueError):
    def __init__(self, path: Path | str, problems: list[str]):
        self.path, self.problems = str(path), problems
        super().__init__(f"{path}: " + "; ".join(problems))


class _Doc(BaseModel):
    model_config = ConfigDict(extra="allow")


# morphogen.yaml

class Database(_Doc):
    """Where the lists and logs live. Unset: SQLite in git's own directory."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    url: str | None = None  # any SQLAlchemy URL; MORPHOGEN_DATABASE_URL overrides (keep passwords there)
    schema_: str | None = Field(None, alias="schema")  # `schema` would shadow a BaseModel method
    options: dict[str, Any] = {}  # passed to sqlalchemy.create_engine (connect_args for driver flags)


class Budget(_Doc):
    tool_calls: int | None = None
    trials_per_day: int | None = None
    probes_per_day: int | None = None


class Config(_Doc):
    trunk: str = "main"
    autonomy: int | None = None
    data_dir: str = ".morphogen"
    strategy: str | None = None
    strategies: Any = None
    database: Database = Database()
    sandbox: Literal["auto", "docker", "podman", "none"] = "auto"
    sandbox_image: str = "python:3.12-slim"
    budget: Budget | None = None
    targets: list[str] = []
    map_name: str | None = None
    maps: dict[str, dict[str, Any]] | None = None


# target.yaml

class Metric(_Doc):
    direction: Literal["lower", "higher"] = "lower"
    primary: bool = False
    min_improvement: float | None = None
    max_regression: float | None = None
    gain: Literal["relative", "absolute"] = "relative"
    aggregate: Literal["median", "mean"] = "median"


class Observer(_Doc):
    run: str
    collected: str | None = None


class Measure(_Doc):
    run: str
    warmup: int | None = None
    repeats: int | None = None
    max_repeats: int | None = None
    same_output: bool = True
    observer: Observer | None = None
    metrics: dict[str, Metric] = {}


class Equivalence(_Doc):
    gen: str | None = None
    run: str | None = None
    cases: int | None = None


class TargetParameter(_Doc):
    """A setting in the target's files that the judge reads in base and candidate. The owner decides
    who may change it: agent (within range or choices), operator or judge (never, in a candidate)."""
    file: str                      # relative to the target directory
    name: str | None = None        # a module-level constant in a Python file
    key: str | None = None         # a dotted key in a YAML, JSON or TOML file
    owner: Literal["agent", "operator", "judge"]
    range: tuple[float, float] | None = None
    choices: list[Any] | None = None

    @model_validator(mode="after")
    def _one_location(self):
        if bool(self.name) == bool(self.key):
            raise ValueError("give exactly one of name (a Python constant) or key (a dotted key)")
        if self.range and self.range[0] > self.range[1]:
            raise ValueError("range must be [low, high]")
        return self


class Target(_Doc):
    name: str | None = None
    description: str | None = None
    interface: str = "direct"  # direct | simulated; the judge checks it and what follows from it
    simulates: str | None = None
    harness: list[str] = []
    check: str | None = None
    equivalence: Equivalence | None = None
    measure: Measure | None = None
    timeout: int | None = None
    parameters: dict[str, TargetParameter] = {}


# catalogs.yaml: named sections, each a list of entries

class Catalogs(RootModel[dict[str, list[dict[str, Any]]]]):
    pass


# strategy cards: Markdown with YAML front matter

class StrategyCard(_Doc):
    name: str
    description: str
    when: str
    weak_when: str | None = None


SCHEMAS: dict[str, type[BaseModel]] = {
    "config": Config, "target": Target, "catalogs": Catalogs, "strategy": StrategyCard,
}


def _problems(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in err['loc']) or '(top)'}: {err['msg']}" for err in e.errors()]


def validate(kind: str, data: Any, path: Path | str = "<data>") -> dict:
    """Check `data` against the schema for `kind` and return it with defaults filled in."""
    model = SCHEMAS[kind]
    try:
        doc = model.model_validate({} if data is None else data)
    except ValidationError as e:
        raise DocumentError(path, _problems(e)) from None
    return doc.model_dump(by_alias=True, exclude_none=True)


def _yaml(path: Path, text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise DocumentError(path, [f"not valid YAML: {e}"]) from None


def load(kind: str, path: Path) -> dict:
    """Read a document of `kind` (config, target, catalogs, strategy) and validate it.

    A strategy card is returned with its Markdown `body` and `path` alongside the front matter.
    """
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as e:
        raise DocumentError(path, [f"cannot read: {e.strerror or e}"]) from None
    if kind != "strategy":
        return validate(kind, _yaml(path, text), path)
    if not text.startswith("---"):
        raise DocumentError(path, ["no front matter (the card must start with ---)"])
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise DocumentError(path, ["front matter is not closed with ---"])
    meta = validate(kind, _yaml(path, parts[1]), path)
    return {**meta, "body": parts[2].strip(), "path": str(path)}
