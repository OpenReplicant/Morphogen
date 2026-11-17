"""Case custody when there is nowhere private to keep the cases: seal each case set with AES-256-GCM
under a key held only as a secret of the trusted jobs, and keep the sealed files anywhere, even in a
public branch. The sealed file names its case set and version in the authenticated header, so a
sealed set cannot be swapped for another or edited without the key.

    python -m judge.custody seal --key-env K --plain DIR --sealed DIR    every <set>/cases.jsonl
    python -m judge.custody open --key-env K --sealed DIR --plain DIR    every <set>/cases.jsonl.sealed

The key is any secret string of at least 32 characters; scrypt turns it into the AES key with a fresh
salt per file. `open` refuses a file that fails authentication.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = "morphogen.sealed/v1"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def _key(secret, salt):
    if len(secret) < 32:
        raise SystemExit("the case key must be at least 32 characters")
    return Scrypt(salt=salt, length=32, **SCRYPT).derive(secret.encode())


def seal_bytes(secret, set_name, plaintext):
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {"format": FORMAT, "set": set_name, "kdf": "scrypt", **SCRYPT,
              "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode()}
    aad = json.dumps(header, sort_keys=True).encode()
    ct = AESGCM(_key(secret, salt)).encrypt(nonce, plaintext, aad)
    return json.dumps({"header": header, "ciphertext": base64.b64encode(ct).decode()}).encode()


def open_bytes(secret, set_name, sealed):
    doc = json.loads(sealed)
    header = doc["header"]
    if header.get("format") != FORMAT or header.get("set") != set_name:
        raise SystemExit(f"sealed file is not case set {set_name!r}")
    aad = json.dumps(header, sort_keys=True).encode()
    key = _key(secret, base64.b64decode(header["salt"]))
    try:
        return AESGCM(key).decrypt(base64.b64decode(header["nonce"]), base64.b64decode(doc["ciphertext"]), aad)
    except Exception:
        raise SystemExit(f"case set {set_name!r} failed authentication: wrong key or tampered file") from None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m judge.custody")
    ap.add_argument("action", choices=["seal", "open"])
    ap.add_argument("--key-env", required=True)
    ap.add_argument("--plain", required=True, type=Path)
    ap.add_argument("--sealed", required=True, type=Path)
    a = ap.parse_args(argv)
    secret = os.environ.get(a.key_env, "")
    n = 0
    if a.action == "seal":
        for f in sorted(a.plain.glob("*/cases.jsonl")):
            out = a.sealed / f.parent.name / "cases.jsonl.sealed"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(seal_bytes(secret, f.parent.name, f.read_bytes()))
            n += 1
    else:
        for f in sorted(a.sealed.glob("*/cases.jsonl.sealed")):
            out = a.plain / f.parent.name / "cases.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(open_bytes(secret, f.parent.name, f.read_bytes()))
            n += 1
    print(f"{a.action}: {n} case set(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
