"""Parse every real direction value in tests/data/census.tsv.

The census holds every distinct value found on surveillance nodes in several
US states (see scripts/census.py). This test pins down which values can't be
read, so a change in what the parser accepts shows up here on purpose.
"""

from pathlib import Path

import pytest

from osm_direction import Verdict, parse

CENSUS = Path(__file__).parent / "data" / "census.tsv"

# Values the parser deliberately refuses to guess at.
EXPECTED_UNREADABLE = {
    # "Eastbound" etc.: the traffic watched, not the way the camera faces,
    # and a plate reader can face either way along the road.
    "EB", "NB", "SB", "WB",
    # Beyond one turn: typos, or lists missing their separators.
    "370", "500", "550", "557", "600", "620", "680", "690", "801", "950",
    "1000", "1605", "1610", "2400", "2755", "3525", "9100",
    "27070", "90100", "180280", "270230", "90180270", "65534559",
    "450;470;495",
    # Pasted junk.
    "150WY39-J963-T96Q-9KE6-9DR9", "280WY39-J963-T96Q-9KE6-9DR9",
}

# Values only partly readable: the out-of-range or garbled items are dropped.
EXPECTED_PARTIAL = {
    "370;190", "370;200", "1200;340", "150;275;385", "230;1230",
    "75;375;500", "345;270:360",
}


def census():
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        count, key, value = line.split("\t", 2)
        yield int(count), key, value


@pytest.mark.skipif(not CENSUS.exists(), reason="no census file")
def test_every_census_value():
    unreadable, partial = set(), set()
    for _, _, value in census():
        r = parse(value)
        for d in r.directions:
            assert d.bearing is None or 0 <= d.bearing < 360, value
            assert d.width is None or 0 < d.width <= 360, value
        if r.verdict is Verdict.UNPARSEABLE:
            unreadable.add(value)
        elif r.verdict is Verdict.PARTIAL:
            partial.add(value)
    assert unreadable == EXPECTED_UNREADABLE
    assert partial == EXPECTED_PARTIAL
