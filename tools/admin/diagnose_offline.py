"""Read-only end-to-end offline permit diagnostic, run on the admin PC.

Uses a fresh normal Firebase end-user login, not administrator credentials.
No tokens, passwords, private key material, response bodies or account IDs
are printed or saved. Does not edit Firestore or the remembered session.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit

# Run from tools/admin in the downloaded source tree, no GIS deps required.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geostudio.web_app.firebase_auth import AuthError, FirebaseClient, FirebaseConfig
from geostudio.web_app.firebase_devices import device_id
from geostudio.web_app.firebase_offline import verify_permit


WORKER_ERRORS = {
    "method", "auth", "body", "denied", "upstream", "expired",
    "signer", "unavailable", "firestore_response",
    "key_missing", "key_json", "key_import", "key_sign",
}


def public_from_jwk(path):
    # Only use public coordinates; never send the JWK to any server.
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["kty"] != "EC" or data["crv"] != "P-256":
        raise ValueError("unexpected key type")
    coords = [base64.urlsafe_b64decode(data[k] + "=" * (-len(data[k]) % 4))
              for k in ("x", "y")]
    if any(len(part) != 32 for part in coords):
        raise ValueError("invalid public coordinates")
    return base64.urlsafe_b64encode(b"\x04" + b"".join(coords)).decode("ascii").rstrip("=")


def worker_error(response):
    try:
        code = response.json().get("error")
        return code if isinstance(code, str) and code in WORKER_ERRORS else "unknown"
    except (ValueError, AttributeError):
        return "non-json"


def main():
    parser = argparse.ArgumentParser(description="Diagnose GeoStudio offline permits without logging secrets")
    parser.add_argument("--project", required=True)
    parser.add_argument("--url", required=True, help="Your own trusted HTTPS Worker URL")
    parser.add_argument("--jwk", type=Path,
                        default=Path(os.environ["USERPROFILE"]) / "GeoStudioAdmin" / "offline-private.jwk")
    args = parser.parse_args()
    import requests

    parsed = urlsplit(args.url)
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".workers.dev")
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        parser.error("Use your own trusted HTTPS workers.dev endpoint.")
    try:
        public = public_from_jwk(args.jwk)
        api_key = getpass.getpass("Firebase Web API Key (local only): ").strip()
        cfg = FirebaseConfig(args.project, api_key, args.url, public)
    except (OSError, ValueError, KeyError, TypeError, AuthError):
        print("CONFIG: ERROR (check the local key file, API key and URL)")
        return 1
    print("CONFIG: OK")
    device = device_id(args.project)
    if not device:
        print("DEVICE: ERROR")
        return 1
    email = input("GeoStudio account email: ").strip()
    password = getpass.getpass("GeoStudio account password (hidden): ")
    client = FirebaseClient(cfg, machine_id=device)
    try:
        data = client._post("signInWithPassword", {
            "email": email, "password": password, "returnSecureToken": True,
        })
        credential = client._credentials(data)
    except AuthError:
        print("FIREBASE_AUTH: ERROR (check account and API key)")
        return 1
    finally:
        del password
    print("FIREBASE_AUTH: OK")
    headers = {"Authorization": "Bearer " + credential.id_token,
               "Accept": "application/json", "User-Agent": "GeoStudio-Offline/1.0"}
    firestore = ("https://firestore.googleapis.com/v1/projects/" + args.project
                 + "/databases/(default)/documents/geostudio_access/"
                 + quote(credential.uid, safe=""))
    try:
        response = requests.get(firestore, headers=headers, timeout=15, allow_redirects=False)
        print("FIRESTORE_HTTP:", response.status_code)
        if response.status_code != 200:
            return 1
        fields = response.json()["fields"]
        cap, devices = client._device_policy(fields)
        enabled = fields.get("offlineHours", {}).get("integerValue") in ("72", 72)
        print("POLICY_OFFLINE_72:", "YES" if enabled else "NO")
        print("DEVICE_REGISTERED:", "YES" if device in devices else "NO")
        print("DEVICE_COUNT:", str(len(devices)) + "/" + str(cap))
        if not (enabled and cap and device in devices):
            return 1
        response = requests.post(args.url, json={"deviceId": device}, headers=headers,
                                 timeout=15, allow_redirects=False)
        print("WORKER_HTTP:", response.status_code)
        if response.status_code != 200:
            print("WORKER_ERROR:", worker_error(response))
            return 1
        try:
            permit = verify_permit(response.json()["lease"], public, args.project, device, time.time())
            if permit.uid != credential.uid:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            print("SIGNATURE_OR_PERMIT: ERROR")
            return 1
        print("SIGNATURE_OR_PERMIT: OK")
        print("RESULT: VALID_OFFLINE_PERMIT")
        return 0
    except requests.RequestException as exc:
        # Exception messages can contain URLs or request details.
        print("NETWORK_ERROR:", type(exc).__name__)
        return 1
    except (AuthError, ValueError, KeyError, TypeError):
        print("RESPONSE_OR_POLICY: ERROR")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
