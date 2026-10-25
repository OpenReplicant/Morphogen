"""Fetch the image's downloads for this architecture (downloads.txt), each checked by sha256 before it is kept.

  python3 fetch.py downloads.txt OUT     (in the build; a CA bundle at /run/secrets/ca is trusted if given)
"""
import hashlib
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True, check=True).stdout.strip()
ca = "/run/secrets/ca" if os.path.exists("/run/secrets/ca") and os.path.getsize("/run/secrets/ca") else None
context = ssl.create_default_context(cafile=ca)
opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
wanted = [line.split() for line in Path(sys.argv[1]).read_text().splitlines() if line.strip() and not line.startswith("#")]
mine = [(name, sha, url) for name, a, sha, url in wanted if a == arch]
if not mine:
    raise SystemExit(f"fetch: nothing listed for {arch}")
for name, sha, url in mine:
    for attempt in range(4):
        try:
            with opener.open(url, timeout=120) as r:
                data = r.read()
            break
        except OSError as e:
            if attempt == 3:
                raise SystemExit(f"fetch: {url}: {e}")
    got = hashlib.sha256(data).hexdigest()
    if got != sha:
        raise SystemExit(f"fetch: {name} from {url} has sha256 {got}, not {sha}")
    (out / name).write_bytes(data)
    print(f"fetch: {name} ({arch}) checked")
