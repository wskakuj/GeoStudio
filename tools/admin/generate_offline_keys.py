"""Generate a new offline signing key outside the repository. Never commit it."""
import argparse
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("private_file", type=Path, help="New private JWK file outside repo")
    args = parser.parse_args()
    target = args.private_file.resolve()
    repo = Path(__file__).resolve().parents[2]
    if target.is_relative_to(repo):
        parser.error("Choose a private location outside the repository.")
    key = ec.generate_private_key(ec.SECP256R1())
    n = key.private_numbers()
    jwk = {"kty":"EC","crv":"P-256","x":b64(n.public_numbers.x.to_bytes(32,"big")),
           "y":b64(n.public_numbers.y.to_bytes(32,"big")),
           "d":b64(n.private_value.to_bytes(32,"big")),"ext":False,"key_ops":["sign"]}
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(jwk, output)
    print("GEOSTUDIO_OFFLINE_PUBLIC_KEY=" + b64(key.public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint)))
    print("Private key saved locally; set it ONLY as the Worker's SIGNING_KEY_JWK secret.")


if __name__ == "__main__":
    main()
