import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from dispatchzero.config import get_settings


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="dz_session_v1")


def sign_session(user_id: uuid.UUID) -> str:
    return _serializer().dumps(str(user_id))


def verify_session(cookie: str, max_age_seconds: int) -> uuid.UUID | None:
    try:
        raw = _serializer().loads(cookie, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None
