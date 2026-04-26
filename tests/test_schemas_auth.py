import pytest
from pydantic import ValidationError

from dispatchzero.schemas.auth import LoginIn, SignupIn


def test_signup_accepts_valid_payload():
    s = SignupIn(callsign="Trevor_01", password="hunter2hunter2", adventure_style="agency")
    assert s.callsign == "Trevor_01"


def test_signup_rejects_short_callsign():
    with pytest.raises(ValidationError):
        SignupIn(callsign="ab", password="hunter2hunter2", adventure_style="agency")


def test_signup_rejects_bad_callsign_chars():
    with pytest.raises(ValidationError):
        SignupIn(callsign="hi there", password="hunter2hunter2", adventure_style="agency")


def test_signup_rejects_short_password():
    with pytest.raises(ValidationError):
        SignupIn(callsign="agent01", password="short1", adventure_style="agency")


def test_signup_rejects_unknown_style():
    with pytest.raises(ValidationError):
        SignupIn(callsign="agent01", password="hunter2hunter2", adventure_style="ranger")


def test_login_minimal():
    login = LoginIn(callsign="Trevor_01", password="hunter2hunter2")
    assert login.callsign == "Trevor_01"
