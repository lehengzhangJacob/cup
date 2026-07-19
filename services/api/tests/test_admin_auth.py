from __future__ import annotations

from app.admin_auth import create_admin_token, verify_admin_token


def test_signed_admin_token_round_trip_and_tamper_rejection():
    token = create_admin_token()
    assert verify_admin_token(token) is True
    replacement = "0" if token[-1] != "0" else "1"
    assert verify_admin_token(token[:-1] + replacement) is False


def test_malformed_admin_tokens_are_rejected():
    assert verify_admin_token(None) is False
    assert verify_admin_token("") is False
    assert verify_admin_token("not-a-session") is False
    assert verify_admin_token("bad.payload") is False
