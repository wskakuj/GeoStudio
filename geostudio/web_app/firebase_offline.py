"""Verify bounded or explicitly perpetual offline permits signed outside the client.

DPAPI and monotonic time protect normal local use, not a hostile machine
owner capable of restoring disk snapshots or modifying the executable.
"""
import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

MAX_OFFLINE_SECONDS = 72 * 3600
OFFLINE_UNLIMITED = -1
CLOCK_TOLERANCE = 120


def b64decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class OfflinePermit:
    uid: str
    email: str
    issued: int
    expires: int | None
    account_expires: datetime | None
    device_limit: int
    device_count: int

    @property
    def unlimited(self):
        return self.expires is None


def verify_permit(token, public_key, project, device, now, last_seen=0):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    try:
        if not isinstance(token, str) or len(token) > 8192:
            raise ValueError
        payload, signature = token.split(".")
        raw, sig = b64decode(payload), b64decode(signature)
        if len(sig) != 64:
            raise ValueError
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64decode(public_key))
        der = utils.encode_dss_signature(int.from_bytes(sig[:32], "big"),
                                         int.from_bytes(sig[32:], "big"))
        key.verify(der, raw, ec.ECDSA(hashes.SHA256()))
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        uid, email = data["uid"], data["email"]
        issued, expires = data["iat"], data["exp"]
        cap, count = data["deviceLimit"], data["deviceCount"]
        account = data["accountExp"]
        version = data["v"]
        if (type(version) is not int or version not in (1, 2)
                or data["project"] != project or data["device"] != device
                or not re.fullmatch(r"[a-f0-9]{64}", device or "")
                or not isinstance(uid, str) or not 1 <= len(uid) <= 128
                or not isinstance(email, str) or len(email) > 320
                or any(type(x) is not int for x in (issued, cap, count))
                or now < issued - CLOCK_TOLERANCE or now < last_seen - CLOCK_TOLERANCE
                or (account is not None and (type(account) is not int or account <= issued))):
            raise ValueError
        # V1 remains strictly limited to a registered computer and 72 h.
        # V2 explicitly describes unlimited-device and/or perpetual policies.
        if version == 1:
            hours = 72
            if not 1 <= count <= cap <= 20:
                raise ValueError
        else:
            hours = data["offlineHours"]
            if type(hours) is not int or hours not in (72, OFFLINE_UNLIMITED):
                raise ValueError
            if not ((cap == 0 and count == 0) or 1 <= count <= cap <= 20):
                raise ValueError
        if expires is None:
            if version != 2 or hours != OFFLINE_UNLIMITED or account is not None:
                raise ValueError
        else:
            if (type(expires) is not int or not issued < expires or now >= expires
                    or (hours == 72 and expires > issued + MAX_OFFLINE_SECONDS)
                    or (account is not None and expires > account)
                    or (hours == OFFLINE_UNLIMITED and account != expires)):
                raise ValueError
        account_exp = datetime.fromtimestamp(account, timezone.utc) if account is not None else None
        return OfflinePermit(uid, "".join(c for c in email if c.isprintable()), issued,
                             expires, account_exp, cap, count)
    except (InvalidSignature, ValueError, TypeError, KeyError, OverflowError, OSError):
        raise ValueError("Nieprawidłowa lub wygasła licencja offline.") from None
