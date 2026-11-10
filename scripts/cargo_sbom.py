"""CycloneDX 1.5 SBOM for the Rust workspace from `cargo metadata --locked` (finding G-5).

Covers every package in Cargo.lock that the workspace resolves (normal, build and dev dependencies, all targets),
with a purl and the registry checksum where Cargo.lock has one. No extra tool to install, so CI and a Windows
host produce the same file. Usage: python scripts/cargo_sbom.py [-o out.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build() -> dict:
    meta = json.loads(subprocess.run(["cargo", "metadata", "--locked", "--format-version", "1"], cwd=ROOT,
                                     capture_output=True, text=True, check=True).stdout)
    lock = tomllib.loads((ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    checksums = {(p["name"], p["version"]): p.get("checksum") for p in lock.get("package", [])}
    members = set(meta["workspace_members"])
    components = []
    for pkg in sorted(meta["packages"], key=lambda p: (p["name"], p["version"])):
        ref = f"pkg:cargo/{pkg['name']}@{pkg['version']}"
        item = {"type": "library" if pkg["id"] not in members else "application", "bom-ref": ref,
                "name": pkg["name"], "version": pkg["version"], "purl": ref}
        if pkg.get("license"):
            item["licenses"] = [{"expression": pkg["license"]}]
        digest = checksums.get((pkg["name"], pkg["version"]))
        if digest:
            item["hashes"] = [{"alg": "SHA-256", "content": digest}]
        components.append(item)
    # Deterministic serial so the SBOM changes only when the lockfile does.
    serial = uuid.uuid5(uuid.NAMESPACE_URL, "tradinggym-cargo:" + (ROOT / "Cargo.lock").read_text(encoding="utf-8"))
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", "version": 1,
            "metadata": {"component": {"type": "application", "name": "tradinggym-executor"}},
            "components": components}


def main(argv: list[str]) -> int:
    bom = json.dumps(build(), indent=2) + "\n"
    if "-o" in argv:
        Path(argv[argv.index("-o") + 1]).write_text(bom, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(bom)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
