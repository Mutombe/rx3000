/** Toasts — every action says what happened.
 *
 *  An inline banner has two problems at a counter. It scrolls out of view, so
 *  the confirmation for something you did at the bottom of a long table appears
 *  where you are not looking; and it lives on the page, so navigating away
 *  destroys it before it has been read. A toast is anchored to the viewport and
 *  outlives the route change that caused it.
 *
 *  Three rules that keep them useful rather than noisy:
 *
 *  * **An error does not dismiss itself.** A success can vanish after a few
 *    seconds — the row already shows the new state, so the toast is a
 *    courtesy. A failure is the only record that something did *not* happen,
 *    and taking it away on a timer means the one person who needed to read it
 *    is the one who looked up too late.
 *
 *  * **The message is the server's.** "That password was not accepted", "only
 *    15 in stock", "January 2026 is closed" — these are already written for a
 *    human. Replacing them with "Something went wrong" throws away the only
 *    part that tells anyone what to do next.
 *
 *  * **Identical toasts collapse.** Clicking a failing button four times should
 *    produce one message with a count, not a stack that hides the screen.
 */
import { X } from "@phosphor-icons/react";
import {
  createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";

type Tone = "ok" | "error" | "warn";

interface Toast {
  id: number;
  tone: Tone;
  message: string;
  count: number;
  /** When it appeared. A repeat resets this, so the fifth failure gets its full
   *  time rather than inheriting what was left of the first one's. */
  born: number;
}

interface ToastApi {
  ok: (message: string) => void;
  error: (message: string) => void;
  warn: (message: string) => void;
  /** Report the outcome of a promise without writing the same try/catch again. */
  report: <T>(work: Promise<T>, success: string) => Promise<T | undefined>;
}

const Ctx = createContext<ToastApi | null>(null);

/** How long each tone stays before clearing itself.
 *
 *  Errors used to stay forever, on the reasoning that a failure is the only
 *  record something did not happen. In use that turned the corner of the screen
 *  into a wall of old failures nobody had closed, which hides the next one — the
 *  opposite of the intent.
 *
 *  So they clear too, but slowly, and the timer stops while the pointer is over
 *  the toast or it holds keyboard focus. Nobody loses a message halfway through
 *  reading it, and nothing has to be dismissed by hand to see the screen again.
 */
const LIFETIME: Record<Tone, number> = { ok: 4000, warn: 8000, error: 15000 };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((tone: Tone, message: string) => {
    setToasts((all) => {
      // Collapse a repeat rather than stacking it.
      // A blank toast is a red box that says nothing. Whatever went wrong
      // upstream, the reader gets a sentence.
      message = (message ?? "").toString().trim() ||
        "Something went wrong, and the details did not come back.";
      const same = all.find((t) => t.tone === tone && t.message === message);
      if (same) {
        return all.map((t) =>
          (t === same ? { ...t, count: t.count + 1, born: Date.now() } : t));
      }
      const id = ++seq.current;
      return [...all, { id, tone, message, count: 1, born: Date.now() }];
    });
  }, [dismiss]);

  // One ticker for all of them rather than a timer per toast. A setTimeout
  // captured at push time cannot be paused, and pausing is the whole point: a
  // message that vanishes while somebody is reading it is worse than one that
  // lingers. `paused` is a ref so hovering does not re-render the stack.
  const paused = useRef(false);
  useEffect(() => {
    if (toasts.length === 0) return;
    const tick = window.setInterval(() => {
      if (paused.current) return;
      const now = Date.now();
      setToasts((all) => all.filter((t) => now - t.born < LIFETIME[t.tone]));
    }, 500);
    return () => window.clearInterval(tick);
  }, [toasts.length]);

  const api = useMemo<ToastApi>(() => ({
    ok: (m) => push("ok", m),
    error: (m) => push("error", m),
    warn: (m) => push("warn", m),
    report: async (work, success) => {
      try {
        const result = await work;
        push("ok", success);
        return result;
      } catch (e: any) {
        // The server's wording, not ours.
        push("error", e?.message || "That did not work.");
        return undefined;
      }
    },
  }), [push]);

  // Hand the imperative API to the module-level handle above, so a plain
  // module can raise a toast instead of an `alert`.
  useEffect(() => {
    imperative = api;
    return () => { imperative = null; };
  });

  return (
    <Ctx.Provider value={api}>
      {children}
      <div
        className="toasts" role="status" aria-live="polite"
        // Reading one holds it. Both events, because a keyboard user tabbing to
        // the dismiss button is reading it just as much as a mouse user.
        onMouseEnter={() => { paused.current = true; }}
        onMouseLeave={() => { paused.current = false; }}
        onFocusCapture={() => { paused.current = true; }}
        onBlurCapture={() => { paused.current = false; }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast toast-${t.tone}`}
            // Drives the thin bar that shows the time left, so the toast is
            // visibly going rather than disappearing without warning.
            style={{ ["--toast-life" as string]: `${LIFETIME[t.tone]}ms` }}
          >
            <span className="toast-body">
              {t.message}
              {/* A repeat count sat next to the dismiss button as "×2", beside a
                  "×" that closes the toast — the same glyph meaning two
                  unrelated things an inch apart. It is a plain number now, and
                  it says what it counts. */}
              {t.count > 1 && (
                <span className="toast-count" title={`Happened ${t.count} times`}>
                  {t.count}
                </span>
              )}
            </span>
            <span className="toast-life" aria-hidden="true" />
            <button
              className="toast-close"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
            >
              <X size={14} weight="bold" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

/** The same toasts, for code that is not a component.
 *
 *  `print.ts` is a plain module — it opens a window and writes HTML into it,
 *  and it cannot hold a hook. It was reaching for `alert()` when a pop-up
 *  blocker refused the print window, which is the one moment the operator is
 *  standing at a counter waiting for a receipt: a native box that freezes the
 *  application until somebody clicks OK.
 *
 *  Set once by the provider, so there is still exactly one toast stack and
 *  nothing has to be passed down through five call sites to reach a printer.
 *  Silently does nothing before the provider mounts, which is correct — a
 *  message raised before there is anywhere to show it has nowhere to go, and
 *  throwing there would take down the application over a notification.
 */
let imperative: ToastApi | null = null;

export const toast: ToastApi = {
  ok: (m) => imperative?.ok(m),
  warn: (m) => imperative?.warn(m),
  error: (m) => imperative?.error(m),
  // `report` awaits work and announces the outcome. Before the provider is
  // mounted the work still has to run and its result still has to reach the
  // caller — only the announcement is lost, which is the right thing to drop.
  report: async (work, success) =>
    (imperative ? imperative.report(work, success) : work.catch(() => undefined)),
};

export function useToast(): ToastApi {
  const api = useContext(Ctx);
  if (!api) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return api;
}
