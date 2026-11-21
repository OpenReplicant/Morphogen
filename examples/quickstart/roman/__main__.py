import json
import sys

from roman.core import to_roman

print(to_roman(json.load(sys.stdin)["n"]))
