import json
import sys

from topwords.core import top_words

case = json.load(sys.stdin)
print(json.dumps(top_words(case["text"], case["k"])))
