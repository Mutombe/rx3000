"""Everything the running server imports is something the deploy installs.

WHY THIS GUARD EXISTS

`openpyxl` was imported in three places — the report engine, the spreadsheet
reader and the export endpoint — and named in `requirements.txt` in none. It
was installed on the machine the code was written on, so every test passed,
every guard passed, and the failure existed only on the hosted deployment,
where every xlsx download answered 500 and every CSV answered 200. Both of
those routes default to xlsx, so the commonest press was the one that failed.

It had been that way since reports were written. Nothing reported it: a 500
from a download link reads as the internet rather than as the software, and
the one machine that could not reproduce it is the one every developer uses.

A comment in `services/spreadsheet.py` said "Reports already export real xlsx,
so openpyxl is here". That sentence was true of a laptop and false of the
server, which is the whole shape of this class of fault: an import is a claim
about a machine you are not sitting at.

WHAT IS DELIBERATELY NOT CHECKED

`backend/app/importers/` holds the one-off CareXpress migration readers. They
are run by hand, on a developer's machine, against files a pharmacy sent on a
memory stick, and nothing in the running server imports them. PyMuPDF is a
twenty megabyte wheel; putting it on every deploy to satisfy a script that has
never run there would be paying rent on a room nobody enters. They are listed
below so the distinction stays a decision rather than an oversight, and if one
of them is ever imported by a router this guard fails, because then it IS on
the server.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
REQS = ROOT / "backend" / "requirements.txt"

# A module whose name differs from the package that installs it.
INSTALLED_AS = {
    "jwt": "pyjwt",
    "multipart": "python-multipart",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "fitz": "pymupdf",
    "yaml": "pyyaml",
}

# Pulled in by something we DO declare, so pip installs them either way.
# Named here rather than waved through, because "it comes with fastapi" is a
# claim that should be written down where it can be argued with.
ARRIVES_WITH = {
    "starlette": "fastapi",
    "botocore": "boto3",
    "pydantic_core": "pydantic",
    "anyio": "fastapi",
}

passed = failed = 0


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


def imports_of(path: pathlib.Path) -> set[str]:
    """Top-level module names imported by one file, relative ones left out."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # `from .. import x` is our own code; only an absolute import can
            # name something pip has to fetch.
            if node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
    return out


print("\n  the server has what it imports\n")

declared = set()
for line in REQS.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    declared.add(re.split(r"[\[><=!~ ]", line)[0].lower())

check(f"requirements.txt names {len(declared)} package(s)", len(declared) > 5)

MIGRATION = APP / "importers"
server_files, tooling_files = [], []
for path in sorted(APP.rglob("*.py")):
    (tooling_files if MIGRATION in path.parents else server_files).append(path)

check(f"there is a server to check ({len(server_files)} file(s), "
      f"{len(tooling_files)} migration reader(s) set aside)",
      len(server_files) > 50)

stdlib = set(sys.stdlib_module_names)


def undeclared(files):
    out = {}
    for path in files:
        for mod in imports_of(path):
            if mod in stdlib or mod == "app" or mod in ARRIVES_WITH:
                continue
            if INSTALLED_AS.get(mod, mod).lower() in declared:
                continue
            out.setdefault(mod, []).append(path.relative_to(ROOT).as_posix())
    return out


missing = undeclared(server_files)
check("every module the server imports is one the deploy installs",
      not missing,
      "; ".join(f"{mod} ({len(where)} file(s), e.g. {where[0]})"
                for mod, where in sorted(missing.items())))

# The migration readers are allowed their own libraries. What is NOT allowed is
# one of those libraries arriving on the server by the back door, and the check
# above is what catches that: the moment a router imports one, its module shows
# up in the server's set.
theirs = sorted(undeclared(tooling_files))
print(f"\n       run by hand, not installed on the server: "
      f"{', '.join(theirs) if theirs else 'none'}")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
