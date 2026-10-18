import pytest

from osm_direction import Flag, Verdict, parse, parse_tags


def one(value):
    r = parse(value)
    assert r.verdict is Verdict.OK, r
    assert len(r.directions) == 1, r
    return r.directions[0]


# Missing


@pytest.mark.parametrize("value", [None, "", "   ", ";"])
def test_missing_or_empty(value):
    r = parse(value)
    assert r.verdict in (Verdict.MISSING, Verdict.UNPARSEABLE)
    assert r.directions == ()


def test_none_is_missing():
    assert parse(None).verdict is Verdict.MISSING


# Single numbers


@pytest.mark.parametrize(
    "value, bearing",
    [("90", 90.0), ("90.5", 90.5), (" 90 ", 90.0), ("045", 45.0), (".5", 0.5), ("359", 359.0)],
)
def test_degrees(value, bearing):
    d = one(value)
    assert d.bearing == bearing
    assert d.width is None
    assert d.flags == frozenset()


@pytest.mark.parametrize("value, bearing", [("360", 0.0), ("-90", 270.0), ("-35", 325.0), ("-360", 0.0)])
def test_out_of_range_is_wrapped_and_flagged(value, bearing):
    d = one(value)
    assert d.bearing == bearing
    assert Flag.NORMALIZED in d.flags


@pytest.mark.parametrize("value", ["2755", "361", "-361", "1e3", "nan", "inf"])
def test_far_out_of_range_is_not_guessed(value):
    assert parse(value).verdict is Verdict.UNPARSEABLE


@pytest.mark.parametrize("value", ["90°", "90 °", "90deg", "90 degrees"])
def test_degree_sign_is_nonstandard(value):
    d = one(value)
    assert d.bearing == 90.0
    assert Flag.NONSTANDARD in d.flags


# The placeholder zero


@pytest.mark.parametrize("value", ["0", "0.0", "000", "+0", "-0"])
def test_bare_zero_is_reported_as_north_and_flagged(value):
    d = one(value)
    assert d.bearing == 0.0
    assert d.suspect_placeholder


def test_zero_inside_a_list_is_flagged():
    r = parse("90;0")
    assert r.bearings == (90.0, 0.0)
    assert not r.directions[0].suspect_placeholder
    assert r.directions[1].suspect_placeholder


@pytest.mark.parametrize("value", ["N", "360", "1", "359"])
def test_other_northish_values_are_not_flagged(value):
    assert not one(value).suspect_placeholder


@pytest.mark.parametrize("value", ["338-23", "337-22", "315-45", "N-N"])
def test_range_centered_on_north(value):
    d = one(value)
    if value == "N-N":
        # A range of nothing written with a compass point: deliberate, not a placeholder.
        assert not d.suspect_placeholder
    else:
        assert d.suspect_placeholder
        assert d.width is not None


def test_omnidirectional_range_is_not_a_placeholder():
    d = one("0-360")
    assert d.width == 360.0
    assert not d.suspect_placeholder


# Compass points


@pytest.mark.parametrize("value, bearing", [("N", 0.0), ("NE", 45.0), ("NNW", 337.5), ("WSW", 247.5)])
def test_cardinals(value, bearing):
    d = one(value)
    assert d.bearing == bearing
    assert d.flags == frozenset({Flag.CARDINAL})


def test_lowercase_cardinal_is_nonstandard():
    d = one("se")
    assert d.bearing == 135.0
    assert d.flags == frozenset({Flag.CARDINAL, Flag.NONSTANDARD})


@pytest.mark.parametrize("value", ["NEE", "X", "north", "NESW"])
def test_bad_cardinals(value):
    assert parse(value).verdict is Verdict.UNPARSEABLE


# Ranges


def test_range():
    d = one("90-180")
    assert (d.bearing, d.width, d.start, d.end) == (135.0, 90.0, 90.0, 180.0)
    assert Flag.RANGE in d.flags


def test_range_wrapping_through_north():
    d = one("330-15")
    assert d.width == 45.0
    assert d.bearing == pytest.approx(352.5)
    assert (d.start, d.end) == (330.0, 15.0)


def test_range_is_clockwise():
    # 180-90 means clockwise from 180 round to 90: 270 degrees wide.
    d = one("180-90")
    assert d.width == 270.0
    assert d.bearing == 315.0


@pytest.mark.parametrize("value", ["0-360", "360-0", "0 - 360"])
def test_all_round(value):
    d = one(value)
    assert d.width == 360.0
    assert Flag.NORMALIZED not in d.flags


def test_zero_width_range_reports_the_bearing():
    d = one("90-90")
    assert d.bearing == 90.0
    assert d.width is None
    assert Flag.NONSTANDARD in d.flags


def test_cardinal_range():
    d = one("N-E")
    assert (d.bearing, d.width) == (45.0, 90.0)
    assert Flag.CARDINAL in d.flags


