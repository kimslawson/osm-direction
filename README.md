# osm-direction

Parse OpenStreetMap `direction` tags into clean bearings, with a verdict on how much to trust each one.

The OSM [`direction`](https://wiki.openstreetmap.org/wiki/Key:direction) tag says which way a camera, sign, viewpoint or bench faces. Real values are messy: degrees, compass points, ranges, lists, negative numbers, commas instead of semicolons, typos, and a lot of `0`s that nobody meant. Every tool that reads the tag ends up writing its own parser. This is one parser, with a test suite built from every distinct value found on surveillance cameras in several US states.

```python
from osm_direction import parse, parse_tags

parse("90;270").bearings                # (90.0, 270.0)
parse("NE").bearings                    # (45.0,)

d = parse("330-15").directions[0]       # a range, clockwise through north
d.bearing, d.width, d.start, d.end      # (352.5, 45.0, 330.0, 15.0)

parse("0").directions[0].suspect_placeholder   # True: see below
parse("2755").verdict                   # Verdict.UNPARSEABLE: a typo, not guessed at

parse_tags({"direction": "90", "camera:direction": "270"}).verdict   # Verdict.CONFLICT
```

Python 3.10 or later, no dependencies.

## What it reads

| Written as | Example | Result |
| --- | --- | --- |
| Degrees | `90`, `90.5`, `045` | bearing 90, 90.5, 45 |
| Compass points (16-point) | `N`, `NE`, `NNW` | bearing 0, 45, 337.5; flagged `cardinal` |
| Ranges, clockwise | `90-180`, `330-15`, `N-E` | bearing is the middle; `width`, `start`, `end` set; flagged `range` |
| All the way round | `0-360` | width 360 |
| Lists | `90;270`, `110-180;152-222` | one direction per item |
| Out of range | `360`, `-90` | wrapped to 0, 270; flagged `normalized` |
| Relative | `forward`, `backward`, `both` | no bearing; `relative` set; flagged `relative` |
| Nonstandard but clear | `se`, `90°`, `150, 310`, `90;;180` | read, and flagged `nonstandard` |

It never guesses. These come back unreadable rather than wrong:

- Numbers beyond one turn either way (`2755`, `370`, `180280`): typos or missing separators, and wrapping them would invent a direction.
- Travel directions (`EB`, `NB`): they name the traffic watched, not the way the camera faces, and a plate reader can face either way along the road.
- Ambiguous commas: `90,5` could be a decimal comma, so a two-item comma list needs a space after the comma, and only whole numbers count.
- Anything else it doesn't recognize. In a list, the readable items are kept and the verdict is `partial`.

## Verdicts and flags

Each `Result` has a `verdict`:

- `ok`: every part was read.
- `missing`: no tag, or an empty one.
- `unparseable`: nothing could be read.
- `partial`: some parts were read; the rest are in `unparsed`.
- `conflict`: from `parse_tags`, when `direction` and `camera:direction` disagree. Both sets of directions are returned, and each key's own result is in `sources`, so you decide which to believe.

Each `Direction` has `flags`: `suspect_placeholder`, `normalized`, `cardinal`, `nonstandard`, `range`, `relative`, `duplicate`.

## Why `0` is flagged

A `direction=0` should mean "faces north." In practice it's often a placeholder: at least one popular editor starts every new camera at 0 and writes it whether or not the mapper set it ([deflock-app#199](https://github.com/FoggedLens/deflock-app/issues/199)), so an unset camera looks exactly like one facing north. Across 62,664 ALPR cameras in seven US states (October 2026):

- A bare `0` occurs 2,964 times, about 38 times as often as the average of the five degrees on either side.
- Inside lists like `90;0`, `0` occurs 1,387 times, more than three times as often as any other value.
- The range `338-23` occurs 112 times; no other range occurs more than 14.

This library still reports `0` as 0 degrees. It doesn't rewrite data, because real north-facing cameras exist and would be lost, and because once editors stop writing placeholders, new `0`s will be real. It adds the `suspect_placeholder` flag, and you choose. A router avoiding cameras might treat a flagged `0` as "direction unknown" and avoid a circle around the camera; a map might draw it as north with a question mark.

Flagged as suspected placeholders:

- a numeric zero (`0`, `0.0`, `000`), alone or in a list
- a range centered within 1 degree of north (`338-23`, which is how that editor writes an unset direction with a 45-degree field of view)

Not flagged: `N` (typed on purpose), `360`, and `0-360` (all the way round).

## Census

`tests/data/census.tsv` lists every distinct `direction` and `camera:direction` value on surveillance nodes in seven US states (California, Colorado, Florida, Georgia, Maine, Massachusetts, Texas; 63,491 nodes, 3,607 distinct values), with counts. 99.9% of uses read cleanly. The test suite parses every line and pins down exactly which values are unreadable, so a change in what the parser accepts is always deliberate. Rebuild it from Overpass responses with `scripts/census.py`.

Census values come from OpenStreetMap, © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright).

## Development

```sh
uv run pytest
```

## License

MIT. Started for [Outis](https://github.com/kimslawson/outis), a navigation app that routes around known license plate reader cameras.
