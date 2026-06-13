"""Unit tests for the OSM tag-mapping pure functions.

These have no DB or network dependency — they're the cheapest, highest-payoff
coverage for the OSM round-trip. They lock in the tag bundles we emit to
OpenStreetMap so a future edit can't silently change what we publish.
"""
from dispatchzero.services import osm_tagging


class TestTagsForPublish:
    def test_mural_simple_mapping(self):
        tags = osm_tagging.tags_for_publish(category="mural", place_name="Combine Mural")
        assert tags["tourism"] == "artwork"
        assert tags["artwork_type"] == "mural"
        assert tags["name"] == "Combine Mural"
        assert tags["source"] == "survey;Dispatch Zero"
        assert "source:date" in tags

    def test_church_gets_christian_default(self):
        tags = osm_tagging.tags_for_publish(category="church", place_name="First Pres")
        assert tags["amenity"] == "place_of_worship"
        assert tags["religion"] == "christian"

    def test_civic_post_office(self):
        tags = osm_tagging.tags_for_publish(category="civic", place_name="Harrington PO")
        assert tags["amenity"] == "post_office"

    def test_ambiguous_category_returns_none_without_picker(self):
        # historic + infrastructure require a subtype pick before publish.
        assert osm_tagging.tags_for_publish(category="historic", place_name="X") is None
        assert osm_tagging.tags_for_publish(category="infrastructure", place_name="X") is None

    def test_ambiguous_category_with_picker_choice(self):
        tags = osm_tagging.tags_for_publish(
            category="infrastructure", place_name="John Day Dam",
            picker_choice="dam",
        )
        assert tags["waterway"] == "dam"
        assert tags["name"] == "John Day Dam"

    def test_ambiguous_category_with_bad_picker_choice_returns_none(self):
        assert osm_tagging.tags_for_publish(
            category="infrastructure", place_name="X", picker_choice="not_a_real_option",
        ) is None

    def test_unknown_category_returns_none(self):
        assert osm_tagging.tags_for_publish(category="banana", place_name="X") is None

    def test_external_wikipedia_link_becomes_wikipedia_tag(self):
        tags = osm_tagging.tags_for_publish(
            category="mural", place_name="X",
            external_link="https://en.wikipedia.org/wiki/Harrington,_Washington",
        )
        assert tags["wikipedia"] == "en:Harrington, Washington"
        assert "website" not in tags

    def test_external_non_wikipedia_link_becomes_website_tag(self):
        tags = osm_tagging.tags_for_publish(
            category="mural", place_name="X",
            external_link="https://example.com/the-mural",
        )
        assert tags["website"] == "https://example.com/the-mural"
        assert "wikipedia" not in tags

    def test_wp_sourced_place_auto_derives_wikipedia_tag(self):
        # No user link, but the place itself came from Wikipedia (osm_type='wp').
        tags = osm_tagging.tags_for_publish(
            category="historic", place_name="Egypt Church",
            picker_choice="building", place_osm_type="wp",
        )
        assert tags["wikipedia"] == "en:Egypt Church"

    def test_user_link_wins_over_auto_derivation(self):
        tags = osm_tagging.tags_for_publish(
            category="mural", place_name="Some Place",
            external_link="https://de.wikipedia.org/wiki/Berlin",
            place_osm_type="wp",
        )
        # The explicit user link should beat the place-name auto-derivation.
        assert tags["wikipedia"] == "de:Berlin"

    def test_junk_external_link_is_dropped(self):
        tags = osm_tagging.tags_for_publish(
            category="mural", place_name="X", external_link="not a url",
        )
        assert "wikipedia" not in tags
        assert "website" not in tags

    def test_wikidata_qid_attached_when_valid(self):
        tags = osm_tagging.tags_for_publish(
            category="mural", place_name="X", wikidata_id="Q12345",
        )
        assert tags["wikidata"] == "Q12345"

    def test_malformed_wikidata_qid_dropped(self):
        for bad in ("12345", "Q", "P31", "Q12a", "", "  Q1 "):
            tags = osm_tagging.tags_for_publish(
                category="mural", place_name="X", wikidata_id=bad,
            )
            assert "wikidata" not in tags, f"should have dropped {bad!r}"


class TestAmbiguity:
    def test_is_ambiguous(self):
        assert osm_tagging.is_ambiguous("historic")
        assert osm_tagging.is_ambiguous("infrastructure")
        assert not osm_tagging.is_ambiguous("mural")
        assert not osm_tagging.is_ambiguous("church")

    def test_picker_choices_shape(self):
        choices = osm_tagging.picker_choices("infrastructure")
        assert choices is not None
        values = {c["value"] for c in choices}
        assert "bridge" in values
        assert "dam" in values
        assert osm_tagging.picker_choices("mural") is None


class TestChangesetComment:
    def test_comment_includes_name_and_category(self):
        c = osm_tagging.changeset_comment(place_name="Combine Mural", category="mural")
        assert "Combine Mural" in c
        assert "mural" in c
        assert "Dispatch Zero" in c

    def test_comment_without_name(self):
        c = osm_tagging.changeset_comment(place_name="", category="mural")
        assert "mural" in c
