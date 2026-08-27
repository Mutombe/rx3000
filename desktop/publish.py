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
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI = ROOT / "desktop" / "src-tauri"
BUNDLE = TAURI / "target" / "release" / "bundle"
DOWNLOADS = ROOT / "landing" / "downloads"
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


def build() -> None:
    print("  building the front end…")
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend",
                   check=True, shell=True)
    print("  building the installers… (several minutes)")
    subprocess.run(["npx", "--yes", "@tauri-apps/cli", "build"], cwd=TAURI,
                   check=True, shell=True)


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
