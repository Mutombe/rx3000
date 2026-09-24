"""What people download must be the application we are looking at.

THIS WENT WRONG FOR FIVE DAYS AND NOBODY COULD SEE IT.

The website redeploys on every push. A desktop build happens only when
somebody runs `desktop/publish.py`. So the two drift apart by default, in one
direction, silently — and the drift is not discovered by anybody working on
the code. It is discovered by a pharmacy installing the application, finding
screens that were changed last week, and reporting it as a mixture of old and
new, because from the counter that is exactly what it looks like.

It ran to 120 frontend commits before anybody noticed, and the report that
finally surfaced it described the symptom rather than the cause: an old
dispensary sitting next to a new assistant. They were not from different
builds. They were one build, from before half the work existed.

WHAT THIS CHECKS

`publish.py` now records the commit it built from, beside the installer it
published. This compares that commit with the current branch and counts the
commits to `frontend/` in between — the ones that change what a person sees.

  - Nothing in between: the download is the code. Passes.
  - Commits in between: the download is behind, and by how much and which
    ones is printed, because "rebuild it" is only actionable if you can see
    what is missing.

It counts `frontend/` alone on purpose. A change to the backend, to the
guards, or to this file does not alter what is inside an installer, and a
check that cries wolf about those is a check somebody turns off.

Run by exit code. Nought is a pass.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "landing" / "downloads" / "published.json"
#: What actually goes into the installer. The backend is served, not bundled.
BUNDLED = ("frontend/src", "frontend/index.html", "frontend/package.json",
           "frontend/vite.config.ts", "frontend/public")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def main() -> int:
    if not STAMP.exists():
        print(f"No {STAMP.relative_to(ROOT)}, so there is no way to tell which "
              f"commit the published installer was built from.\n"
              f"  Publish once with desktop/publish.py and it will be written.")
        return 1

    stamp = json.loads(STAMP.read_text(encoding="utf-8"))
    built = (stamp.get("commit") or "").strip()
    version = stamp.get("version", "?")
    if not built:
        print("The published installer records no commit, so it cannot be "
              "compared with anything.")
        return 1

    try:
        git("cat-file", "-e", f"{built}^{{commit}}")
    except subprocess.CalledProcessError:
        print(f"The published installer names commit {built[:7]}, which is not "
              f"in this repository.\n"
              f"  Either it was built somewhere else or the history was "
              f"rewritten; either way the download cannot be vouched for.")
        return 1

    behind = [ln for ln in
              git("log", "--oneline", f"{built}..HEAD", "--", *BUNDLED).split("\n")
              if ln.strip()]

    if not behind:
        print(f"The download is the code. {version} was built from "
              f"{built[:7]}, and nothing in the front end has changed since.")
        return 0

    print(f"\nThe download is {len(behind)} front-end commit(s) behind the code.\n")
    print(f"  published : {version}, built from {built[:7]}")
    print(f"  now       : {git('rev-parse', '--short', 'HEAD')}")
    print(f"\n  Somebody downloading the application today would not get:\n")
    for line in behind[:15]:
        print(f"    {line}")
    if len(behind) > 15:
        print(f"    … and {len(behind) - 15} more")
    print(f"\n  Cut a build: python desktop/publish.py <next version>")
    return 1


if __name__ == "__main__":
    sys.exit(main())
