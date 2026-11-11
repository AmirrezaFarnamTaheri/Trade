"""Sign executor update manifests so an update proves where it came from, not only that it matches itself.

ECDSA P-256 with SHA-256, because the verifier runs in an elevated Windows PowerShell 5.1 session on .NET
Framework, which has ECDSA but no Ed25519, and must not depend on user-writable code such as a Python venv.

    gymctl release-keygen --private <path> --public <path>   once, on a machine that is not the build host
    gymctl release-sign <manifest> --key <private>           writes <manifest>.sig
    gymctl release-verify <manifest> --public-key <public>   the same check the update script performs

The public key file is JSON {"curve": "P-256", "x": hex, "y": hex}; the signature file is the hex of the
64-byte IEEE P1363 form (r || s) that .NET's ECDsa.VerifyData expects.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

MAX_MANIFEST = 4096


def keygen(private_path: Path, public_path: Path, passphrase: str) -> dict:
    if len(passphrase) < 12:
        raise ValueError("signing-key passphrase must be at least 12 characters")
    for path in (private_path, public_path):
        if path.exists():
            raise ValueError(f"{path} already exists; never overwrite a signing key")
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(passphrase.encode()))
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(pem)
    numbers = key.public_key().public_numbers()
    public = {"curve": "P-256", "x": f"{numbers.x:064x}", "y": f"{numbers.y:064x}"}
    public_path.write_text(json.dumps(public, sort_keys=True) + "\n", "ascii")
    return public


def _manifest(path: Path) -> bytes:
    data = path.read_bytes()
    if not 1 <= len(data) <= MAX_MANIFEST:
        raise ValueError("manifest must be 1..4096 bytes")
    return data


def sign(manifest: Path, private_path: Path, passphrase: str) -> Path:
    key = serialization.load_pem_private_key(private_path.read_bytes(), passphrase.encode())
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise ValueError("signing key must be ECDSA P-256")
    r, s = decode_dss_signature(key.sign(_manifest(manifest), ec.ECDSA(hashes.SHA256())))
    out = manifest.with_name(manifest.name + ".sig")
    out.write_text(f"{r:064x}{s:064x}\n", "ascii")
    return out


def load_public(path: Path) -> ec.EllipticCurvePublicKey:
    value = json.loads(path.read_text("ascii"))
    if set(value) != {"curve", "x", "y"} or value["curve"] != "P-256":
        raise ValueError("public key must be {curve: P-256, x, y}")
    return ec.EllipticCurvePublicNumbers(int(value["x"], 16), int(value["y"], 16), ec.SECP256R1()).public_key()


def verify(manifest: Path, signature: Path, public_path: Path) -> bool:
    text = signature.read_text("ascii").strip()
    if len(text) != 128 or any(c not in "0123456789abcdef" for c in text):
        return False
    der = encode_dss_signature(int(text[:64], 16), int(text[64:], 16))
    try:
        load_public(public_path).verify(der, _manifest(manifest), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True
