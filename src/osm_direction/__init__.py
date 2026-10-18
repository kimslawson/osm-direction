"""Parse OpenStreetMap direction tags into clean bearings.

``parse`` reads one tag value. ``parse_tags`` reads a node's tags, looking at
``direction`` and ``camera:direction`` by default.

Nothing is rewritten: a value is reported as tagged, and anything doubtful is
flagged so each caller can decide what to do with it. Where a value could only
be read by guessing, it isn't read at all.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

__all__ = [
    "CARDINALS",
    "DEFAULT_KEYS",
    "Direction",
    "Flag",
    "Result",
    "Verdict",
    "parse",
    "parse_tags",
]

__version__ = "0.1.0"

#: 16-point compass, degrees clockwise from north.
CARDINALS: Mapping[str, float] = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5,
    "E": 90.0, "ESE": 112.5, "SE": 135.0, "SSE": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}

#: Keys read by ``parse_tags`` unless told otherwise, in order of preference.
DEFAULT_KEYS: Sequence[str] = ("direction", "camera:direction")

# Relative values used on nodes that sit on a way (stop signs, signals).
_RELATIVE = ("forward", "backward", "both")

# Numbers beyond one turn either way are almost always typos ("2755"), and
# wrapping them would invent a direction.
_LIMIT = 360.0

# A range whose middle is this close to north is flagged as a suspected
# placeholder.
_NORTH_TOLERANCE = 1.0


class Verdict(str, Enum):
    """How much of a value could be read."""

    OK = "ok"
    """Every part was read."""
    MISSING = "missing"
    """No tag, or an empty one."""
    UNPARSEABLE = "unparseable"
    """Nothing could be read."""
    PARTIAL = "partial"
    """Some parts were read and some weren't; see ``Result.unparsed``."""
    CONFLICT = "conflict"
    """Only from ``parse_tags``: two keys were read and disagree."""


class Flag(str, Enum):
    """Something worth knowing about a direction that was read."""

    SUSPECT_PLACEHOLDER = "suspect_placeholder"
    """A numeric ``0``, alone or in a list, or a range centered on north.
    Some editors write these when nobody set a direction, so they can't be
    told apart from a camera that really faces north. The bearing is still
    reported as 0."""
    NORMALIZED = "normalized"
    """A number outside [0, 360) was wrapped into range, e.g. ``360`` or
    ``-90``."""
    CARDINAL = "cardinal"
    """Written as a compass point, e.g. ``NE``."""
    NONSTANDARD = "nonstandard"
    """Readable but not in the documented form: lowercase ``ne``, a degree
    sign, commas between values, an empty list item, or a range of zero
    width."""
    RANGE = "range"
    """Written as a clockwise range ``from-to``; ``Direction.width`` is set."""
    RELATIVE = "relative"
    """``forward``, ``backward`` or ``both``: relative to the way the node
    sits on, so it has no bearing on its own."""
    DUPLICATE = "duplicate"
    """The same direction appears more than once."""


@dataclass(frozen=True)
class Direction:
    """One direction from a tag value."""

    raw: str
    """The part of the tag value this came from."""
    bearing: float | None
    """Degrees clockwise from north, in [0, 360). For a range, its middle.
    ``None`` for relative values."""
    width: float | None = None
    """For a range, its width in degrees, in (0, 360]. ``None`` otherwise."""
    relative: str | None = None
    """``"forward"``, ``"backward"`` or ``"both"``, for relative values."""
    flags: frozenset[Flag] = frozenset()

    @property
    def start(self) -> float | None:
        """Clockwise start of a range, or ``None``."""
        if self.bearing is None or self.width is None:
            return None
        return _wrap(self.bearing - self.width / 2)

    @property
    def end(self) -> float | None:
        """Clockwise end of a range, or ``None``."""
        if self.bearing is None or self.width is None:
            return None
        return _wrap(self.bearing + self.width / 2)

    @property
    def suspect_placeholder(self) -> bool:
        return Flag.SUSPECT_PLACEHOLDER in self.flags


