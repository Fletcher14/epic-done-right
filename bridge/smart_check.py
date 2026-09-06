#!/usr/bin/env python3
"""Prove the configured SMART credentials actually obtain a token."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart  # noqa: E402

auth = smart.from_env()
if not auth:
    print("SMART not configured — set SMART_TOKEN_URL / SMART_CLIENT_ID / SMART_PRIVATE_KEY")
    sys.exit(1)
tok = auth.token()
print(f"✅ access token acquired — {len(tok)} chars, scope {auth.scope}")
print(f"   cached until {auth._expires_at - __import__('time').time():.0f}s from now")
print(f"   second call served from cache: {auth.token() == tok}")
