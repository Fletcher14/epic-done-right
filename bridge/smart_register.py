#!/usr/bin/env python3
"""
One-time setup for SMART Backend Services against the SMART reference sandbox.

Generates an RSA keypair, publishes the public half as a JWKS during registration,
and writes the resulting client_id + key path to secrets/smart.env.

    python bridge/smart_register.py

The private key never leaves this machine; the server only ever sees the public
JWKS and, per request, a JWT signed with the private half. That asymmetry is the
entire point of the profile -- there is no shared secret to leak.
"""
import base64
import json
import os
import sys
import uuid

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SANDBOX = os.environ.get("SMART_SANDBOX", "https://bulk-data.smarthealthit.org")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SECRETS = os.path.join(ROOT, "secrets")


def _b64u(i):
    return base64.urlsafe_b64encode(
        i.to_bytes((i.bit_length() + 7) // 8, "big")).decode().rstrip("=")


def main():
    os.makedirs(SECRETS, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    kid = uuid.uuid4().hex[:16]
    jwks = {"keys": [{"kty": "RSA", "alg": "RS384", "use": "sig", "kid": kid,
                      "n": _b64u(pub.n), "e": _b64u(pub.e)}]}

    key_path = os.path.join(SECRETS, "smart-key.pem")
    with open(key_path, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    os.chmod(key_path, 0o600)

    r = requests.post(f"{SANDBOX}/auth/register", timeout=25,
                      data={"jwks": json.dumps(jwks), "dur": "15"})
    r.raise_for_status()
    client_id = r.text.strip()

    env_path = os.path.join(SECRETS, "smart.env")
    with open(env_path, "w") as fh:
        fh.write(f"SMART_TOKEN_URL={SANDBOX}/auth/token\n"
                 f"SMART_CLIENT_ID={client_id}\n"
                 f"SMART_PRIVATE_KEY={os.path.abspath(key_path)}\n"
                 f"SMART_KID={kid}\n"
                 f"SMART_SCOPE=system/*.read\n")
    os.chmod(env_path, 0o600)
    print(f"registered with {SANDBOX}")
    print(f"  private key -> {key_path}  (0600, never transmitted)")
    print(f"  config      -> {env_path}")
    print(f"  client_id   -> {len(client_id)} chars")
    print("\nUse it:  set -a && . secrets/smart.env && set +a && python bridge/smart_check.py")


if __name__ == "__main__":
    sys.exit(main())
