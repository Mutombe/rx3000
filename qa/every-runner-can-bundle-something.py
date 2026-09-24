"""A machine we pay to compile for fifteen minutes must be able to produce something.

FOUR TAGGED RELEASES FAILED ON macOS BEFORE ANYBODY READ THE CAUSE.

`bundle.targets` in tauri.conf.json listed msi, nsis, deb and appimage. Those
are the Windows and Linux formats. The Mac runner checked the code out,
installed two Rust targets, compiled the whole application, was then asked to
build four bundle formats none of which exist on macOS, produced nothing, and
tauri-action ended with "No artifacts were found."

Nothing about that says "the configuration never asked for a Mac bundle". The
job simply went red, on every tag, while Windows and Linux went green beside
it, which reads like a flaky Mac runner rather than a line in a JSON file. It
is also invisible locally: Tauri silently skips targets that do not belong to
the host, which is what lets Windows build happily with deb and appimage in
the same list.

WHAT THIS CHECKS

The release workflow names the machines we build on. For each one, at least
one of the configured bundle targets must be producible there, and the icon
that platform's bundler requires must exist.

  - macOS wants app or dmg, and an .icns.
  - Windows wants msi or nsis, and an .ico.
  - Linux wants deb, appimage or rpm.

It reads the matrix out of the workflow rather than hard-coding the runners,
so adding a platform to the workflow and forgetting its bundle format is
caught by the same check that caught this one.

Run by exit code. Nought is a pass.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
FLOW = ROOT / ".github" / "workflows" / "desktop.yml"

#: runner name fragment -> (what it can bundle, the icon its bundler needs)
PLATFORMS = {
    "macos": ({"app", "dmg"}, "icns"),
    "windows": ({"msi", "nsis"}, "ico"),
    "ubuntu": ({"deb", "appimage", "rpm"}, None),
}


def main() -> int:
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    bundle = conf.get("bundle", {})
    targets = bundle.get("targets")
    icons = [Path(i).name.lower() for i in bundle.get("icon", [])]

    if targets in ("all", None):
        print("bundle.targets builds everything the host offers, so no runner "
              "can be left with nothing to do.")
        return 0
    targets = {str(t).lower() for t in targets}

    runners = sorted(set(re.findall(r"os:\s*([A-Za-z0-9.\-]+)",
                                    FLOW.read_text(encoding="utf-8"))))
    if not runners:
        print(f"No runners found in {FLOW.relative_to(ROOT)}, so there is "
              f"nothing to check against. Has the matrix moved?")
        return 1

    faults = []
    for runner in runners:
        for fragment, (can_build, needs_icon) in PLATFORMS.items():
            if fragment not in runner:
                continue
            if not targets & can_build:
                faults.append(
                    f"{runner} compiles the whole application and then has "
                    f"nothing it can bundle.\n"
                    f"      it can build : {', '.join(sorted(can_build))}\n"
                    f"      we asked for : {', '.join(sorted(targets))}")
            elif needs_icon and not any(i.endswith(needs_icon) for i in icons):
                faults.append(
                    f"{runner} is asked for a bundle but bundle.icon has no "
                    f".{needs_icon}, which its bundler needs.\n"
                    f"      icons listed : {', '.join(icons) or 'none'}")
            break

    if not faults:
        print(f"Every runner can bundle something. "
              f"{len(runners)} machine(s), targets: {', '.join(sorted(targets))}.")
        return 0

    print("\nA machine is being paid to compile and cannot ship the result.\n")
    for fault in faults:
        print(f"    {fault}\n")
    print("  Add the platform's format to bundle.targets in "
          "desktop/src-tauri/tauri.conf.json.")
    print("  Tauri skips targets that do not belong to the host, so adding one "
          "does not\n  change what the other machines produce.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
