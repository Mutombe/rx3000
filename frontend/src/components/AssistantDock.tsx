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
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { X, Sparkle, ArrowSquareOut, CornersOut, CornersIn, NotePencil }
  from "@phosphor-icons/react";
import { Link, useLocation } from "react-router-dom";

import { readStored, writeStored } from "../storage";
import { clearThread, getThread, subscribeThread } from "../assistantThread";
import AssistantChat from "./AssistantChat";

const OPEN = "assistant_dock_open";
const SEEN = "assistant_dock_seen";
const BIG = "assistant_dock_big";

/** Whether the dock should be showing. Read once at mount and kept here, so
 *  the top bar button and the dock cannot disagree about it. */
/** Screens whose primary action sits where this panel does.
 *
 *  The dock is fixed to the bottom right at 480 by 347. The dispensary's
 *  Finish button is in the same corner, and measuring it at 1500x980 and at
 *  1366x768 showed the button was not reachable at all: on a first sign-in
 *  the panel opened itself straight over it, so a dispenser's first script
 *  could not be completed until they worked out that the chat window had to
 *  be closed. Raising the button above the panel does not work, because the
 *  sticky row is inside an ancestor that traps it in its own stacking
 *  context, and fighting that would be fragile in both directions.
 *
 *  So the panel does not OPEN ITSELF here. It is still one press away on the
 *  top bar, which is where somebody reaches for it deliberately, and it still
 *  opens itself everywhere else, which is what made it discoverable. */
const CROWDED = [/^\/dispense/, /^\/till/, /^\/pos/];

export function useDock() {
  const crowded = CROWDED.some((r) => r.test(window.location.pathname));
  const [open, setOpen] = useState(() => {
    try {
      // On for everybody, the first time. That was the decision, and the
      // reason is that nobody goes looking for an assistant they have not
      // seen. After that it is whatever they last chose.
      //
      // Except where it would land on the work: see CROWDED above. A first
      // run there leaves it closed and unremembered, so the next screen
      // still introduces it.
      if (readStored(SEEN) !== "1") return !crowded;
      return readStored(OPEN) === "1";
    } catch { return !crowded; }
  });
  const set = (next: boolean) => {
    setOpen(next);
    try { writeStored(OPEN, next ? "1" : "0"); writeStored(SEEN, "1"); } catch { /* private window */ }
  };
  // Read inside the handler rather than captured, so the binding below does not
  // have to be torn down and rebuilt every time the dock opens or closes.
  const openRef = useRef(open);
  openRef.current = open;

  // Ctrl with K, which is what every other assistant in the world opens on,
  // so nobody has to be told. Bound once here rather than in the panel,
  // because the point of it is opening the panel when it is not there.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        set(!openRef.current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return { open, setOpen: set };
}

export default function AssistantDock({ open, onClose }: {
  open: boolean;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement | null>(null);
  // Wide, for an answer with a diagram in it, and remembered. A dock that is
  // the right size for "where is the register" is the wrong size for a claim
  // lifecycle drawn across it.
  const [big, setBig] = useState(() => {
    try { return readStored(BIG) === "1"; } catch { return false; }
  });
  const grow = (next: boolean) => {
    setBig(next);
    try { writeStored(BIG, next ? "1" : "0"); } catch { /* private window */ }
  };
  // Not on top of the page it is a smaller copy of. Two views of one
  // conversation side by side is a choice nobody should have to make about
  // which one to type into.
  const onItsOwnPage = useLocation().pathname.startsWith("/assistant");

  // Only to know whether there is anything to put down; the conversation
  // itself is drawn by the chat.
  const thread = useSyncExternalStore(subscribeThread, getThread, getThread);

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

  if (!open || onItsOwnPage) return null;

  return (
    // No scrim. The page behind stays usable on purpose: the routes it draws
    // point at that page, and a layer that blocks the thing it is pointing at
    // would be pointing at nothing.
    <aside className={`ax-dock${big ? " is-big" : ""}`} ref={panel}
           aria-label="RX-Assistant">
      <header className="ax-dock-head">
        <span className="ax-dock-name">
          <Sparkle size={14} weight="fill" /> RX-Assistant
        </span>
        <span className="ax-dock-acts">
          {/* The thread now survives being closed, reopened, made bigger and
              navigated away from, which is the point of it. That makes a way
              to put it down deliberately necessary: without one the only way
              to start a fresh question was to lose the last one by accident,
              which is what this was doing before. */}
          {thread.length > 0 && (
            <button type="button" className="ax-dock-btn" onClick={clearThread}
                    title="Start a new conversation"
                    aria-label="Start a new conversation">
              <NotePencil size={15} />
            </button>
          )}
          <button type="button" className="ax-dock-btn" onClick={() => grow(!big)}
                  title={big ? "Make it smaller" : "Make it bigger"}
                  aria-label={big ? "Make it smaller" : "Make it bigger"}>
            {big ? <CornersIn size={15} /> : <CornersOut size={15} />}
          </button>
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
