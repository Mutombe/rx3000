import { useCallback, useEffect, useRef, useState } from "react";

/** A sidebar the operator can size, that forgets when they leave.
 *
 *  Kept in `sessionStorage`, not `localStorage`, and that is the whole design:
 *  a till is shared. One pharmacist dragging the rail wide for a long branch
 *  name should not hand the next person a layout they did not choose and cannot
 *  explain. It survives a reload and an accidental navigation — the things that
 *  happen inside one shift, and resets to the default when the session ends.
 *
 *  Bounded at both ends. Below the lower bound the labels wrap, which is the
 *  fault this replaced; above the upper one the navigation is eating width the
 *  data needs. Somebody dragging to an extreme is telling you they want more or
 *  less room, not that they want a broken screen.
 */
const KEY = "rx5000_rail_width";
const MIN = 200;
const MAX = 380;

export function useRailWidth(collapsed: boolean) {
  const [width, setWidth] = useState<number | null>(() => {
    try {
      const saved = Number(sessionStorage.getItem(KEY));
      return Number.isFinite(saved) && saved >= MIN && saved <= MAX ? saved : null;
    } catch { return null; }
  });
  const [dragging, setDragging] = useState(false);
  const frame = useRef(0);

  // Applied as a custom property rather than an inline width, so the collapsed
  // rule can still win by simply not using the variable.
  useEffect(() => {
    const root = document.documentElement;
    if (width) root.style.setProperty("--rail-user", `${width}px`);
    else root.style.removeProperty("--rail-user");
  }, [width]);

  const start = useCallback((event: React.PointerEvent) => {
    if (collapsed) return;
    event.preventDefault();
    setDragging(true);
    const move = (e: PointerEvent) => {
      // Coalesced into a frame: pointermove fires far faster than the screen
      // repaints, and setting state on every one makes the drag feel heavy.
      cancelAnimationFrame(frame.current);
      frame.current = requestAnimationFrame(() => {
        setWidth(Math.min(MAX, Math.max(MIN, Math.round(e.clientX))));
      });
    };
    const end = () => {
      cancelAnimationFrame(frame.current);
      setDragging(false);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      setWidth((w) => {
        try { if (w) sessionStorage.setItem(KEY, String(w)); } catch { /* private mode */ }
        return w;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
  }, [collapsed]);

  /** Keyboard, because a drag handle that only answers a mouse is not a control. */
  const nudge = useCallback((event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 24 : 8;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home") return;
    event.preventDefault();
    setWidth((current) => {
      if (event.key === "Home") { try { sessionStorage.removeItem(KEY); } catch {} return null; }
      const from = current ?? 248;
      const next = Math.min(MAX, Math.max(MIN, from + (event.key === "ArrowRight" ? step : -step)));
      try { sessionStorage.setItem(KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  return { width, dragging, start, nudge, min: MIN, max: MAX };
}
