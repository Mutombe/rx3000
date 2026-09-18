/** RX-Assistant in the corner, where somebody can ask without leaving the work.
 *
 *  The whole value of an assistant in a dispensary is that the question arrives
 *  mid-script, with a patient at the counter. Sending somebody to a separate
 *  page to ask it means abandoning what they were doing, which is the reason
 *  they will not ask.
 *
 *  So it opens over the screen they are on, and the routes it draws navigate
 *  the page behind it. On a narrow screen it takes the whole width, because a
 *  380px panel on a 400px phone is a panel with no room to read in.
 *
 *  Open by default the first time, and never again once somebody has closed
 *  it. A thing that reappears after being dismissed is not a feature, it is a
 *  pop-up.
 */
import { useEffect, useRef, useState } from "react";
import { X, Sparkle, ArrowSquareOut } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { readStored, writeStored } from "../storage";
import AssistantChat from "./AssistantChat";

const OPEN = "assistant_dock_open";
const SEEN = "assistant_dock_seen";

/** Whether the dock should be showing. Read once at mount and kept here, so
 *  the top bar button and the dock cannot disagree about it. */
export function useDock() {
  const [open, setOpen] = useState(() => {
    try {
      // On for everybody, the first time. That was the decision, and the
      // reason is that nobody goes looking for an assistant they have not
      // seen. After that it is whatever they last chose.
      if (readStored(SEEN) !== "1") return true;
      return readStored(OPEN) === "1";
    } catch { return true; }
  });
  const set = (next: boolean) => {
    setOpen(next);
    try { writeStored(OPEN, next ? "1" : "0"); writeStored(SEEN, "1"); } catch { /* private window */ }
  };
  return { open, setOpen: set };
}

export default function AssistantDock({ open, onClose }: {
  open: boolean;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement | null>(null);

  // Escape closes it, like every other layer in this product. Bound only while
  // it is open, so it cannot swallow Escape from the script underneath.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    // No scrim. The page behind stays usable on purpose: the routes it draws
    // point at that page, and a layer that blocks the thing it is pointing at
    // would be pointing at nothing.
    <aside className="ax-dock" ref={panel} aria-label="RX-Assistant">
      <header className="ax-dock-head">
        <span className="ax-dock-name">
          <Sparkle size={14} weight="fill" /> RX-Assistant
        </span>
        <span className="ax-dock-acts">
          <Link to="/assistant" className="ax-dock-btn" title="Open the full page"
                aria-label="Open the full page">
            <ArrowSquareOut size={15} />
          </Link>
          <button type="button" className="ax-dock-btn" onClick={onClose}
                  title="Close" aria-label="Close">
            <X size={15} />
          </button>
        </span>
      </header>
      <AssistantChat compact />
    </aside>
  );
}
