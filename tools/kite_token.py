#!/usr/bin/env python3
"""Kite Connect Token Helper: Exchange request_token or verify access_token."""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def update_env(key, value):
    lines = []
    found = False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                if k.strip() == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_token(api_key, access_token):
    req = urllib.request.Request(
        "https://api.kite.trade/user/profile",
        headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return True, data.get("data", {})
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode())
            return False, err
        except Exception:
            return False, {"message": str(exc), "status_code": exc.code}
    except Exception as exc:
        return False, {"message": str(exc)}


def verify_margin(api_key, access_token):
    req = urllib.request.Request(
        "https://api.kite.trade/user/margins",
        headers={"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            equity = data.get("data", {}).get("equity", {})
            return equity.get("available", {}).get("live_balance", 0.0)
    except Exception:
        return None


def exchange_request_token(api_key, api_secret, request_token_or_url):
    raw = request_token_or_url.strip()
    match = re.search(r"request_token=([a-zA-Z0-9]+)", raw)
    token = match.group(1) if match else raw
    if not token or len(token) < 16:
        return False, "Invalid request token format"

    checksum = hashlib.sha256(f"{api_key}{token}{api_secret}".encode()).hexdigest()
    data = urllib.parse.urlencode(
        {"api_key": api_key, "request_token": token, "checksum": checksum}
    ).encode()
    req = urllib.request.Request("https://api.kite.trade/session/token", data=data)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode())
            return True, res.get("data", {})
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode())
            return False, err.get("message", str(exc))
        except Exception:
            return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:
        return False, str(exc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange", help="Request token or full redirect URL from Kite login")
    parser.add_argument("--verify", action="store_true", help="Verify current access token in .env")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("KITE_API_KEY", "")
    api_secret = env.get("KITE_API_SECRET", "")
    current_token = env.get("KITE_ACCESS_TOKEN", "")

    if not api_key:
        print("ERROR: KITE_API_KEY not found in .env")
        return 1

    if args.exchange:
        if not api_secret:
            print("ERROR: KITE_API_SECRET required in .env to exchange request token")
            return 1
        print(f"Exchanging request token with Kite API (API Key: {api_key})...")
        success, data = exchange_request_token(api_key, api_secret, args.exchange)
        if not success:
            print(f"FAILED to exchange request token: {data}")
            return 1
        new_token = data.get("access_token")
        user_id = data.get("user_id")
        user_name = data.get("user_name")
        print(f"SUCCESS! Logged in as: {user_name} ({user_id})")
        update_env("KITE_ACCESS_TOKEN", new_token)
        print("Updated KITE_ACCESS_TOKEN in .env successfully.")
        current_token = new_token

    # Verify token
    print(f"\nVerifying access token against Kite API...")
    ok, profile = verify_token(api_key, current_token)
    if ok:
        margin = verify_margin(api_key, current_token)
        print(f"TOKEN VALID!")
        print(f"  - User: {profile.get('user_name')} ({profile.get('user_id')})")
        print(f"  - Email: {profile.get('email')}")
        print(f"  - Broker: {profile.get('broker')}")
        print(f"  - Available Margin: Rs. {margin if margin is not None else 'N/A'}")
        return 0
    else:
        print(f"TOKEN INVALID / EXPIRED:")
        print(f"  - Error: {profile.get('message', 'Unknown error')}")
        print(f"  - Error Type: {profile.get('error_type', 'N/A')}")
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
        print(f"\nTo generate a new session:")
        print(f"1. Open this URL in your browser:\n   {login_url}")
        print(f"2. Log in with Kite credentials.")
        print(f"3. Copy the redirected URL (contains request_token=...) and run:")
        print(f"   python tools/kite_token.py --exchange <URL_OR_REQUEST_TOKEN>")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
