"""Tests for token encryption at rest."""
from dispatchzero.config import get_settings
from dispatchzero.crypto import decrypt_token, encrypt_token


def test_round_trip():
    plain = "test-access-token-abc123"
    enc = encrypt_token(plain)
    assert enc != plain
    assert decrypt_token(enc) == plain


def test_ciphertext_is_not_plaintext():
    enc = encrypt_token("secret")
    assert "secret" not in enc


def test_legacy_plaintext_passthrough():
    # A pre-encryption plaintext token (doesn't start with the Fernet
    # version prefix) should be returned unchanged, not error.
    assert decrypt_token("plain-legacy-token") == "plain-legacy-token"


def test_empty_passthrough():
    assert decrypt_token("") == ""


def test_distinct_ciphertexts_for_same_plaintext():
    # Fernet includes a random IV + timestamp, so two encryptions of the
    # same plaintext differ but both decrypt back.
    a = encrypt_token("same")
    b = encrypt_token("same")
    assert a != b
    assert decrypt_token(a) == decrypt_token(b) == "same"


def test_key_derived_from_session_secret(monkeypatch):
    # A token encrypted under one secret should NOT decrypt (cleanly) under
    # a different secret — it falls back to passthrough rather than crash.
    enc = encrypt_token("tied-to-secret")
    monkeypatch.setenv("SESSION_SECRET", "a-completely-different-secret-value-32x")
    get_settings.cache_clear()
    # Wrong key -> InvalidToken -> passthrough of the raw ciphertext.
    assert decrypt_token(enc) == enc