@dataclass(frozen=True)
class Result:
    """Everything read from one tag value, or from a node's tags."""

    raw: str | None
    """The tag value as given. From ``parse_tags`` with several keys, the
    ``key=value`` pairs joined, for the record."""
    verdict: Verdict
    directions: tuple[Direction, ...] = ()
    unparsed: tuple[str, ...] = ()
    """Parts that couldn't be read."""
    sources: Mapping[str, Result] = field(default_factory=dict)
    """From ``parse_tags``: the result for each key that was present."""

    @property
    def flags(self) -> frozenset[Flag]:
        """Every flag on every direction."""
        out: set[Flag] = set()
        for d in self.directions:
            out |= d.flags
        return frozenset(out)

    @property
    def bearings(self) -> tuple[float, ...]:
        """The bearings that have one, in tag order."""
        return tuple(d.bearing for d in self.directions if d.bearing is not None)


_NUMBER_RE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(°|deg|degrees?)?$", re.IGNORECASE)
# Range endpoints are unsigned numbers or compass points: a leading minus
# would be ambiguous with the dash.
_END = r"(?:\d+(?:\.\d*)?|\.\d+|[NSEWnsew]{1,3})"
_RANGE_RE = re.compile(rf"^({_END})\s*°?\s*-\s*({_END})\s*°?$")
_INTEGER_RE = re.compile(r"^\d{1,3}$")


def _wrap(deg: float) -> float:
    w = deg % 360.0
    # Float modulo can round a tiny negative up to exactly 360.0.
    return 0.0 if w >= 360.0 else w


def _angle(a: float, b: float) -> float:
    """Smallest angle between two bearings."""
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


@dataclass(frozen=True)
class _Reading:
    value: float
    """As written, before wrapping (cardinals: their bearing)."""
    flags: frozenset[Flag]
    zero: bool
    """A numeric zero ("0", "0.0", "000")."""


def _number(text: str) -> _Reading | None:
    m = _NUMBER_RE.match(text)
    if not m:
        return None
    value = float(m.group(1))
    if not -_LIMIT <= value <= _LIMIT:
        return None
    flags = set()
    if m.group(2):
        flags.add(Flag.NONSTANDARD)
    if not 0 <= value < 360:
        flags.add(Flag.NORMALIZED)
    return _Reading(value, frozenset(flags), zero=value == 0)


def _cardinal(text: str) -> _Reading | None:
    deg = CARDINALS.get(text.upper())
    if deg is None:
        return None
    flags = {Flag.CARDINAL}
    if text != text.upper():
        flags.add(Flag.NONSTANDARD)
    return _Reading(deg, frozenset(flags), zero=False)


def _part(text: str) -> Direction | None:
    lowered = text.lower()
    if lowered in _RELATIVE:
        flags = {Flag.RELATIVE}
        if text != lowered:
            flags.add(Flag.NONSTANDARD)
        return Direction(raw=text, bearing=None, relative=lowered, flags=frozenset(flags))

    single = _number(text) or _cardinal(text)
    if single is not None:
        flags = set(single.flags)
        if single.zero:
            flags.add(Flag.SUSPECT_PLACEHOLDER)
        return Direction(raw=text, bearing=_wrap(single.value), flags=frozenset(flags))

    m = _RANGE_RE.match(text)
    if not m:
        return None
    a = _number(m.group(1)) or _cardinal(m.group(1))
    b = _number(m.group(2)) or _cardinal(m.group(2))
    if a is None or b is None:
        return None
    flags = {Flag.RANGE} | a.flags | b.flags
    flags.discard(Flag.NORMALIZED)  # 0-360 is the documented way to say "all round"
    width = _wrap(b.value - a.value)
    if width == 0:
        if a.value != b.value:
            width = 360.0  # 0-360: all the way round
        else:
            # 90-90: a range of nothing. Report the bearing alone.
            flags.discard(Flag.RANGE)
            flags.add(Flag.NONSTANDARD)
            return Direction(raw=text, bearing=_wrap(a.value), flags=frozenset(flags))
    bearing = _wrap(a.value + width / 2)
    if width < 360 and _angle(bearing, 0.0) <= _NORTH_TOLERANCE:
        flags.add(Flag.SUSPECT_PLACEHOLDER)
    return Direction(raw=text, bearing=bearing, width=width, flags=frozenset(flags))


