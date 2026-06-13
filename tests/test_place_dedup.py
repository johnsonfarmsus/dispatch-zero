"""Tests for conservative cross-source name matching."""
from dispatchzero.services.place_dedup import names_match


class TestNamesMatch:
    def test_exact_match(self):
        assert names_match("Egypt Church", "Egypt Church")

    def test_normalized_match_punctuation_case(self):
        assert names_match("St. Mary's Church", "Saint Mary Church")

    def test_token_reorder_match(self):
        assert names_match("Harrington Opera House", "Opera House, Harrington")

    def test_abbreviation_normalization(self):
        assert names_match("Mt Spokane", "Mount Spokane")

    def test_different_denominations_do_not_match(self):
        # Share only stopword-ish tokens; significant sets differ.
        assert not names_match("First Presbyterian Church", "First Baptist Church")

    def test_single_shared_token_does_not_false_merge(self):
        # Both reduce to {riverside} but full names differ -> no merge.
        assert not names_match("Riverside Park", "Riverside Trail")

    def test_single_token_exact_full_name_matches(self):
        # Same single significant token AND identical full name -> match.
        assert names_match("Egypt Church", "egypt church")

    def test_empty_names_never_match(self):
        assert not names_match("", "Anything")
        assert not names_match("Anything", "")
        assert not names_match("", "")

    def test_unrelated_names_do_not_match(self):
        assert not names_match("Combine Mural", "John Day Dam")
