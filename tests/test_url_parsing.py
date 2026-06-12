"""Unit tests for the URL classifier used by the OSM publish path."""
from dispatchzero.services.url_parsing import normalize_url, parse_wikipedia_link


class TestParseWikipediaLink:
    def test_standard_en_article(self):
        assert parse_wikipedia_link(
            "https://en.wikipedia.org/wiki/Harrington,_Washington"
        ) == ("en", "Harrington, Washington")

    def test_other_language(self):
        assert parse_wikipedia_link("https://de.wikipedia.org/wiki/Berlin") == ("de", "Berlin")

    def test_bare_wikipedia_defaults_to_en(self):
        assert parse_wikipedia_link("https://wikipedia.org/wiki/Foo") == ("en", "Foo")

    def test_url_encoded_title_decoded(self):
        lang, title = parse_wikipedia_link("https://en.wikipedia.org/wiki/Frank_O%27Hara")
        assert lang == "en"
        assert title == "Frank O'Hara"

    def test_non_article_path_rejected(self):
        assert parse_wikipedia_link("https://en.wikipedia.org/wiki/Special:Search") is None

    def test_non_wikipedia_host_rejected(self):
        assert parse_wikipedia_link("https://www.google.com/maps/place/X") is None

    def test_non_http_scheme_rejected(self):
        assert parse_wikipedia_link("ftp://en.wikipedia.org/wiki/Foo") is None
        assert parse_wikipedia_link("javascript:alert(1)") is None

    def test_empty_and_garbage(self):
        assert parse_wikipedia_link("") is None
        assert parse_wikipedia_link("not a url") is None


class TestNormalizeUrl:
    def test_valid_https(self):
        assert normalize_url("https://example.com/x") == "https://example.com/x"

    def test_trims_whitespace(self):
        assert normalize_url("  https://example.com/x  ") == "https://example.com/x"

    def test_rejects_non_http_scheme(self):
        assert normalize_url("javascript:alert(1)") is None
        assert normalize_url("ftp://example.com") is None

    def test_rejects_no_host(self):
        assert normalize_url("https://") is None
        assert normalize_url("not a url") is None

    def test_blank_returns_none(self):
        assert normalize_url("") is None
        assert normalize_url(None) is None
        assert normalize_url("   ") is None
