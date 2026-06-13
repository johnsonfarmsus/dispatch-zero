from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# A real argon2 hash of a throwaway value. dummy_verify() runs a verify
# against this so the login path spends the same CPU time whether or not
# the callsign exists, closing the user-enumeration timing oracle. Computed
# once at import.
_DUMMY_HASH = _hasher.hash("dispatch-zero-timing-equalizer")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def dummy_verify() -> None:
    """Burn the same argon2 verification cost as a real password check,
    discarding the result. Call this on the 'callsign not found' branch of
    login so response timing doesn't reveal whether an account exists."""
    try:
        _hasher.verify(_DUMMY_HASH, "wrong-password")
    except Exception:
        pass
