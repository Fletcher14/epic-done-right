"""
SMART on FHIR -- Backend Services authentication.

This bridge is a SYSTEM talking to a system. No clinician clicks anything: a unit
gets dispatched and the bridge pulls on its own. That makes this the
*Backend Services* profile (`client_credentials` + an asymmetric signed JWT),
not the App Launch profile (authorization code + a user session). Picking the
wrong one of those two is the most common misunderstanding of SMART, and Epic
gates production access on getting it right.

Flow:
    private key ──▶ signed JWT assertion (RS384, kid) ──▶ POST client_credentials
                 ──▶ short-lived access token ──▶ Authorization: Bearer on FHIR calls

Auth is OPTIONAL and off by default: with no SMART_* environment set, the bridge
behaves exactly as before against the local mock or a public open server. That
keeps `docker compose up` working for anyone who clones this.
"""
import json
import os
import time
import uuid

import requests

try:
    import jwt as pyjwt
except ImportError:      # optional dependency -- auth simply stays unavailable
    pyjwt = None

TOKEN_SKEW = 30          # refresh this many seconds before actual expiry


class SmartAuth:
    """Holds a private key and vends cached bearer tokens."""

    def __init__(self, token_url, client_id, private_key_pem, kid=None,
                 scope="system/*.read", algorithm="RS384"):
        if pyjwt is None:
            raise RuntimeError("pyjwt is required for SMART auth (pip install pyjwt cryptography)")
        self.token_url = token_url
        self.client_id = client_id
        self.private_key_pem = private_key_pem
        self.kid = kid
        self.scope = scope
        self.algorithm = algorithm
        self._token = None
        self._expires_at = 0.0

    def _assertion(self, now=None):
        """The signed JWT proving we hold the private key for the registered JWKS.

        aud MUST be the token endpoint, and jti must be unique -- servers reject
        replays. Kept short-lived deliberately; it is a single-use credential.
        """
        now = int(now or time.time())
        headers = {"kid": self.kid} if self.kid else None
        return pyjwt.encode(
            {"iss": self.client_id, "sub": self.client_id, "aud": self.token_url,
             "exp": now + 300, "jti": uuid.uuid4().hex},
            self.private_key_pem, algorithm=self.algorithm, headers=headers)

    def token(self):
        """A valid access token, fetched only when the cached one is near expiry."""
        if self._token and time.time() < self._expires_at:
            return self._token
        resp = requests.post(self.token_url, timeout=20, data={
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": self._assertion(),
            "scope": self.scope})
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + max(0, int(body.get("expires_in", 300)) - TOKEN_SKEW)
        return self._token

    def headers(self):
        return {"Authorization": f"Bearer {self.token()}"}


def from_env():
    """Build a SmartAuth from environment, or None when unconfigured (the default)."""
    client_id = os.environ.get("SMART_CLIENT_ID")
    token_url = os.environ.get("SMART_TOKEN_URL")
    key_path = os.environ.get("SMART_PRIVATE_KEY")
    if not (client_id and token_url and key_path):
        return None
    with open(key_path) as fh:
        pem = fh.read()
    return SmartAuth(token_url, client_id, pem,
                     kid=os.environ.get("SMART_KID"),
                     scope=os.environ.get("SMART_SCOPE", "system/*.read"))
