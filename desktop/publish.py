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


#: The server a desktop build points at unless the shell says otherwise.
#: Read from the Rust source so there is one statement of it, not two that
#: drift.
def _default_server() -> str:
    src = (TAURI / "src" / "main.rs").read_text(encoding="utf-8")
    found = re.search(r'const DEFAULT_SERVER: &str = "([^"]+)"', src)
    if not found:
        raise SystemExit(
            "Could not find DEFAULT_SERVER in main.rs, so the front end would "
            "be built with no server address and every request in the desktop "
            "application would go nowhere.")
    return found.group(1)


def build() -> None:
    env = _signing_env()

    # Bake the server address into the bundle.
    #
    # `apiBase` prefers the address the Rust shell injects and falls back to
    # this. The hosted site sets it in its own build environment, which is why
    # the browser has always worked; a laptop build had nothing, so the bundle
    # fell back to "" and every request went to http://tauri.localhost/api/…
    # — reported, accurately, as not being able to reach the server.
    #
    # The injected global still wins where it exists. That is what lets a
    # pharmacy point a till at a server in their own back office.
    api_base = _default_server()
    env["VITE_API_BASE"] = api_base
    print(f"  front end will fall back to {api_base}")

    # The front end is NOT built here any more. `tauri.conf.json` carries a
    # `beforeBuildCommand` that builds it, so the bundle is rebuilt whoever
    # starts the build — this script, `npx tauri build` by hand, or CI.
    #
    # It used to be built here and only here, which meant `tauri build` on its
    # own bundled whatever `frontend/dist` happened to be lying on the disk.
    # That is how a download ends up five days behind the repository while the
    # person who built it is looking at today's code, and it is invisible
    # until somebody installs it and reports screens that were changed a week
    # ago. The environment below is passed through to that command.
    print("  building the installers… (several minutes, front end included)")
    subprocess.run(["npx", "--yes", "@tauri-apps/cli", "build"], cwd=TAURI,
                   check=True, shell=True, env=env)

    # Checked AFTER the build, against what was actually bundled.
    #
    # EVERY chunk, not `index-*.js`. The address lives in `api.ts`, and which
    # chunk that lands in is Vite's business, not ours: when the staff
    # application moved behind its own lazy boundary the entry chunk became a
    # router and almost nothing else, and `api.ts` went to a shared chunk
    # named after whichever module happened to be first in it. The check
    # started failing on a bundle that was perfectly correct, which is the
    # good failure — it stopped a publish rather than shipping something
    # unverified — but the question it means to ask is "is the address in the
    # bundle", and the bundle is all of these files.
    built = sorted((ROOT / "frontend" / "dist" / "assets").glob("*.js"))
    if not any(api_base in f.read_text(encoding="utf-8", errors="replace")
               for f in built):
        raise SystemExit(
            f"The built bundle does not contain {api_base}.\n"
            f"  A desktop build with no server address reports every request "
            f"as a connection failure, which sends everybody looking at the "
            f"network instead of at this.")
    print("  the address is in the bundle")

    # And the bundle is today's. A build that silently shipped a stale front
    # end is the fault this check exists for: the installer is only worth
    # handing to a pharmacy if what is inside it is what is in the repository.
    newest = max(f.stat().st_mtime for f in built)
    age = (datetime.now(timezone.utc).timestamp() - newest) / 60
    if age > 30:
        raise SystemExit(
            f"The bundled front end is {age:.0f} minutes old, so the build did "
            f"not rebuild it. Check `beforeBuildCommand` in tauri.conf.json.")
    print(f"  the bundle was built {age:.0f} minute(s) ago")


def _head_commit() -> str:
    """Whatever HEAD is at this moment."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              check=True, capture_output=True, text=True,
                              shell=False).stdout.strip()
    except Exception:
        return ""


#: HEAD as it was when this run started, which is the code the bundle can
#: possibly contain. Read at import so it is taken before anything is built.
_HEAD_AT_START = _head_commit()


def _built_from() -> str:
    """The commit the bundle in this installer was ACTUALLY built from.

    NOT HEAD at publish time. HEAD can move while a build runs — a fifteen
    minute Rust compile is long enough to commit something else — and stamping
    the later commit claims the installer contains code it does not.

    That is the one failure qa/the-download-is-not-behind-the-code.py cannot
    catch. It compares the stamp against the branch, so a stamp that OVERCLAIMS
    reads as "the download is the code" while the download quietly is not. It
    happened on 1.6.30: the bundle was built at 13:48 from 9848568 and stamped
    ce17458, committed eight minutes into the compile.

    So the stamp is HEAD as it was when this run started, and a move is said
    out loud rather than silently resolved either way.
    """
    now = _head_commit()
    if _HEAD_AT_START and now and now != _HEAD_AT_START:
        print(f"  NOTE      the branch moved during the build "
              f"({_HEAD_AT_START[:7]} to {now[:7]}).")
        print(f"            Stamped {_HEAD_AT_START[:7]}, which is what these "
              f"installers actually contain.")
        print(f"            Build again to ship what is on the branch now.")
    return _HEAD_AT_START or now


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
    # And the size, which the page stated and nobody maintained: it read
    # 3.5 MB beside a 5.0 MB installer. A page that is wrong about the thing
    # it is offering is a page nobody checks the rest of.
    mb = (DOWNLOADS / wanted["nsis"]).stat().st_size / 1024 / 1024
    page = re.sub(r'(Windows 10 and 11, 64-bit\. )[0-9.]+ MB',
                  rf'\g<1>{mb:.1f} MB', page)
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

    Windows only, and deliberately. Windows is what a till in a Zimbabwean
    pharmacy runs, and it is what is built here.

    This used to say a Linux or macOS build from the workflow would add its own
    platform to this file. Nothing does: .github/workflows/desktop.yml attaches
    its installers to a GitHub release and never opens latest.json, and this
    function rewrites the file whole. So the entries for the other two platforms
    were not lost, they were never maintained, and the version they carried went
    stale the moment a Windows release moved past it. Offering a till an
    installer built against a different version of the app is worse than
    offering it nothing, so this writes only what it has just built and signed.
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

    # WHICH COMMIT IS IN THE THING PEOPLE DOWNLOAD.
    #
    # Nothing recorded this, and without it nobody can answer the only
    # question that matters about an installer: is it the code we are looking
    # at. The website redeploys on every push; a desktop build happens when
    # somebody runs this. So the two drift by default, silently, and the drift
    # is discovered by a pharmacy installing a five-day-old application and
    # reporting screens that were changed last week.
    #
    # Written beside the manifest rather than inside it: `latest.json` is a
    # contract with the Tauri updater, and an unrecognised key there is a risk
    # taken for no reason. qa/the-download-is-not-behind-the-code.py reads it.
    stamp = DOWNLOADS / "published.json"
    stamp.write_text(json.dumps({
        "version": version,
        "commit": _built_from(),
        "published_at": manifest["pub_date"],
    }, indent=2) + "\n", encoding="utf-8")
    print(f"  stamped   built from {_built_from()[:7] or 'unknown'}")


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
