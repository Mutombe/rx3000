"""Which screens blank, and which say they are working.

Two faults, both of which look like the software being broken rather than busy:

  * **No loading state at all.** A page that fetches on mount and renders an
    empty table until the answer lands shows "No records" to somebody whose
    records are on their way. On a slow connection that is indistinguishable
    from an empty pharmacy, and it is the first thing a new customer sees.

  * **A loading state that blanks what is already there.** Changing a filter on
    a populated table and having it drop to a skeleton reads as the page
    breaking. `Refreshable` exists for exactly this — skeleton on the first
    paint, a dim on every refetch after it — and most screens do not use it.

This counts both, names the screens, and is meant to be run down to zero rather
than admired. It reads the source rather than the browser because the question
is whether the code can ever show a loading state, not whether it happened to
on one run.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = ROOT / "frontend" / "src" / "pages"

# Screens that legitimately have nothing to wait for.
NO_FETCH_NEEDED = {
    "Login", "Welcome", "Training", "Profile", "Assistant",
}

# A RecordPage that is handed a loading flag ghosts itself.
REC_LOADING = re.compile(r"loading=\{")

fetches, skeletons, refreshable, bare = [], [], [], []

for path in sorted(PAGES.glob("*.tsx")):
    name = path.stem
    src = path.read_text(encoding="utf-8")
    # Does it read anything from the server at all?
    if not re.search(r"api\.(get|post)<", src):
        continue
    if name in NO_FETCH_NEEDED:
        continue
    fetches.append(name)
    # `RecordPage` takes a `loading` prop and renders DetailSkeleton itself, so
    # a page using it has a loading state without naming a skeleton. Counting
    # only the word "Skeleton" reported fifteen record pages as bare when every
    # one of them already ghosts correctly — an audit that cries wolf gets
    # worked around rather than worked down.
    has_skeleton = (
        "Skeleton" in src
        or ("RecordPage" in src and REC_LOADING.search(src) is not None)
    )
    has_refreshable = "<Refreshable" in src
    if has_skeleton:
        skeletons.append(name)
    if has_refreshable:
        refreshable.append(name)
    if not has_skeleton:
        bare.append(name)

print(f"{len(fetches)} screens load data from the server")
print(f"  {len(skeletons)} show a skeleton while it arrives")
print(f"  {len(refreshable)} keep what they have while refetching (Refreshable)")
print(f"  {len(bare)} show nothing at all\n")

if bare:
    print("NO LOADING STATE — these render an empty table until the answer lands")
    print("-" * 72)
    for n in bare:
        print(f"  {n}")

only_skeleton = [n for n in skeletons if n not in refreshable]
if only_skeleton:
    print("\nSKELETON BUT NO Refreshable — these blank a populated table on refetch")
    print("-" * 72)
    for n in only_skeleton:
        print(f"  {n}")

# A budget rather than a pass/fail: this is worked down over time, and a run
# that fails the build the moment somebody adds a screen helps nobody.
BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else len(bare)
print(f"\n{len(bare)} without a loading state (budget {BUDGET})")
sys.exit(1 if len(bare) > BUDGET else 0)
