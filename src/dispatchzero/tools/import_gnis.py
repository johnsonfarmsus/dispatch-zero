"""USGS GNIS importer — load Churches and Cemeteries into the places table.

GNIS (Geographic Names Information System) is a USGS dataset of named
geographic features, public domain. We use it as a fallback location source
for rural areas where OSM and Wikipedia are sparse.

Download a state file from
https://www.usgs.gov/u.s.-board-on-geographic-names/download-gnis-data
and pass it via --file. Pipe- OR comma-delimited; the importer sniffs the
header row and reads by column name so format quirks across GNIS releases
don't break us.

Usage (inside the app container on VPS 2):

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app \\
        python -m dispatchzero.tools.import_gnis \\
        --file /uploads/imports/WA_Features.csv \\
        --counties rural_wa \\
        --categories church,cemetery

Idempotent: re-running upserts (osm_type='gnis', osm_id=feature_id is the
unique key on the places table, same pattern Wikipedia entries use).
"""
import argparse
import asyncio
import csv
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from dispatchzero.db import get_engine
from dispatchzero.models import Place, PlaceCategory
from dispatchzero.services.discovery import _excluded_by_name


# Map GNIS Feature Class → our PlaceCategory.
_CLASS_MAP: dict[str, PlaceCategory] = {
    "Church": PlaceCategory.CHURCH,
    "Cemetery": PlaceCategory.HISTORIC,
}


# Hardcoded rural WA counties — sparse enough that OSM/Wikipedia leave gaps,
# and "rural" enough that GNIS coverage is worth the import. Match by the
# bare county name (no " County" suffix) as GNIS encodes it.
_RURAL_WA_COUNTIES: frozenset[str] = frozenset({
    "Adams", "Asotin", "Columbia", "Douglas", "Ferry", "Garfield",
    "Grant", "Lincoln", "Okanogan", "Pend Oreille", "Stevens", "Whitman",
})


_COUNTY_FILTERS: dict[str, frozenset[str]] = {
    "rural_wa": _RURAL_WA_COUNTIES,
}


def _sniff_delimiter(sample: str) -> str:
    """GNIS files have been pipe- or comma-delimited across releases. Sniff."""
    if "|" in sample.splitlines()[0]:
        return "|"
    return ","


def _find_col(header: list[str], *candidates: str) -> int:
    """Return the index of the first matching column header (case-insensitive,
    whitespace + punctuation tolerant). Raises KeyError if none match."""
    norm_header = [h.strip().lower().replace("_", " ") for h in header]
    for cand in candidates:
        c = cand.strip().lower().replace("_", " ")
        if c in norm_header:
            return norm_header.index(c)
    raise KeyError(f"none of {candidates} found in header {header}")


def _row_to_place_args(row: list[str], idx: dict[str, int]) -> dict | None:
    """Extract Place fields from a GNIS row, or None if invalid/excluded."""
    try:
        feature_id = int(row[idx["feature_id"]].strip())
        name = row[idx["name"]].strip()
        feature_class = row[idx["class"]].strip()
        county = row[idx["county"]].strip()
        lat = float(row[idx["lat"]].strip())
        lng = float(row[idx["lng"]].strip())
    except (ValueError, IndexError, KeyError):
        return None
    if not name or feature_class not in _CLASS_MAP:
        return None
    if _excluded_by_name(name):
        return None
    # Skip ambient-named entries that aren't useful as dispatch targets.
    if name.lower() in {"church", "cemetery"} or name.lower().startswith("unnamed"):
        return None
    return {
        "feature_id": feature_id,
        "name": name,
        "category": _CLASS_MAP[feature_class],
        "county": county,
        "lat": lat,
        "lng": lng,
    }


