"""Build the installers and put them on the website, in one step.

Doing this by hand means four things that must agree: the version in
`Cargo.toml`, the version in `tauri.conf.json`, the files in the site's
downloads folder, and the links on the page pointing at them. They drifted
once already — the folder held a 1.0.0, a 1.1.0 and a 1.2.0 with the page
naming only the last, so every earlier build sat there being downloadable by
anyone who guessed the URL.

    python desktop/publish.py 1.3.0            # bump, build, publish
    python desktop/publish.py 1.3.0 --no-build # publish what is already built

The old installers are removed rather than left beside the new one. A
downloads folder with four versions in it is a folder where somebody installs
the wrong one, which is exactly how a "the fix did not work" report starts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI = ROOT / "desktop" / "src-tauri"
BUNDLE = TAURI / "target" / "release" / "bundle"
DOWNLOADS = ROOT / "landing" / "downloads"
#: Where the site is served from. The updater fetches the manifest and the
#: installer from here, so it has to be the real origin rather than a relative
#: path — a till has no page to be relative to.
SITE = "https://rx3000-site.onrender.com"
PAGE = ROOT / "landing" / "index.html"


def set_version(version: str) -> None:
    cargo = TAURI / "Cargo.toml"
    text = cargo.read_text(encoding="utf-8")
    text = re.sub(r'^version = "[^"]+"', f'version = "{version}"', text,
                  count=1, flags=re.M)
    cargo.write_text(text, encoding="utf-8")

    conf = TAURI / "tauri.conf.json"
    raw = conf.read_text(encoding="utf-8")
    raw = re.sub(r'("version"\s*:\s*)"[^"]+"', rf'\1"{version}"', raw, count=1)
    conf.write_text(raw, encoding="utf-8")
    # Read it back rather than trust the substitution: a broken tauri.conf.json
    # fails deep inside the build with a message about nothing in particular.
    assert json.loads(raw)["version"] == version
    print(f"  version set to {version}")


#: Where the private half of the update signing key lives on a build machine.
#: Outside the repository, deliberately and permanently: whoever holds it can
#: hand every till in the country a program of their choosing.
KEY_PATH = Path.home() / ".rx5000" / "rx5000-updater.key"


def _signing_env() -> dict:
    """The environment the bundler signs with.

    `TAURI_SIGNING_PRIVATE_KEY` takes either a path or the key itself. CI sets
    it to the key from a secret; a laptop has the file. Both are checked here
    rather than left to fail four minutes into a build with a message about
    a missing artefact.
    """
    env = dict(os.environ)
    if env.get("TAURI_SIGNING_PRIVATE_KEY"):
        return env
    if KEY_PATH.exists():
        env["TAURI_SIGNING_PRIVATE_KEY"] = KEY_PATH.read_text(
            encoding="utf-8").strip()
        env.setdefault("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
        return env
    raise SystemExit(
        f"No update signing key.\n"
        f"  Expected {KEY_PATH}, or TAURI_SIGNING_PRIVATE_KEY in the "
        f"environment.\n"
        f"  Without it the installers are unsigned and no existing till can "
        f"update itself.")


def build() -> None:
    env = _signing_env()
    print("  building the front end…")
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend",
                   check=True, shell=True)
    print("  building the installers… (several minutes)")
    subprocess.run(["npx", "--yes", "@tauri-apps/cli", "build"], cwd=TAURI,
                   check=True, shell=True, env=env)


def publish(version: str) -> list[Path]:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)

    wanted = {
        "nsis": f"RX5000_{version}_x64-setup.exe",
        "msi": f"RX5000_{version}_x64_en-US.msi",
    }
    found: list[Path] = []
    for kind, name in wanted.items():
        src = BUNDLE / kind / name
        if not src.exists():
            raise SystemExit(f"not built: {src}")
        found.append(src)

    # Clear the old ones first, so a failed copy cannot leave the page pointing
    # at a version that is no longer there.
    for old in DOWNLOADS.glob("RX*"):
        if old.name not in wanted.values():
            print(f"  removing {old.name}")
            old.unlink()

    for src in found:
        shutil.copy2(src, DOWNLOADS / src.name)
        size = (DOWNLOADS / src.name).stat().st_size
        print(f"  published {src.name}  ({size / 1024 / 1024:.1f} MB)")

    _manifest(version, wanted["nsis"])

    page = PAGE.read_text(encoding="utf-8")
    page = re.sub(r'downloads/RX5000_[0-9.]+_x64-setup\.exe',
                  f'downloads/{wanted["nsis"]}', page)
    page = re.sub(r'downloads/RX5000_[0-9.]+_x64_en-US\.msi',
                  f'downloads/{wanted["msi"]}', page)
    page = re.sub(r'RX5000 [0-9]+\.[0-9]+\.[0-9]+ MSI',
                  f'RX5000 {version} MSI', page)
    PAGE.write_text(page, encoding="utf-8")

    still = re.findall(r'downloads/RX5000[^"]*', page)
    for link in still:
        target = DOWNLOADS / link.split("/", 1)[1]
        mark = "ok" if target.exists() else "MISSING"
        print(f"  {mark}: page links {link}")
        if not target.exists():
            raise SystemExit("the page links a file that is not there")
    return found


def _manifest(version: str, installer: str) -> None:
    """Write the file every running till asks for.

    One entry per platform, each naming the installer and the signature that
    proves it came from here. The app carries the public key and refuses
    anything that does not verify, so a manifest without a valid signature is
    not a broken update — it is no update, which is the safe way for this to
    fail.

    Windows only for now, because Windows is what is built here. A Linux or a
    macOS build from the workflow adds its own platform to this file.
    """
    setup = BUNDLE / "nsis" / installer
    signature = setup.with_suffix(setup.suffix + ".sig")
    if not signature.exists():
        raise SystemExit(
            f"not signed: {signature}\n"
            f"  The bundler produced no signature, so nothing can be offered "
            f"as an update. Check that createUpdaterArtifacts is on and the "
            f"signing key was found.")

    notes = (ROOT / "desktop" / "RELEASE_NOTES.md")
    body = notes.read_text(encoding="utf-8").strip() if notes.exists() else ""

    manifest = {
        "version": version,
        "notes": body,
        "pub_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": {
            "windows-x86_64": {
                "signature": signature.read_text(encoding="utf-8").strip(),
                "url": f"{SITE}/downloads/{installer}",
            },
        },
    }
    out = DOWNLOADS / "latest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  manifest  {out.name} offers {version} to every running till")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("version must look like 1.3.0")

    set_version(args.version)
    if not args.no_build:
        build()
    publish(args.version)
    print("\nDone. Commit and push to put it on the site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
