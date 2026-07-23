"""Offline tool for generating Document Core signing keys and license keys."""

import argparse
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def keygen(private_path: Path, public_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    private_path.write_text(encode(private_bytes), encoding="ascii")
    public_path.write_text(encode(public_bytes), encoding="ascii")
    print(f"Privater Schlüssel: {private_path}")
    print(f"Öffentlicher Schlüssel: {public_path}")


def issue(
    private_path: Path,
    customer: str,
    features: list[str],
    expires_at: str,
    installation_id: str | None,
) -> None:
    expiry = datetime.fromisoformat(expires_at).replace(tzinfo=UTC)
    payload = {
        "customer": customer,
        "features": sorted(set(features)),
        "expires_at": expiry.isoformat(),
        "installation_id": installation_id,
    }
    payload_part = encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    private_key = Ed25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(private_path.read_text(encoding="ascii").strip() + "==")
    )
    signed = f"DC1.{payload_part}"
    print(f"{signed}.{encode(private_key.sign(signed.encode('ascii')))}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    keys = subcommands.add_parser("keygen", help="Signaturschlüssel erzeugen")
    keys.add_argument("--private", type=Path, required=True)
    keys.add_argument("--public", type=Path, required=True)
    license_parser = subcommands.add_parser("issue", help="Lizenzschlüssel ausstellen")
    license_parser.add_argument("--private", type=Path, required=True)
    license_parser.add_argument("--customer", required=True)
    license_parser.add_argument("--feature", action="append", required=True)
    license_parser.add_argument("--expires", required=True, help="YYYY-MM-DD")
    license_parser.add_argument("--installation-id")
    args = parser.parse_args()
    if args.command == "keygen":
        keygen(args.private, args.public)
    else:
        issue(
            args.private,
            args.customer,
            args.feature,
            args.expires,
            args.installation_id,
        )


if __name__ == "__main__":
    main()
