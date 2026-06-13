"""Symmetric encryption for secrets at rest (currently OSM OAuth tokens).

We use Fernet (AES-128-CBC + HMAC) keyed off a 32-byte value derived from
SESSION_SECRET. Deriving from the existing secret means there's no new key
to manage; the trade-off is that rotating SESSION_SECRET invalidates stored
ciphertexts (acceptable here — the only encrypted data is OSM tokens, which
can be re-obtained by reconnecting OSM).

Threat model: this protects against a DB-read compromise (stolen backup,
SQL-injection elsewhere, filesystem access to the Postgres volume). It does
NOT protect against an attacker who already has the app's environment
(SESSION_SECRET) — that's a full-app compromise, a different blast radius.

Backward compatibility: decrypt_token() falls back to returning the input
unchanged if it isn't a valid Fernet token. This lets pre-encryption
plaintext tokens already in the DB keep working; they get re-encrypted the
next time they're saved.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from dispatchzero.config import get_settings

# Fernet tokens always start with this version byte (0x80) base64-encoded,
# i.e. they begin with 'gA'. Used as a cheap "is this ciphertext?" check so
# we can transparently pass through legacy plaintext.
_FERNET_PREFIX = "gA"


def _fernet() -> Fernet:
    secret = get_settings().session_secret.encode("utf-8")
    # Fernet wants a 32-byte urlsafe-base64 key. SHA256 of the session
    # secret gives us a deterministic 32-byte value; a distinct salt keeps
    # this key independent of any other SHA256(session_secret) use.
    digest = hashlib.sha256(b"dz_token_crypto_v1:" + secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_token(plain: str) -> str:
    """Encrypt a token for storage. Returns urlsafe base64 ciphertext."""
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_token(stored: str) -> str:
    """Decrypt a stored token. If `stored` doesn't look like / isn't a valid
    Fernet token (legacy plaintext from before encryption was added), return
    it unchanged so existing rows keep working."""
    if not stored or not stored.startswith(_FERNET_PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # Not actually ciphertext (or wrong key) — treat as plaintext.
        return stored
