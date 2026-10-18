"""Count real direction values on OpenStreetMap surveillance nodes.

Writes tests/data/census.tsv: every distinct value of ``direction`` and
``camera:direction``, with how often it occurs. The test suite parses every
line, so new kinds of messy data show up as test changes.

    python scripts/census.py overpass1.json overpass2.json ...

Each input is an Overpass JSON response, for example from:

    [out:json][timeout:180];
    area["name"="Georgia"]["admin_level"="4"]->.a;
    node(area.a)["man_made"="surveillance"];
    out tags;

Values come from OpenStreetMap, (c) OpenStreetMap contributors, ODbL.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

KEYS = ("direction", "camera:direction")
OUT = Path(__file__).resolve().parent.parent / "tests" / "data" / "census.tsv"


def main(paths: list[str]) -> None:
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    nodes = 0
    for path in paths:
        for element in json.loads(Path(path).read_text())["elements"]:
            nodes += 1
            tags = element.get("tags", {})
            for key in KEYS:
                if key in tags:
                    counts[(key, tags[key])] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        f.write("# Direction values on OpenStreetMap surveillance nodes.\n")
        f.write("# (c) OpenStreetMap contributors, ODbL: https://www.openstreetmap.org/copyright\n")
        f.write(f"# {nodes} nodes from {len(paths)} Overpass responses. Columns: count, key, value.\n")
        for (key, value), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            if "\t" in value or "\n" in value:
                continue
            f.write(f"{n}\t{key}\t{value}\n")
    print(f"{len(counts)} distinct values from {nodes} nodes -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
