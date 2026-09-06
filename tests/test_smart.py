"""
SMART Backend Services tests -- deterministic, no network.

These assert the shape of the credential rather than mocking a whole OAuth
server: the assertion's claims are what a real authorization server validates,
and getting `aud` or `jti` wrong is the usual reason a token request is refused.
"""
import time

import pytest

pytest.importorskip("jwt", reason="SMART extras not installed")
pytest.importorskip("cryptography", reason="SMART extras not installed")

import jwt as pyjwt                                        # noqa: E402
from cryptography.hazmat.primitives import serialization   # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import smart  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                         serialization.NoEncryption()).decode()
PUB = _KEY.public_key().public_bytes(serialization.Encoding.PEM,
                                     serialization.PublicFormat.SubjectPublicKeyInfo).decode()
TOKEN_URL = "https://example.org/auth/token"


def _auth(**kw):
    return smart.SmartAuth(TOKEN_URL, "client-123", PEM, kid="abc123", **kw)


def test_unconfigured_environment_yields_no_auth(monkeypatch):
    """Default posture: no SMART env means no auth, so the open demo still runs."""
    for k in ("SMART_CLIENT_ID", "SMART_TOKEN_URL", "SMART_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert smart.from_env() is None


def test_assertion_carries_the_claims_a_server_validates():
    decoded = pyjwt.decode(_auth()._assertion(), PUB, algorithms=["RS384"],
                           audience=TOKEN_URL)
    assert decoded["iss"] == "client-123"
    assert decoded["sub"] == "client-123"      # iss and sub are both the client id
    assert decoded["aud"] == TOKEN_URL         # must be the TOKEN endpoint, not the FHIR base
    assert decoded["exp"] > time.time()
    assert decoded["jti"]                      # unique -- servers reject replays


def test_assertion_is_signed_with_the_registered_kid():
    assert pyjwt.get_unverified_header(_auth()._assertion())["kid"] == "abc123"


def test_each_assertion_has_a_fresh_jti():
    a = _auth()
    j1 = pyjwt.decode(a._assertion(), PUB, algorithms=["RS384"], audience=TOKEN_URL)["jti"]
    j2 = pyjwt.decode(a._assertion(), PUB, algorithms=["RS384"], audience=TOKEN_URL)["jti"]
    assert j1 != j2


def test_token_is_cached_until_near_expiry(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"access_token": "tok-abc", "expires_in": 300}

    def fake_post(url, **kw):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(smart.requests, "post", fake_post)
    a = _auth()
    assert a.token() == "tok-abc"
    assert a.token() == "tok-abc"
    assert len(calls) == 1                      # second call served from cache
    assert a.headers() == {"Authorization": "Bearer tok-abc"}


def test_expired_token_is_refetched(monkeypatch):
    calls = []

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": f"tok-{len(calls)}", "expires_in": 300}

    monkeypatch.setattr(smart.requests, "post",
                        lambda url, **kw: (calls.append(url), _Resp())[1])
    a = _auth()
    a.token()
    a._expires_at = time.time() - 1             # simulate expiry
    a.token()
    assert len(calls) == 2
