"""The SSSOM/TSV reader (encode.py, no database): the metadata block, quoting, propagation, CURIEs, and what the
spec says to refuse.

  python3 tests/test_encode.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from encoder_sssom import encode  # noqa: E402

SKOS = "http://www.w3.org/2004/02/skos/core#"
SET = """# curie_map:
#   A: https://a.example/
#   B: https://b.example/
#   orcid: https://orcid.org/
# mapping_set_id: https://example.org/a-b.sssom.tsv
# license: https://creativecommons.org/licenses/by/4.0/
# mapping_tool: https://example.org/matcher
subject_id\tpredicate_id\tobject_id\tmapping_justification\tconfidence\tcomment
A:1\tskos:exactMatch\tB:1\tsemapv:ManualMappingCuration\t0.95\t"a ""quoted"" comment
over two lines"
A:2\towl:equivalentClass\tB:2\tsemapv:LexicalMatching\t\t
A:3\tskos:broadMatch\tB:3\tsemapv:LexicalMatching\t\t
"""


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def refused(text: str, what: str, says: str = "") -> None:
    try:
        encode.read(text)
    except encode.SSSOMError as e:
        if says not in str(e):
            raise SystemExit(f"CHECK FAILED: {what} refused, but the reason does not say {says!r}: {e}")
        print(f"ok: refused: {what} ({e})")
        return
    raise SystemExit(f"CHECK FAILED: not refused: {what}")


def main() -> None:
    meta, rows = encode.read(SET)
    check(meta["mapping_set_id"] == "https://example.org/a-b.sssom.tsv" and len(rows) == 3, "the metadata block and three mappings")
    check([n for n, _ in rows] == [9, 11, 12], f"each mapping keeps the line it starts on, after a quoted line break ({[n for n, _ in rows]})")
    check(rows[0][1]["comment"] == 'a "quoted" comment\nover two lines', "quotes and doubled quotes are stripped")
    check(rows[0][1]["subject_id"] == "https://a.example/1" and rows[0][1]["predicate_id"] == SKOS + "exactMatch"
          and rows[0][1]["mapping_justification"] == "https://w3id.org/semapv/vocab/ManualMappingCuration",
          "CURIEs expanded with the curie_map and the built-in prefixes")
    check(all(r["mapping_tool"] == "https://example.org/matcher" for _, r in rows), "a set-level mapping_tool is propagated")
    check(rows[0][1]["confidence"] == 0.95 and "confidence" not in rows[1][1], "confidence read as a number; an empty cell is no value")

    ops, skipped = encode.encode("a-b.sssom.tsv", "ab" * 32, SET)
    check([(o["subject"], o["predicate"], o["object"]["entity"]) for o in ops]
          == [("https://a.example/1", SKOS + "exactMatch", "https://b.example/1"),
              ("https://a.example/3", SKOS + "broadMatch", "https://b.example/3")],
          "one claim per SKOS mapping")
    check(skipped == [{"line": 11, "why": "http://www.w3.org/2002/07/owl#equivalentClass is not a SKOS mapping property"}],
          "an owl:equivalentClass row is skipped with why, never recorded under another predicate")
    q = ops[0]["qualifiers"]
    check(q == {"https://w3id.org/sssom/mapping_justification": "https://w3id.org/semapv/vocab/ManualMappingCuration",
                "https://w3id.org/sssom/confidence": 0.95, "https://w3id.org/sssom/mapping_tool": "https://example.org/matcher"},
          "justification, confidence and tool as qualifiers")
    ref = ops[1]["references"][0]
    check(ref["source_uri"] == "file:a-b.sssom.tsv#sha256=" + "ab" * 32 and ref["artifact"] == "ab" * 32 and ref["span"]["value"] == "line=12"
          and all(o["evidence_type"] == "deterministic" for o in ops), "each cites the file by its sha256 and the row's line")
    neg = SET.replace("comment\n", "comment\tpredicate_modifier\n").replace("over two lines\"\n", "over two lines\"\tNot\n")
    neg = neg.replace("LexicalMatching\t\t\n", "LexicalMatching\t\t\t\n")
    check([o["subject"] for o in encode.encode("x", "0" * 64, neg)[0]] == ["https://a.example/3"], "a negated mapping is skipped")

    refused("\ufeff" + SET, "a byte order mark", "byte order mark")
    refused(SET.replace("A:3\t", "C:3\t"), "an undeclared prefix")
    refused(SET.replace("A:3\t", "https://a.example/3\t"), "an IRI where a CURIE belongs")
    refused(SET.replace("#   orcid: https://orcid.org/\n", "#   skos: https://example.org/skos#\n"), "a built-in prefix bound elsewhere")
    refused(SET.replace("# mapping_set_id: https://example.org/a-b.sssom.tsv\n", ""), "no mapping_set_id")
    refused(SET.replace("\t0.95\t", "\t1.5\t"), "a confidence above 1")
    refused(SET.replace("A:3\tskos:broadMatch\tB:3\t", "A:3\tskos:broadMatch\t"), "a row with too few values")
    refused(SET.replace("# license", "#license"), "metadata lines with different indentation")
    print("encode checks passed")


if __name__ == "__main__":
    main()
