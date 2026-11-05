"""Download the Leipzig benchmark datasets, check them, and write them as JSONL.

The datasets are made available by Prof. Erhard Rahm's database group at the University of
Leipzig "under the Creative Commons license" (the page names no version, so they are not
committed here). Credit: https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution
and Köpcke, Thor and Rahm, "Evaluation of entity resolution approaches on real-world match
problems", VLDB 2010.

Run from the demo's directory: python data/fetch.py
Writes data/<dataset>/left.jsonl, right.jsonl and gold.jsonl (not committed).
"""

import csv
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://dbs.uni-leipzig.de/files/datasets/"
HERE = Path(__file__).resolve().parent

DATASETS = {
    "abt-buy": {
        "zip": "Abt-Buy.zip",
        "sha256": "b9ff2937d97371b7a00b0a97033213bfbdee24e8f1a0718a41ea8364472a8ff8",
        "left": ("Abt.csv", {"name": "name", "description": "description", "price": "price"}),
        "right": ("Buy.csv", {"name": "name", "description": "description",
                              "manufacturer": "manufacturer", "price": "price"}),
        "gold": ("abt_buy_perfectMapping.csv", "idAbt", "idBuy"),
    },
    "amazon-google": {
        "zip": "Amazon-GoogleProducts.zip",
        "sha256": "fcd72e223d51ce5b0d6b1d68034a438ba95cf2940431e209a57910b067cc4811",
        "left": ("Amazon.csv", {"name": "title", "description": "description",
                                "manufacturer": "manufacturer", "price": "price"}),
        "right": ("GoogleProducts.csv", {"name": "name", "description": "description",
                                         "manufacturer": "manufacturer", "price": "price"}),
        "gold": ("Amzon_GoogleProducts_perfectMapping.csv", "idAmazon", "idGoogleBase"),
    },
}


def rows(z: zipfile.ZipFile, name: str) -> list[dict]:
    raw = z.read(name)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return list(csv.DictReader(io.StringIO(text)))


def fetch(name: str, spec: dict) -> None:
    data = urllib.request.urlopen(BASE + spec["zip"], timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        sys.exit(f"{spec['zip']}: checksum {digest} does not match {spec['sha256']}; not using it")
    z = zipfile.ZipFile(io.BytesIO(data))
    out = HERE / name
    out.mkdir(exist_ok=True)
    for side in ("left", "right"):
        file, fields = spec[side]
        with open(out / f"{side}.jsonl", "w") as f:
            for r in rows(z, file):
                rec = {"id": f"{side[0]}:{r['id'].strip()}"}
                rec.update({k: (r.get(src) or "").strip() for k, src in fields.items()})
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    file, lcol, rcol = spec["gold"]
    with open(out / "gold.jsonl", "w") as f:
        for r in rows(z, file):
            f.write(json.dumps({"left": f"l:{r[lcol].strip()}", "right": f"r:{r[rcol].strip()}"}) + "\n")
    print(f"{name}: written to {out}")


if __name__ == "__main__":
    for name in sys.argv[1:] or DATASETS:
        fetch(name, DATASETS[name])