async def _upsert_places(db, rows: list[dict]) -> int:
    """Upsert GNIS rows into places. Returns number of rows touched."""
    if not rows:
        return 0
    for r in rows:
        stmt = (
            pg_insert(Place)
            .values(
                id=uuid.uuid4(),
                osm_type="gnis",
                osm_id=r["feature_id"],
                name=r["name"],
                category=r["category"].value,
                coordinates=f"SRID=4326;POINT({r['lng']} {r['lat']})",
                tags={"source": "gnis", "county": r["county"]},
                description=None,
                wikidata_id=None,
            )
            .on_conflict_do_update(
                index_elements=["osm_type", "osm_id"],
                set_={
                    "name": r["name"],
                    "category": r["category"].value,
                    "coordinates": f"SRID=4326;POINT({r['lng']} {r['lat']})",
                    "tags": {"source": "gnis", "county": r["county"]},
                },
            )
        )
        await db.execute(stmt)
    await db.commit()
    return len(rows)


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, type=Path,
                        help="Path to the downloaded GNIS state/national CSV/PSV")
    parser.add_argument("--categories", default="church,cemetery",
                        help="Comma list of categories to import (church,cemetery,...)")
    parser.add_argument("--counties", default="rural_wa",
                        help=("Named filter ('rural_wa') or comma list of county names. "
                              "Use 'all' to disable county filtering."))
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + filter but do not write to the DB")
    args = parser.parse_args()

    # Resolve the category filter — map user input to GNIS feature classes.
    cat_aliases = {
        "church": "Church",
        "cemetery": "Cemetery",
    }
    wanted_classes = {cat_aliases[c.strip().lower()] for c in args.categories.split(",")
                      if c.strip().lower() in cat_aliases}
    if not wanted_classes:
        print(f"no recognized categories in {args.categories!r}; aborting")
        return

    # Resolve the county filter.
    if args.counties.lower() == "all":
        county_filter: frozenset[str] | None = None
    elif args.counties.strip().lower() in _COUNTY_FILTERS:
        county_filter = _COUNTY_FILTERS[args.counties.strip().lower()]
    else:
        county_filter = frozenset(c.strip() for c in args.counties.split(",") if c.strip())

    print(f"reading {args.file}")
    print(f"  categories (GNIS classes): {sorted(wanted_classes)}")
    print(f"  counties: {sorted(county_filter) if county_filter else 'ALL'}")

    sample = args.file.open(encoding="utf-8").read(4096)
    delim = _sniff_delimiter(sample)
    print(f"  delimiter: {delim!r}")

    rows_to_insert: list[dict] = []
    seen_classes: dict[str, int] = {}
    rejected = 0

    with args.file.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=delim)
        header = next(reader)
        idx = {
            "feature_id": _find_col(header, "Feature ID", "feature_id"),
            "name": _find_col(header, "Feature Name", "feature name"),
            "class": _find_col(header, "Feature Class", "feature class"),
            "county": _find_col(header, "County Name", "county name", "County"),
            "lat": _find_col(header, "Primary Latitude", "prim lat dec", "lat"),
            "lng": _find_col(header, "Primary Longitude", "prim long dec", "lng"),
        }
        for row in reader:
            feature_class = row[idx["class"]].strip() if len(row) > idx["class"] else ""
            seen_classes[feature_class] = seen_classes.get(feature_class, 0) + 1
            if feature_class not in wanted_classes:
                continue
            if county_filter is not None:
                county = row[idx["county"]].strip() if len(row) > idx["county"] else ""
                if county not in county_filter:
                    continue
            parsed = _row_to_place_args(row, idx)
            if parsed is None:
                rejected += 1
                continue
            rows_to_insert.append(parsed)

    print(f"\nrows matching filters: {len(rows_to_insert)} (rejected {rejected} for name/coord issues)")

    if args.dry_run:
        print("dry-run; not writing")
        # Show a sample
        for r in rows_to_insert[:10]:
            print(f"  {r['category'].value:10s} {r['name']!r:40s} ({r['county']}, "
                  f"{r['lat']:.4f},{r['lng']:.4f})")
        return

    engine = get_engine()
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as db:
        written = await _upsert_places(db, rows_to_insert)
        # Verify
        result = await db.execute(
            select(Place).where(Place.osm_type == "gnis").limit(1)
        )
        first = result.scalar_one_or_none()
    print(f"\nupserted {written} rows. Example DB row: {first}")


if __name__ == "__main__":
    asyncio.run(_main())
