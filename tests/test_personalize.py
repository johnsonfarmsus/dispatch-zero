from dispatchzero.services.personalize import OPERATIVE_TOKEN, personalize_operative


def test_substitutes_canonical_token():
    assert personalize_operative("Operative {operative}, proceed.", "82juliet") == (
        "Operative 82juliet, proceed."
    )


def test_substitutes_all_occurrences():
    out = personalize_operative("{operative}: {operative} again", "X9")
    assert out == "X9: X9 again"


def test_tolerates_mangled_delimiters_and_case():
    # Small models mangle the token; all variants resolve to the call sign.
    for variant in ("[operative]", "<operative>", "{ operative }", "{OPERATIVE}"):
        assert personalize_operative(f"hello {variant}", "Zed") == "hello Zed"


def test_bare_word_operative_is_left_alone():
    # No delimiters => generic address, nothing to inject.
    assert personalize_operative("Listen, operative.", "Zed") == "Listen, operative."


def test_passthrough_without_token():
    # Old pre-token briefings (and any text) pass through untouched.
    text = "Operative 42juliet, your task is at the silo."
    assert personalize_operative(text, "82juliet") == text


def test_none_and_empty_are_safe():
    assert personalize_operative(None, "X") is None
    assert personalize_operative("", "X") == ""


def test_token_constant_is_what_the_matcher_accepts():
    assert personalize_operative(f"a {OPERATIVE_TOKEN} b", "Q") == "a Q b"
