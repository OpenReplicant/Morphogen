"""Read 'k' on the first line and text after it from stdin; print the top k words as JSON."""

import json
import sys

from topwords import top_words


def main():
    data = sys.stdin.read()
    first, _, text = data.partition("\n")
    print(json.dumps(top_words(text, int(first.strip()))))


if __name__ == "__main__":
    main()
