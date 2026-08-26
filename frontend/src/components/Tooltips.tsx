/** One tooltip for the whole application.
 *
 *  Mounted once. It listens for hover and focus at the document level and works
 *  out for itself what deserves a tooltip, which is why nothing else in the
 *  codebase has to remember to add one:
 *
 *    - anything carrying `data-tip`, said deliberately;
 *    - anything with a `title`, adopted so the browser's own tooltip does not
 *      also appear — two tooltips for one element is worse than none;
 *    - **any cell whose text is actually clipped**, which is the case this
 *      exists for. Tables truncate to keep their columns; a truncation with no
 *      way to read the value is data removed, not data shortened.
 *
 *  Truncation is measured at hover, not guessed at render. A cell that fits
 *  today may clip tomorrow when the sidebar is dragged wider or the window is
 *  resized, and a title attribute decided at render would be wrong in both
 *  directions — missing where it is needed, and announcing a value that is
 *  plainly visible.
 *
 *  The native `title` is removed while the element is hovered and put back on
 *  leave, so nothing is lost for a user who never hovers, and screen readers
 *  keep reading the attribute they expect.
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const SHOW_AFTER = 320;   // long enough not to flash while the eye scans a column
const GAP = 8;

interface Shown { text: string; x: number; y: number; below: boolean }

/** Is this element's own text cut off? */
function isClipped(el: HTMLElement): boolean {
  // 1px of slack: sub-pixel layout reports a one-pixel overflow on text that is
  // visibly complete, and a tooltip on every cell in the table is noise.
  return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
}

function tipFor(start: HTMLElement): { host: HTMLElement; text: string } | null {
  let el: HTMLElement | null = start;
  while (el && el !== document.body) {
    const said = el.dataset.tip;
    if (said) return { host: el, text: said };

    const title = el.getAttribute("title");
    if (title) return { host: el, text: title };

    // Only elements that hold text of their own are candidates for the
    // clipped-value case: a wrapper that happens to be narrower than its
    // children is a layout fact, not a hidden value.
    const clippable = el.matches(
      "td, th, .clip, .sel-value, .wl-row-mid, .wl-patient, .nav-label, .rc-xaxis span");
    if (clippable && isClipped(el)) {
      const text = (el.innerText || "").trim();
      if (text) return { host: el, text };
    }
    el = el.parentElement;
  }
  return null;
}

export default function Tooltips() {
  const [shown, setShown] = useState<Shown | null>(null);
  const timer = useRef(0);
  const restore = useRef<{ el: HTMLElement; title: string } | null>(null);

  useEffect(() => {
    const putTitleBack = () => {
      if (restore.current) {
        restore.current.el.setAttribute("title", restore.current.title);
        restore.current = null;
      }
    };

    const hide = () => {
      window.clearTimeout(timer.current);
      putTitleBack();
      setShown(null);
    };

    const consider = (target: EventTarget | null) => {
      if (!(target instanceof HTMLElement)) return;
      const found = tipFor(target);
      if (!found) { hide(); return; }

      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        const box = found.host.getBoundingClientRect();
        if (!box.width) return;

        // Take the native tooltip out of the way for as long as ours is up.
        const title = found.host.getAttribute("title");
        if (title) {
          restore.current = { el: found.host, title };
          found.host.removeAttribute("title");
        }

        // Below by default; above when the element is near the bottom edge.
        const below = box.bottom + GAP + 44 < window.innerHeight;
        setShown({
          text: found.text,
          x: Math.round(box.left + box.width / 2),
          y: Math.round(below ? box.bottom + GAP : box.top - GAP),
          below,
        });
      }, SHOW_AFTER);
    };

    const onOver = (e: PointerEvent) => consider(e.target);
    const onFocus = (e: FocusEvent) => consider(e.target);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };

    document.addEventListener("pointerover", onOver);
    document.addEventListener("pointerdown", hide);
    document.addEventListener("focusin", onFocus);
    document.addEventListener("keydown", onKey);
    // Any movement of the page invalidates the position we measured.
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      window.clearTimeout(timer.current);
      putTitleBack();
      document.removeEventListener("pointerover", onOver);
      document.removeEventListener("pointerdown", hide);
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, []);

  if (!shown) return null;

  return createPortal(
    <div
      className={`tip ${shown.below ? "is-below" : "is-above"}`}
      role="tooltip"
      style={{ left: shown.x, top: shown.y }}
    >
      {shown.text}
    </div>,
    document.body,
  );
}
