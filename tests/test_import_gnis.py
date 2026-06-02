"""Tests for the GNIS importer CLI.

Covers row parsing, category + county filtering, name normalization,
the safety filter, and the idempotent upsert against the places table.
"""
import pytest
from sqlalchemy import select

from dispatchzero.models import Place, PlaceCategory
from dispatchzero.tools import import_gnis


_HEADER = "Feature ID|Feature Name|Feature Class|State Name|County Name|Primary Latitude|Primary Longitude"


def _row(**overrides):
    base = {
        "feature_id": "1000001",
        "name": "Trinity Church",
        "class": "Church",
        "state": "Washington",
        "county": "Lincoln",
        "lat": "47.4808",
        "lng": "-118.2547",
    }
    base.update(overrides)
    return [base["feature_id"], base["name"], base["class"], base["state"],
            base["county"], base["lat"], base["lng"]]


def _idx():
    return {
        "feature_id": 0, "name": 1, "class": 2,
        "county": 4, "lat": 5, "lng": 6,
    }


def test_row_to_place_args_happy_path():
    parsed = import_gnis._row_to_place_args(_row(), _idx())
    assert parsed is not None
    assert parsed["feature_id"] == 1000001
    assert parsed["name"] == "Trinity Church"
    assert parsed["category"] == PlaceCategory.CHURCH
    assert parsed["county"] == "Lincoln"


def test_row_to_place_args_maps_cemetery_to_historic():
    parsed = import_gnis._row_to_place_args(
        _row(name="Oak Hill Cemetery", **{"class": "Cemetery"}), _idx(),
    )
    assert parsed is not None
    assert parsed["category"] == PlaceCategory.HISTORIC
    assert parsed["feature_class"] == "Cemetery"


@pytest.mark.parametrize("feature_class, expected_category", [
    ("Park", PlaceCategory.PARK),
    ("Falls", PlaceCategory.PARK),
    ("Trail", PlaceCategory.PARK),
    ("Dam", PlaceCategory.INFRASTRUCTURE),
    ("Bridge", PlaceCategory.INFRASTRUCTURE),
    ("Tower", PlaceCategory.INFRASTRUCTURE),
    ("Post Office", PlaceCategory.CIVIC),
])
def test_row_to_place_args_maps_new_feature_classes(feature_class, expected_category):
    """Park/Falls/Trail → PARK, Dam/Bridge/Tower → INFRASTRUCTURE, Post Office → CIVIC."""
    parsed = import_gnis._row_to_place_args(
        _row(name=f"Sample {feature_class}", **{"class": feature_class}), _idx(),
    )
    assert parsed is not None, f"{feature_class} should parse"
    assert parsed["category"] == expected_category
    assert parsed["feature_class"] == feature_class


def test_row_to_place_args_drops_bare_class_names_for_new_classes():
    """A 'Park' named literally 'Park' is useless — skip it."""
    for fc in ["Park", "Dam", "Falls", "Tower", "Bridge", "Trail", "Post Office"]:
        assert import_gnis._row_to_place_args(
            _row(name=fc.lower(), **{"class": fc}), _idx(),
        ) is None, f"{fc!r} bare name should be filtered"


def test_row_to_place_args_drops_historical_suffix():
    """GNIS marks demolished/relocated features with '(historical)' — those are dead."""
    assert import_gnis._row_to_place_args(
        _row(name="Old Mill Bridge (historical)", **{"class": "Bridge"}), _idx(),
    ) is None


def test_row_to_place_args_drops_unwanted_class():
    assert import_gnis._row_to_place_args(
        _row(**{"class": "School"}), _idx(),
    ) is None


def test_row_to_place_args_drops_names_in_safety_filter():
    """A 'Church' feature whose name contains 'school' must still be excluded."""
    assert import_gnis._row_to_place_args(
        _row(name="Sunday School Church"), _idx(),
    ) is None


def test_row_to_place_args_drops_unnamed_and_bare_class_names():
    assert import_gnis._row_to_place_args(_row(name=""), _idx()) is None
    assert import_gnis._row_to_place_args(_row(name="Church"), _idx()) is None
    assert import_gnis._row_to_place_args(_row(name="cemetery"), _idx()) is None
    assert import_gnis._row_to_place_args(
        _row(name="Unnamed Cemetery", **{"class": "Cemetery"}), _idx(),
    ) is None


