"""The shopfront belongs to the pharmacy, not to us.

Three of the four public portals put "RX5000" at the top — the software
vendor's name, on a page the pharmacy's own customer is reading. `document.ts`
settled the argument for printed paper years ago, in as many words: the
wordmark on a statement is the PHARMACY'S, not ours. The portals never got the
memo, so a patient opening their prescriptions from an SMS saw a product they
have never bought from instead of the shop they collect at.

This is the kind of thing that comes back. A new portal is written by copying
the nearest one, and the nearest one used to carry `<div className="pp-brand">
RX5000</div>` at the top of its header. So the rule is checked rather than
remembered:

  1. Every portal page renders the shared frame. A page that hand-rolls its
     own header is a page that will drift, and four of them already had —
     two drew the mark as "RX" and one as the prescription sign.
  2. Nothing in the portal folder puts the vendor's name in a masthead. It
     belongs in the footer, in small print, where a supplier's mark goes,
     and `PortalShell` is the only file allowed to say it at all.
  3. Every portal asks the branding endpoint, so the name it shows is the
     pharmacy's own rather than a hard-coded string.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent / "frontend" / "src" / "portal"

#: The frame itself, and the pieces that are not whole pages.
NOT_A_PAGE = {"PortalShell.tsx", "SignaturePad.tsx"}


def pages() -> list[Path]:
    return sorted(p for p in PORTAL.glob("*.tsx") if p.name not in NOT_A_PAGE)


def main() -> int:
    faults: list[str] = []
    found = pages()
    if not found:
        print("No portal pages found at all, which cannot be right.")
        return 1

    for page in found:
        text = page.read_text(encoding="utf-8")
        name = page.name

        # 1. It is drawn inside the shared frame.
        if "PortalShell" not in text:
            faults.append(
                f"{name} does not use PortalShell. Every portal is drawn in "
                f"the one frame, so a header cannot drift away from the "
                f"others the way four of them already did.")

        # 2. The vendor's name is not its masthead.
        for hit in re.finditer(r"RX5000|Rx5000", text):
            line = text[:hit.start()].count("\n") + 1
            faults.append(
                f"{name}:{line} names the software vendor on a page the "
                f"pharmacy's own customer reads. The masthead is theirs; "
                f"'Powered by RX5000' belongs in PortalShell's footer.")

        # 3. It asks who the pharmacy is rather than assuming.
        if "useBrand(" not in text:
            faults.append(
                f"{name} never calls useBrand, so whatever it shows at the "
                f"top is not this pharmacy's name.")

    # The frame is allowed to say it, and has to, or nobody is credited.
    shell = (PORTAL / "PortalShell.tsx").read_text(encoding="utf-8")
    if "Powered by RX5000" not in shell:
        faults.append(
            "PortalShell no longer carries 'Powered by RX5000' in its "
            "footer. Demoted is not deleted.")

    if faults:
        print("\nA portal is the pharmacy's shopfront:\n")
        for fault in faults:
            print(f"  X  {fault}")
        print(f"\n{len(faults)} fault(s) across {len(found)} portal page(s).")
        return 1

    print(f"All {len(found)} portals wear the pharmacy's own name.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