def _split(value: str) -> tuple[list[str], bool] | None:
    """Split a value into parts. Returns the parts and whether the split was
    nonstandard, or None if the value is ambiguous."""
    if ";" in value:
        parts = value.split(";")
        return parts, any(not p.strip() for p in parts)
    if "," in value:
        # Commas are not the OSM separator, but "150, 310" is plainly a list.
        # "90,5" could be a decimal comma, so a two-item list of numbers
        # needs a space after the comma before it counts.
        parts = value.split(",")
        items = [p.strip() for p in parts if p.strip()]
        if not all(_INTEGER_RE.match(p) for p in items):
            return None
        if len(items) == 2 and len(parts) == 2 and not parts[1][:1].isspace():
            return None
        return parts, True
    return [value], False


def parse(value: str | None) -> Result:
    """Parse one ``direction``-style tag value.

    >>> parse("90;270").bearings
    (90.0, 270.0)
    >>> parse("337-22").directions[0].width
    45.0
    >>> parse("0").directions[0].suspect_placeholder
    True
    """
    if value is None or not value.strip():
        return Result(raw=value, verdict=Verdict.MISSING)

    split = _split(value)
    if split is None:
        return Result(raw=value, verdict=Verdict.UNPARSEABLE, unparsed=(value.strip(),))
    pieces, nonstandard = split

    directions: list[Direction] = []
    unparsed: list[str] = []
    seen: list[Direction] = []
    for piece in pieces:
        text = piece.strip()
        if not text:
            continue
        d = _part(text)
        if d is None:
            unparsed.append(text)
            continue
        flags = set(d.flags)
        if nonstandard:
            flags.add(Flag.NONSTANDARD)
        if any(_close(d, s, 0.0) for s in seen):
            flags.add(Flag.DUPLICATE)
        seen.append(d)
        directions.append(Direction(d.raw, d.bearing, d.width, d.relative, frozenset(flags)))

    if not directions:
        verdict = Verdict.UNPARSEABLE
    elif unparsed:
        verdict = Verdict.PARTIAL
    else:
        verdict = Verdict.OK
    return Result(raw=value, verdict=verdict, directions=tuple(directions), unparsed=tuple(unparsed))


def parse_tags(
    tags: Mapping[str, str],
    keys: Sequence[str] = DEFAULT_KEYS,
    tolerance: float = 1.0,
) -> Result:
    """Parse a node's direction tags.

    Each key in ``keys`` that is present is parsed, and ``sources`` holds each
    result. Directions are combined in key order without repeats. If two keys
    both yield directions and disagree by more than ``tolerance`` degrees, the
    verdict is ``CONFLICT`` and the caller decides which to believe. Parts no
    key could read are collected in ``unparsed``.

    >>> parse_tags({"direction": "90", "camera:direction": "270"}).verdict
    <Verdict.CONFLICT: 'conflict'>
    """
    sources = {k: parse(tags[k]) for k in keys if k in tags}
    present = {k: r for k, r in sources.items() if r.verdict is not Verdict.MISSING}
    if not present:
        raw = next(iter(sources.values())).raw if sources else None
        return Result(raw=raw, verdict=Verdict.MISSING, sources=sources)

    read = [r for r in present.values() if r.directions]
    combined: list[Direction] = []
    for r in read:
        for d in r.directions:
            if not any(_close(d, c, tolerance) for c in combined):
                combined.append(d)
    unparsed = tuple(p for r in present.values() for p in r.unparsed)
    agree = all(_same(read[0].directions, r.directions, tolerance) for r in read[1:])

    if not read:
        verdict = Verdict.UNPARSEABLE
    elif not agree:
        verdict = Verdict.CONFLICT
    elif unparsed:
        verdict = Verdict.PARTIAL
    else:
        verdict = Verdict.OK
    if len(present) == 1:
        raw = next(iter(present.values())).raw
    else:
        raw = "; ".join(f"{k}={tags[k]}" for k in present)
    return Result(raw, verdict, tuple(combined), unparsed, sources)


def _close(a: Direction, b: Direction, tolerance: float) -> bool:
    if a.relative or b.relative:
        return a.relative == b.relative
    assert a.bearing is not None and b.bearing is not None
    if (a.width is None) != (b.width is None):
        return False
    if a.width is not None and b.width is not None and abs(a.width - b.width) > tolerance:
        return False
    return _angle(a.bearing, b.bearing) <= tolerance


def _same(a: Sequence[Direction], b: Sequence[Direction], tolerance: float) -> bool:
    return all(any(_close(x, y, tolerance) for y in b) for x in a) and all(
        any(_close(y, x, tolerance) for x in a) for y in b
    )
