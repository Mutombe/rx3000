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
}

interface ToastApi {
  ok: (message: string) => void;
  error: (message: string) => void;
  warn: (message: string) => void;
  /** Report the outcome of a promise without writing the same try/catch again. */
  report: <T>(work: Promise<T>, success: string) => Promise<T | undefined>;
}

const Ctx = createContext<ToastApi | null>(null);

/** Successes clear themselves; failures do not. */
const LIFETIME: Record<Tone, number | null> = { ok: 4000, warn: 8000, error: null };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((tone: Tone, message: string) => {
    setToasts((all) => {
      // Collapse a repeat rather than stacking it.
      const same = all.find((t) => t.tone === tone && t.message === message);
      if (same) {
        return all.map((t) => (t === same ? { ...t, count: t.count + 1 } : t));
      }
      const id = ++seq.current;
      const life = LIFETIME[tone];
      if (life) window.setTimeout(() => dismiss(id), life);
      return [...all, { id, tone, message, count: 1 }];
    });
  }, [dismiss]);

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

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
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

export function useToast(): ToastApi {
  const api = useContext(Ctx);
  if (!api) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return api;
}
