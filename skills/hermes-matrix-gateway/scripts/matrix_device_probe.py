#!/usr/bin/env python3
"""Matrix account device & security-state probe (stdlib only).

Reads MATRIX_* from the Hermes .env, logs in via the pinned diagnostic device
(DIAG01 — re-login with an existing device_id reuses it, so re-runs are
idempotent and mint no new devices), and reports:

  1. all devices on the account (id, name, last IP, user agent)
  2. cross-signing account data presence
  3. cross-signing public keys (via /keys/query)
  4. secret storage (recovery key) presence
  5. attempts DELETE of DIAG01 (matrix.org 404s device deletion — known quirk;
     cleanup happens in the Element UI)

Use when: user reports a new-device verification prompt, stray devices appear
in the account, or you need to know whether cross-signing / recovery key
exists before advising on Element's "Verify your identity" flow.

Usage:
  <datadir>/.hermes/venv/bin/python matrix_device_probe.py [path/to/.env]

Defaults for .env: $HERMES_HOME/.env, <datadir>/.hermes/.env, ./.env
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def find_env():
    if len(sys.argv) > 1:
        return sys.argv[1]
    cands = [
        os.path.expanduser(os.environ.get("HERMES_HOME", "")) + "/.env",
        "<datadir>/.hermes/.env",
        os.path.join(os.getcwd(), ".env"),
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    sys.exit("no .env found — pass path as first arg")


def load_env(path):
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def req(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def main():
    env = load_env(find_env())
    hs = env.get("MATRIX_HOMESERVER", "https://matrix.org").rstrip("/")
    user = env.get("MATRIX_USER_ID")
    token = env.get("MATRIX_ACCESS_TOKEN")

    if not token:
        if not user or "MATRIX_PASSWORD" not in env:
            sys.exit("need MATRIX_ACCESS_TOKEN, or MATRIX_USER_ID + MATRIX_PASSWORD")
        s, res = req("POST", hs + "/_matrix/client/v3/login", body={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user},
            "password": env["MATRIX_PASSWORD"],
            "device_id": "DIAG01",
        })
        if s != 200:
            sys.exit("login failed: %s %s" % (s, res))
        token = res["access_token"]
        print("logged in via DIAG01 (token not printed)")

    if not user:
        s, who = req("GET", hs + "/_matrix/client/v3/account/whoami", token)
        user = who.get("user_id")
        if not user:
            sys.exit("could not determine user id (whoami: %s)" % s)
    uq = urllib.parse.quote(user, safe="")

    s, d = req("GET", hs + "/_matrix/client/v3/devices", token)
    print("\nDevices on account:")
    for dev in d.get("devices", []):
        print("  - %s | %s | %s | %s" % (
            dev.get("device_id"), dev.get("display_name"),
            dev.get("last_seen_ip"), (dev.get("user_agent") or "")[:70]))

    s, _ = req("GET", hs + "/_matrix/client/v3/user/" + uq + "/account/data/cross_signing", token)
    print("\ncross_signing account data: %s" % ("present" if s == 200 else "NONE"))

    s, ks = req("POST", hs + "/_matrix/client/v3/keys/query", token,
                body={"device_keys": {user: []}})
    cs = ks.get("device_keys", {}).get(user, {}).get("cross_signing", {}) if s == 200 else {}
    print("cross-signing public keys: %s" % (list(cs.keys()) or "NONE"))

    s, _ = req("GET", hs + "/_matrix/client/v3/user/" + uq + "/account/data/m.secret_storage.key", token)
    print("secret storage (recovery key): %s" % ("present" if s == 200 else "not set"))

    s, delres = req("DELETE", hs + "/_matrix/client/v3/devices/DIAG01", token)
    print("\nDELETE DIAG01: %s %s" % (s, delres.get("errcode", "ok")))
    print("(matrix.org 404s device deletion — clean up leftovers in the Element UI)")


if __name__ == "__main__":
    main()
