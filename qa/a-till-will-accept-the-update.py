# -*- coding: utf-8 -*-
"""The update we are offering is one a till will actually take.

WHY THIS IS NOT COVERED BY THE BUILD

`publish.py` checks that the bundler produced a `.sig` file and copies its
contents into `latest.json`. That is the whole of it. Nothing checks that the
signature verifies, and nothing checks it verifies against the key the
application carries.

Those are two different failures and both are silent.

  The wrong key      `tauri.conf.json` carries the PUBLIC half; the build
                     machine holds the private half in `~/.rx5000`. Nothing
                     ties them together. Sign with a second key pair, or with
                     a regenerated one, and every artefact looks perfect:
                     installers build, the manifest is written, the page
                     links resolve. Every running till fetches the manifest,
                     fails to verify, and declines the update. In silence,
                     because declining an unverifiable update is the correct
                     behaviour and the till has nobody to tell.

  The wrong bytes    The signature is over the installer as it came out of
                     the bundler. The installer is then copied into the
                     downloads folder and served by a different machine. A
                     truncated copy, a rewritten file, a stale file left
                     behind next to a fresh manifest: same outcome, same
                     silence.

The result either way is a fleet that stops updating and no report, because
the failure produces nothing a pharmacy can see. They just stay on the version
they have, and the next person to look at it finds tills four releases back
and no explanation.

WHAT THIS CHECKS

The published manifest's signature, verified as minisign does it: blake2b of
the file, Ed25519, against the public key out of `tauri.conf.json` rather than
a copy pasted in here, so rotating the key does not leave this guard checking
the old one.

Locally by default. `--live` checks what the website is actually serving,
which is the only copy a till will ever fetch. `--plant` alters one byte of
the installer in memory, leaving the published file alone, and proves the
check is a check.

Run by exit code. Nought is a pass.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
DOWNLOADS = ROOT / "landing" / "downloads"
PLATFORM = "windows-x86_64"


def public_key():
    """The key the application carries, out of the configuration it carries."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    armoured = base64.b64decode(
        conf["plugins"]["updater"]["pubkey"]).decode("utf-8")
    # A minisign key file is a comment line and then the key: two bytes of
    # algorithm, eight of key id, thirty two of Ed25519 public key.
    raw = base64.b64decode(armoured.splitlines()[1])
    return Ed25519PublicKey.from_public_bytes(raw[10:]), raw[2:10].hex()


def signature(armoured: str):
    """The 64 bytes of signature, and the id of the key that made them."""
    body = base64.b64decode(armoured).decode("utf-8")
    raw = base64.b64decode(body.splitlines()[1])
    if raw[:2] != b"ED":
        raise SystemExit(
            f"The signature says algorithm {raw[:2]!r}. Tauri signs the "
            f"blake2b digest and marks it ED; anything else is a signature "
            f"this does not know how to check, which is not the same as one "
            f"that is good.")
    return raw[10:], raw[2:10].hex()


def main(live: bool, plant: bool = False) -> int:
    manifest = json.loads((DOWNLOADS / "latest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    entry = manifest["platforms"][PLATFORM]
    url = entry["url"]

    if live:
        print(f"  fetching {url}")
        with urllib.request.urlopen(url, timeout=600) as f:
            blob = f.read()
        where = "the website"
    else:
        local = DOWNLOADS / url.rsplit("/", 1)[-1]
        if not local.exists():
            print(f"FAIL  the manifest offers {local.name} and it is not in "
                  f"{DOWNLOADS.relative_to(ROOT)}.")
            return 1
        blob = local.read_bytes()
        where = local.name

    if plant:
        # One byte of a five megabyte installer, changed in memory rather than
        # on the disk: the file people download is never touched. This is the
        # "wrong bytes" failure, and a signature that still verified after it
        # would not be a signature.
        blob = blob[:1024] + bytes([blob[1024] ^ 0x01]) + blob[1025:]
        where += " with one byte altered"

    key, key_id = public_key()
    sig, sig_id = signature(entry["signature"])
    if sig_id != key_id:
        print(f"FAIL  {version} was signed by key {sig_id}, and the "
              f"application carries {key_id}.\n"
              f"  Every till would fetch this, fail to verify it, and decline "
              f"the update without saying so. Check which private key the "
              f"build machine used.")
        return 1

    try:
        key.verify(sig, hashlib.blake2b(blob).digest())
    except Exception:
        if plant:
            print(f"ok  planted fault caught: {where} does not verify, so "
                  f"this would have stopped the publish")
            return 0
        print(f"FAIL  the signature does not match {where} "
              f"({len(blob):,} bytes).\n"
              f"  The key is right, so the file is not the one that was "
              f"signed. A till would decline this update in silence.")
        return 1

    if plant:
        print(f"FAIL  one byte of the installer was changed and the signature "
              f"still verified, which means nothing here is checking anything")
        return 1
    print(f"ok  {version}: {where} ({len(blob):,} bytes) verifies against key "
          f"{key_id}, so a running till will take it")
    return 0


if __name__ == "__main__":
    try:
        import cryptography  # noqa: F401
    except ImportError:
        print("This needs `cryptography` to check an Ed25519 signature.")
        sys.exit(2)
    sys.exit(main("--live" in sys.argv, "--plant" in sys.argv))
