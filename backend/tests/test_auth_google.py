import asyncio

import pytest
from google.auth.exceptions import GoogleAuthError

from backend.auth.google import verify_google_token, InvalidGoogleToken


def test_verify_google_token_returns_user_info_on_success(monkeypatch):
    def fake_verify(token, request, audience):
        assert token == "valid-token"
        return {
            "sub": "google-sub-123",
            "email": "a@example.com",
            "name": "Alice",
            "picture": "http://pic",
        }

    monkeypatch.setattr("backend.auth.google.id_token.verify_oauth2_token", fake_verify)

    info = asyncio.run(verify_google_token("valid-token"))
    assert info.sub == "google-sub-123"
    assert info.email == "a@example.com"
    assert info.name == "Alice"
    assert info.picture == "http://pic"


def test_verify_google_token_raises_on_invalid_token(monkeypatch):
    def fake_verify(token, request, audience):
        raise GoogleAuthError("Token expired")

    monkeypatch.setattr("backend.auth.google.id_token.verify_oauth2_token", fake_verify)

    with pytest.raises(InvalidGoogleToken):
        asyncio.run(verify_google_token("bad-token"))


def test_verify_google_token_refuses_an_unverified_email(monkeypatch):
    def fake_verify(token, request, audience):
        return {"sub": "s", "email": "admin@example.com", "email_verified": False}

    monkeypatch.setattr("backend.auth.google.id_token.verify_oauth2_token", fake_verify)

    with pytest.raises(InvalidGoogleToken):
        asyncio.run(verify_google_token("valid-token"))


def test_verify_google_token_defaults_picture_to_none_when_missing(monkeypatch):
    def fake_verify(token, request, audience):
        return {"sub": "google-sub-456", "email": "b@example.com", "name": "Bob"}

    monkeypatch.setattr("backend.auth.google.id_token.verify_oauth2_token", fake_verify)

    info = asyncio.run(verify_google_token("valid-token"))
    assert info.picture is None
