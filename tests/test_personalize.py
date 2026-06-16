from dispatchzero.services.personalize import clean_operative_address


def test_passthrough_when_no_token():
    # Current briefings have no placeholder, so they are returned untouched.
    text = "Your task is to capture the essence of Hillcrest Cemetery."
    assert clean_operative_address(text) == text


def test_strips_leading_vocative_with_empty_braces():
    # The exact failure seen in the wild: model emitted bare "{}".
    out = clean_operative_address("Operative {}, your task is to capture it.")
    assert "{}" not in out
    assert "Operative" not in out
    assert out == "Your task is to capture it."


def test_strips_leading_operative_token_vocative():
    out = clean_operative_address("Operative {operative}, your task is clear.")
    assert out == "Your task is clear."


def test_strips_midtext_token_vocative_and_recapitalizes():
    out = clean_operative_address(
        "Return before the first light of dawn. {operative}, do not linger."
    )
    assert "{operative}" not in out
    assert out == "Return before the first light of dawn. Do not linger."


def test_strips_bare_token_without_role_word():
    out = clean_operative_address("{operative}, the rite has begun.")
    assert out == "The rite has begun."


def test_tolerates_mangled_delimiters():
    for variant in ("[operative]", "<operative>", "{ operative }", "{OPERATIVE}"):
        out = clean_operative_address(f"{variant}, proceed to the mark.")
        assert out == "Proceed to the mark."


def test_none_and_empty_are_safe():
    assert clean_operative_address(None) is None
    assert clean_operative_address("") == ""


def test_does_not_touch_legit_text_resembling_prose():
    # No braces/brackets => untouched, including the word "operative" itself.
    text = "The operative word here is patience."
    assert clean_operative_address(text) == text
