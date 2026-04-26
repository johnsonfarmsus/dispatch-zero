import time
import uuid

from dispatchzero.auth.sessions import sign_session, verify_session


def test_sign_then_verify_roundtrip():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    assert isinstance(cookie, str) and len(cookie) > 20
    parsed = verify_session(cookie, max_age_seconds=60)
    assert parsed == user_id


def test_verify_rejects_tampered_cookie():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    tampered = cookie[:-2] + "xx"
    assert verify_session(tampered, max_age_seconds=60) is None


def test_verify_rejects_expired_cookie():
    user_id = uuid.uuid4()
    cookie = sign_session(user_id)
    # itsdangerous timestamps are int-seconds; sleep > 2s to safely exceed max_age=1
    time.sleep(2.1)
    assert verify_session(cookie, max_age_seconds=1) is None


def test_verify_rejects_garbage():
    assert verify_session("not-a-real-cookie", max_age_seconds=60) is None