@pytest.mark.parametrize("value", ["90-", "-", "90-180-270", "90-400"])
def test_bad_ranges(value):
    assert parse(value).verdict is Verdict.UNPARSEABLE


def test_list_of_ranges():
    r = parse("110-180;152-222")
    assert [d.width for d in r.directions] == [70.0, 70.0]


# Lists


def test_list():
    r = parse("90;270")
    assert r.bearings == (90.0, 270.0)
    assert r.flags == frozenset()


def test_list_with_negative():
    assert parse("-10;170").bearings == (350.0, 170.0)


def test_mixed_list():
    r = parse("180;nw")
    assert r.bearings == (180.0, 315.0)


def test_empty_list_item_is_nonstandard():
    r = parse("90;;180;")
    assert r.verdict is Verdict.OK
    assert r.bearings == (90.0, 180.0)
    assert Flag.NONSTANDARD in r.flags


def test_duplicates_are_flagged():
    r = parse("0;0;0")
    assert r.bearings == (0.0, 0.0, 0.0)
    assert [Flag.DUPLICATE in d.flags for d in r.directions] == [False, True, True]
    assert all(d.suspect_placeholder for d in r.directions)


def test_partial():
    r = parse("90;banana;180")
    assert r.verdict is Verdict.PARTIAL
    assert r.bearings == (90.0, 180.0)
    assert r.unparsed == ("banana",)


# Commas


@pytest.mark.parametrize(
    "value, bearings",
    [("150, 310", (150.0, 310.0)), ("30, 190, 330,", (30.0, 190.0, 330.0)), ("1,2,3", (1.0, 2.0, 3.0))],
)
def test_unambiguous_comma_lists(value, bearings):
    r = parse(value)
    assert r.verdict is Verdict.OK
    assert r.bearings == bearings
    assert Flag.NONSTANDARD in r.flags


@pytest.mark.parametrize("value", ["90,5", "90,270", "90.5, 270", "N, S"])
def test_ambiguous_commas_are_not_guessed(value):
    # "90,5" might be a decimal comma. Only plain whole numbers count as a
    # comma list, and a pair needs a space after the comma.
    assert parse(value).verdict is Verdict.UNPARSEABLE


# Relative


@pytest.mark.parametrize("value", ["forward", "backward", "both"])
def test_relative(value):
    d = one(value)
    assert d.bearing is None
    assert d.relative == value
    assert Flag.RELATIVE in d.flags


def test_relative_has_no_bearing():
    assert parse("forward").bearings == ()


def test_relative_case():
    d = one("Forward")
    assert d.relative == "forward"
    assert Flag.NONSTANDARD in d.flags


# parse_tags


def test_tags_missing():
    r = parse_tags({"man_made": "surveillance"})
    assert r.verdict is Verdict.MISSING
    assert r.sources == {}


def test_tags_empty_value_is_missing():
    r = parse_tags({"direction": ""})
    assert r.verdict is Verdict.MISSING
    assert "direction" in r.sources


def test_tags_one_key():
    r = parse_tags({"camera:direction": "45"})
    assert r.verdict is Verdict.OK
    assert r.bearings == (45.0,)
    assert r.raw == "45"
    assert set(r.sources) == {"camera:direction"}


def test_tags_agree():
    r = parse_tags({"direction": "90", "camera:direction": "90.4"})
    assert r.verdict is Verdict.OK
    assert r.bearings == (90.0,)


def test_tags_conflict_keeps_both():
    r = parse_tags({"direction": "90", "camera:direction": "270"})
    assert r.verdict is Verdict.CONFLICT
    assert r.bearings == (90.0, 270.0)
    assert r.sources["direction"].bearings == (90.0,)


def test_tags_tolerance():
    tags = {"direction": "90", "camera:direction": "93"}
    assert parse_tags(tags).verdict is Verdict.CONFLICT
    assert parse_tags(tags, tolerance=5).verdict is Verdict.OK


def test_tags_unreadable_second_key_is_not_dropped():
    r = parse_tags({"direction": "90", "camera:direction": "banana"})
    assert r.verdict is Verdict.PARTIAL
    assert r.bearings == (90.0,)
    assert r.unparsed == ("banana",)


def test_tags_all_unreadable():
    r = parse_tags({"direction": "banana"})
    assert r.verdict is Verdict.UNPARSEABLE


def test_tags_custom_keys():
    r = parse_tags({"light:direction": "180"}, keys=("light:direction",))
    assert r.bearings == (180.0,)


def test_wrapped_values_are_in_range():
    for v in ["0", "359.9999999", "-0.0000001", "360", "-360", "0-360", "359-1"]:
        for d in parse(v).directions:
            assert d.bearing is None or 0 <= d.bearing < 360
            for edge in (d.start, d.end):
                assert edge is None or 0 <= edge < 360
