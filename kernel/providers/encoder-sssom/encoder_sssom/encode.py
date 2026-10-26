"""SSSOM/TSV (embedded metadata mode, SSSOM 1.0.0) -> mapping claims (R5-51). Pure functions; no database.

  read(text)               -> (metadata, [(line, row)]): the metadata block's YAML, then each mapping with the line
                              it starts on; set-level values of propagatable slots copied to every mapping (spec:
                              "Propagation"); CURIEs expanded with the set's curie_map and the built-in prefixes
  encode(rel, sha, text)   -> (ops, skipped): one claim per mapping whose predicate is a SKOS mapping property and
                              not negated, `subject predicate object` with qualifiers sssom:mapping_justification,
                              sssom:confidence and sssom:mapping_tool where the row has them; each references the
                              file as an artifact (its sha256) and the row's line (RFC 5147). Other rows are skipped with
                              the reason, never recorded under another predicate.

A file the spec says to reject is refused whole (SSSOMError): a byte order mark, an undeclared prefix, a built-in
prefix bound to another IRI, an identifier written as an IRI (its scheme is no declared prefix), no mapping_set_id, a confidence outside [0, 1].
The encoder decides nothing about whether a mapping is right: every claim it writes is a skos:*Match, which the
lane policy sends to a person (R5-O13 (2)).
"""
from __future__ import annotations

import csv
import io

import yaml

SSSOM = "https://w3id.org/sssom/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SKOS_MATCHES = {SKOS + p for p in ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch")}
BUILTIN = {  # spec-intro.md, "IRI prefixes"
    "owl": "http://www.w3.org/2002/07/owl#", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "semapv": "https://w3id.org/semapv/vocab/",
    "skos": SKOS, "sssom": SSSOM, "xsd": "http://www.w3.org/2001/XMLSchema#", "linkml": "https://w3id.org/linkml/",
}
PROPAGATABLE = {"mapping_date", "mapping_provider", "mapping_tool", "mapping_tool_version", "object_match_field",
                "object_preprocessing", "object_source", "object_source_version", "object_type", "subject_match_field",
                "subject_preprocessing", "subject_source", "subject_source_version", "subject_type"}
ENTITY = ("subject_id", "predicate_id", "object_id", "mapping_justification")   # the EntityReference slots we read


class SSSOMError(ValueError):
    """The file is not one the spec lets a parser accept."""


def _metadata(lines: list[str]) -> tuple[dict, int]:
    block = []
    for line in lines:
        if not line.startswith("#"):
            break
        block.append(line[1:])
    pad = len(block[0]) - len(block[0].lstrip(" ")) if block else 0
    for b in block:
        if b.strip() and b[:pad].strip(" "):
            raise SSSOMError("metadata block: every line must have the same number of spaces after '#'")
    meta = yaml.safe_load("\n".join(b[pad:] for b in block)) if block else None
    if not isinstance(meta, dict):
        raise SSSOMError("no metadata block (embedded mode)")
    return meta, len(block)


def _prefixes(meta: dict) -> dict:
    declared = meta.get("curie_map") or {}
    if not isinstance(declared, dict):
        raise SSSOMError("curie_map is not a map")
    for k, v in declared.items():
        if k in BUILTIN and v != BUILTIN[k]:
            raise SSSOMError(f"built-in prefix {k} bound to {v}, not {BUILTIN[k]}")
    return {**BUILTIN, **declared}


def expand(curie: str, prefixes: dict) -> str:
    """A CURIE with a declared (or built-in) prefix; an IRI is refused too, its scheme being no declared prefix."""
    prefix, sep, local = curie.partition(":")
    if not sep or prefix not in prefixes:
        raise SSSOMError(f"{curie}: prefix {prefix!r} is not declared in curie_map")
    return prefixes[prefix] + local


def read(text: str) -> tuple[dict, list[tuple[int, dict]]]:
    if text.startswith("\ufeff"):
        raise SSSOMError("SSSOM/TSV files must not start with a byte order mark")
    lines = text.split("\n")
    meta, skip = _metadata(lines)
    if not meta.get("mapping_set_id"):
        raise SSSOMError("no mapping_set_id")
    prefixes = _prefixes(meta)
    reader = csv.reader(io.StringIO("\n".join(lines[skip:])), delimiter="\t", quotechar='"', doublequote=True, strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise SSSOMError("no mappings block") from None
    rows, end = [], reader.line_num
    for values in reader:
        start, end = skip + end + 1, reader.line_num
        if not any(v.strip() for v in values):
            continue
        if len(values) != len(header):
            raise SSSOMError(f"line {start}: {len(values)} values for {len(header)} columns")
        rows.append((start, {k: v for k, v in zip(header, values) if v != ""}))
    for slot in PROPAGATABLE & set(meta):
        if not any(slot in r for _, r in rows):
            for _, r in rows:
                r[slot] = str(meta[slot])
    for n, r in rows:
        for k in ENTITY:
            if k in r:
                try:
                    r[k] = expand(r[k], prefixes)
                except SSSOMError as e:
                    raise SSSOMError(f"line {n}: {e}") from None
        if "confidence" in r:
            try:
                c = float(r["confidence"])
            except ValueError:
                c = -1.0
            if not 0.0 <= c <= 1.0:
                raise SSSOMError(f"line {n}: confidence {r['confidence']!r} is not between 0 and 1")
            r["confidence"] = c
    return meta, rows


def encode(rel: str, sha: str, text: str) -> tuple[list[dict], list[dict]]:
    meta, rows = read(text)
    ops, skipped = [], []
    for n, r in rows:
        missing = [k for k in ("subject_id", "predicate_id", "object_id") if k not in r]
        why = (f"no {', '.join(missing)}" if missing
               else "negated (predicate_modifier Not)" if r.get("predicate_modifier") == "Not"
               else f"{r['predicate_id']} is not a SKOS mapping property" if r["predicate_id"] not in SKOS_MATCHES
               else None)
        if why:
            skipped.append({"line": n, "why": why})
            continue
        q = {SSSOM + k: r[k] for k in ("mapping_justification", "confidence", "mapping_tool") if k in r}
        ops.append({"op": "add_claim", "subject": r["subject_id"], "predicate": r["predicate_id"],
                    "object": {"entity": r["object_id"]}, **({"qualifiers": q} if q else {}),
                    "evidence_type": "deterministic",
                    "references": [{"artifact": sha, "source_uri": f"file:{rel}#sha256={sha}",
                                    "span": {"type": "FragmentSelector", "value": f"line={n}",
                                             "conformsTo": "https://www.rfc-editor.org/rfc/rfc5147"}}]})
    return ops, skipped
