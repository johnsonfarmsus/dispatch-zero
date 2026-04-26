from dispatchzero.auth.passwords import hash_password, verify_password


def test_hash_password_returns_argon2_string():
    h = hash_password("hunter2hunter2")
    assert h.startswith("$argon2id$")
    assert len(h) > 50


def test_hash_password_is_non_deterministic():
    h1 = hash_password("hunter2hunter2")
    h2 = hash_password("hunter2hunter2")
    assert h1 != h2  # salted


def test_verify_password_accepts_correct():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) is True


def test_verify_password_rejects_wrong():
    h = hash_password("hunter2hunter2")
    assert verify_password("wrong-password!!", h) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("hunter2hunter2", "not-a-real-hash") is False
