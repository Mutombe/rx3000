/** Horizontal page tabs with URL deep-linking.
 *
 *  Every screen shows exactly one dataset at a time. The active tab lives in
 *  `?tab=`, so a view can be linked, bookmarked and reloaded, and the browser
 *  back button steps through tabs the way users expect.
 */
import { ReactNode, useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

export type TabDef<T extends string> = {
  key: T;
  label: string;
  /** Optional record count rendered as a chip on the tab. */
  count?: number;
  hint?: string;
};

export function usePageTabs<T extends string>(tabs: TabDef<T>[], fallback: T) {
  const [params, setParams] = useSearchParams();
  const tab = (tabs.some((t) => t.key === params.get("tab")) ? params.get("tab") : fallback) as T;

  function setTab(next: T) {
    const q = new URLSearchParams(params);
    if (next === fallback) q.delete("tab");
    else q.set("tab", next);
    setParams(q, { replace: true });
  }

  return [tab, setTab] as const;
}

/** A tab strip that stays on one line and scrolls.
 *
 *  Separated from `PageTabs` because eight screens hand-roll their own
 *  `<div className="pill-tabs">` rather than using the component: they keep
 *  their tab state in their own way, and converting them all to URL-backed
 *  tabs is a different change from stopping the strip wrapping. They wrap
 *  their buttons in this instead, and every strip in the product then
 *  behaves the same way, which is the entire point of it looking the same.
 */
export function TabStrip({ children }: { children: ReactNode }) {
  const strip = useRef<HTMLDivElement>(null);
  const wrap = useRef<HTMLDivElement>(null);

  /** Show the fade only while something is actually off the end.
   *
   *  A permanent fade is a lie on the screens whose tabs fit, and on a wide
   *  monitor where Inventory's ten fit too. */
  const mark = useCallback(() => {
    const el = strip.current;
    const box = wrap.current;
    if (!el || !box) return;
    const more = el.scrollWidth - el.clientWidth - el.scrollLeft > 2;
    box.classList.toggle("more", more);
  }, []);

  /** Put the chosen tab fully inside the visible strip.
   *
   *  WORKED OUT FROM WHERE THINGS ACTUALLY ARE ON SCREEN.
   *
   *  Two wrong turns here, both worth naming. `scrollIntoView({ inline:
   *  "nearest" })` moves the minimum it considers necessary, which left the
   *  last tab flush with the edge and under the fade. Replacing it with
   *  `offsetLeft` arithmetic was worse and looked right: the wrapper added
   *  for the fade is `position: relative`, so it became the buttons'
   *  offsetParent, and offsetLeft quietly stopped meaning "distance into the
   *  scrolling content". Bounding rectangles are where things are, whatever
   *  any ancestor is positioned as. */
  const keepActiveInView = useCallback(() => {
    const el = strip.current;
    const active = el?.querySelector<HTMLElement>("button.active, button[aria-selected='true']");
    if (!el || !active) return;
    const margin = 24;
    const box = el.getBoundingClientRect();
    const seat = active.getBoundingClientRect();
    if (seat.right > box.right - margin) {
      el.scrollLeft += seat.right - box.right + margin;
    } else if (seat.left < box.left + margin) {
      el.scrollLeft -= box.left + margin - seat.left;
    }
    mark();
  }, [mark]);

  /** A mouse wheel over the strip scrolls it sideways.
   *
   *  A trackpad can swipe horizontally and a touchscreen can drag, but a
   *  plain wheel over a horizontal scroller does nothing in any browser
   *  unless shift is held, which nobody knows. On a dispensary desktop with
   *  a wheel mouse that meant the tabs past the edge could be seen and not
   *  reached.
   *
   *  The page's own scrolling is left alone unless this strip can use the
   *  movement: hijacking a wheel over something that cannot scroll is how a
   *  page comes to feel stuck. */
  const onWheel = useCallback((e: WheelEvent) => {
    const el = strip.current;
    if (!el) return;
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
    const room = el.scrollWidth - el.clientWidth;
    if (room <= 0) return;
    const next = Math.max(0, Math.min(room, el.scrollLeft + e.deltaY));
    if (next === el.scrollLeft) return;   // at an end: let the page have it
    e.preventDefault();
    el.scrollLeft = next;
  }, []);

  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    mark();
    el.addEventListener("scroll", mark, { passive: true });
    // Not passive: it has to be able to keep the wheel from the page.
    el.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("resize", mark);
    return () => {
      el.removeEventListener("scroll", mark);
      el.removeEventListener("wheel", onWheel);
      window.removeEventListener("resize", mark);
    };
  }, [mark, onWheel]);

  /** Re-run whenever the strip changes size.
   *
   *  THE BUG THIS EXISTS FOR
   *
   *  Running it when the chosen tab changed looked sufficient and was not.
   *  The counts on the tabs arrive from the server AFTER the first render,
   *  and a count makes its tab wider without changing how many tabs there
   *  are. So the strip grew from 1042 to 1326 with nothing re-running, the
   *  position worked out against the old width stayed, and landing straight
   *  on the last tab left it hanging 63px off the end.
   *
   *  Watching the element covers that and everything with the same shape:
   *  the sidebar collapsing, the window resizing, a font arriving late. */
  useEffect(() => {
    const el = strip.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Repositioning changes scrollLeft and not size, so this cannot feed
    // itself.
    const watch = new ResizeObserver(() => keepActiveInView());
    watch.observe(el);
    for (const child of Array.from(el.children)) watch.observe(child);
    return () => watch.disconnect();
  }, [keepActiveInView, children]);

  useEffect(() => { keepActiveInView(); }, [children, keepActiveInView]);

  return (
    <div className="pill-tabs-wrap" ref={wrap}>
      <div className="pill-tabs" role="tablist" ref={strip}>{children}</div>
    </div>
  );
}


export default function PageTabs<T extends string>({ tabs, tab, setTab }: {
  tabs: TabDef<T>[];
  tab: T;
  setTab: (t: T) => void;
}) {
  return (
    <TabStrip>
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={tab === t.key}
          title={t.hint}
          className={tab === t.key ? "active" : ""}
          onClick={() => setTab(t.key)}
        >
          {t.label}
          {t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </TabStrip>
  );
}