def test_row_to_place_args_handles_garbage_coords():
    assert import_gnis._row_to_place_args(_row(lat="not-a-number"), _idx()) is None
    assert import_gnis._row_to_place_args(_row(lng=""), _idx()) is None


def test_rural_wa_filter_includes_expected_counties():
    rural = import_gnis._COUNTY_FILTERS["rural_wa"]
    # Spot-check Harrington's county and a few neighbors
    assert "Lincoln" in rural
    assert "Adams" in rural
    assert "Whitman" in rural
    # Urban counties should NOT be in the rural filter
    assert "King" not in rural
    assert "Pierce" not in rural
    assert "Spokane" not in rural


def test_sniff_delimiter():
    assert import_gnis._sniff_delimiter("a|b|c\n1|2|3") == "|"
    assert import_gnis._sniff_delimiter("a,b,c\n1,2,3") == ","


def test_find_col_case_and_punctuation_tolerant():
    header = ["Feature ID", "Feature_Name", "feature class"]
    assert import_gnis._find_col(header, "Feature ID") == 0
    assert import_gnis._find_col(header, "feature name") == 1
    assert import_gnis._find_col(header, "Feature Class") == 2


def test_find_col_raises_when_missing():
    with pytest.raises(KeyError):
        import_gnis._find_col(["A", "B"], "nope")


# ---------- DB integration ----------

@pytest.mark.asyncio
async def test_upsert_writes_rows_to_places_table(db_session):
    rows = [
        {
            "feature_id": 2000001,
            "name": "Riverbend Cemetery",
            "category": PlaceCategory.HISTORIC,
            "county": "Lincoln",
            "lat": 47.48,
            "lng": -118.25,
        },
        {
            "feature_id": 2000002,
            "name": "First Methodist Church",
            "category": PlaceCategory.CHURCH,
            "county": "Lincoln",
            "lat": 47.49,
            "lng": -118.26,
        },
    ]
    written = await import_gnis._upsert_places(db_session, rows)
    assert written == 2
    in_db = (
        await db_session.execute(
            select(Place).where(Place.osm_type == "gnis").order_by(Place.osm_id)
        )
    ).scalars().all()
    assert len(in_db) == 2
    assert in_db[0].osm_id == 2000001
    assert in_db[0].name == "Riverbend Cemetery"
    assert in_db[0].category == PlaceCategory.HISTORIC.value
    assert in_db[1].osm_id == 2000002
    assert in_db[1].category == PlaceCategory.CHURCH.value
    # Tag carries the source so we can audit later
    assert in_db[0].tags["source"] == "gnis"
    assert in_db[0].tags["county"] == "Lincoln"


@pytest.mark.asyncio
async def test_upsert_writes_gnis_class_tag_when_present(db_session):
    """The original GNIS feature class is stored in tags for audit/filter use."""
    rows = [{
        "feature_id": 4000001,
        "name": "Bonneville Dam",
        "category": PlaceCategory.INFRASTRUCTURE,
        "feature_class": "Dam",
        "county": "Skamania",
        "lat": 45.6442,
        "lng": -121.9408,
    }]
    await import_gnis._upsert_places(db_session, rows)
    place = (await db_session.execute(
        select(Place).where(Place.osm_id == 4000001)
    )).scalar_one()
    assert place.tags["gnis_class"] == "Dam"
    assert place.category == PlaceCategory.INFRASTRUCTURE.value


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_rerun(db_session):
    """Re-running the importer should overwrite name/category if changed,
    not create duplicate rows."""
    row = {
        "feature_id": 3000001, "name": "Original Name",
        "category": PlaceCategory.CHURCH, "county": "Adams",
        "lat": 47.0, "lng": -118.0,
    }
    await import_gnis._upsert_places(db_session, [row])
    row["name"] = "Updated Name"
    await import_gnis._upsert_places(db_session, [row])

    rows = (
        await db_session.execute(
            select(Place).where(
                Place.osm_type == "gnis", Place.osm_id == 3000001,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Updated Name"
