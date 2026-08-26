import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api";

/** What needs doing, per navigation entry.
 *
 *  "Action responsive" is the whole point: a badge that only loads once is a
 *  number from whenever the tab was opened, and an operator who clears a queue
 *  and watches the badge keep its old figure stops trusting the sidebar within a
 *  day. So it refreshes on three signals:
 *
 *    - on navigation, because arriving somewhere usually means leaving work
 *      finished behind you;
 *    - on a timer, for work other people are doing at other tills;
 *    - when the window regains focus, because a till left alone for an hour is
 *      showing an hour-old picture.
 *
 *  One request answers every badge, so the numbers are consistent with each
 *  other — fourteen separate calls could not promise that.
 */
export function useNavCounts(): Record<string, number> {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const location = useLocation();

  const load = useCallback(() => {
    api.get<Record<string, number>>("/api/nav/counts")
      .then(setCounts)
      // A failed count is not worth a toast: the sidebar simply shows no badge
      // rather than a wrong one, and the next tick tries again.
      .catch(() => undefined);
  }, []);

  useEffect(load, [load, location.pathname]);

  useEffect(() => {
    const timer = window.setInterval(load, 90_000);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", onFocus); };
  }, [load]);

  return counts;
}

/** Rounded so a four-figure backlog does not widen the rail. The exact number
 *  is on the title attribute, because "1.3k" is a shape and 1,316 is the fact. */
export function shortCount(n: number): string {
  if (n < 1000) return String(n);
  const k = n / 1000;
  return `${k >= 10 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, "")}k`;
}
