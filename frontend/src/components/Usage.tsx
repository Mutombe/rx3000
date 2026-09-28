/** What has left this shelf each month, and what came in to replace it.
 *
 *  The stock item says how much is on hand today. It cannot say whether that is
 *  a lot, and the difference between "forty is plenty" and "forty is a
 *  fortnight" is the whole of buying. This is the tab the incumbent gives its
 *  own place for the same reason.
 *
 *  Read off the stock movements rather than off sales, because every way a unit
 *  leaves the shelf writes one — including the ways a sales report never shows.
 *  A buyer looking at a month that dropped needs to know whether that was
 *  demand or a box that got broken, and those are different decisions.
 */
import { useEffect, useState } from "react";

import { api, errorText } from "../api";
import { Block, Figure } from "./Skeleton";

interface Month {
  month: string;
  out: number;
  in: number;
  adjusted: number;
  written_off: number;
  moved: number;
}

interface Usage {
  months: Month[];
  out_total: number;
  in_total: number;
  written_off_total: number;
  a_month: number;
  busiest: string;
}

/** "2026-08" as somebody says it. */
function readable(key: string): string {
  const [year, month] = key.split("-").map(Number);
  if (!year || !month) return key;
  return new Date(year, month - 1, 1)
    .toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
}

export default function Usage({ productId }: { productId: number }) {
  const [data, setData] = useState<Usage | null>(null);
  const [error, setError] = useState("");
  const [months, setMonths] = useState(12);

  useEffect(() => {
    setData(null);
    api.get<Usage>(`/api/products/${productId}/usage?months=${months}`)
      .then(setData)
      .catch((e) => setError(errorText(e, "That history could not be read.")));
  }, [productId, months]);

  if (error) return <p className="alert warn">{error}</p>;

  const busiest = Math.max(1, ...(data?.months ?? []).map((m) => Math.max(m.out, m.in)));
  const everything = !!data && data.months.some((m) => m.out || m.in || m.adjusted
    || m.written_off || m.moved);

  /* SCOPED LOADING.
   *
   * "Reading the movements…" replaced the tab, and it took the window switch
   * with it: a buyer who opened this on 12m and wanted 24m had to wait for the
   * 12m answer before the 24m button existed. The switch is not fetched, it is
   * three numbers written below, and it now stays put and stays pressable while
   * the next window loads.
   *
   * The bars hold their row count from the window that was asked for, so the
   * panel does not grow into the page as the answer lands, and "nothing has
   * moved in this window" waits behind the answer, because it is a finding. */
  return (
    <section className="usage">
      <div className="usage-head">
        <div className="usage-sum">
          <b><Figure ready={!!data} w="4ch">{data?.out_total}</Figure></b> units out over{" "}
          <Figure ready={!!data} w="2ch">{data?.months.length}</Figure> months,
          about <b><Figure ready={!!data} w="3ch">{data?.a_month}</Figure></b> a month
          {data && data.in_total > 0 && <> · <b>{data.in_total}</b> received</>}
          {data && data.written_off_total > 0 && (
            <> · <b className="is-bad">{data.written_off_total}</b> written off</>
          )}
        </div>
        <div className="usage-window" role="radiogroup" aria-label="How far back">
          {[6, 12, 24].map((n) => (
            <button key={n} type="button" role="radio" aria-checked={months === n}
                    className={`usage-win${months === n ? " is-on" : ""}`}
                    onClick={() => setMonths(n)}>{n}m</button>
          ))}
        </div>
      </div>

      {!data ? (
        <ol className="usage-bars" aria-busy="true">
          {Array.from({ length: months }).map((_, i) => (
            <li key={i}>
              <span className="usage-when"><Block w="5ch" h="1em" className="sk-val" /></span>
              <span className="usage-track"><Block w="55%" h={10} /></span>
              <span className="usage-n"><Block w="3ch" h="1em" className="sk-val" /></span>
            </li>
          ))}
        </ol>
      ) : !everything ? (
        <div className="empty">
          <b>Nothing has moved in this window</b>
          <p>
            No units have gone out, come in or been adjusted. A line that does
            not move is worth as much attention as one that runs out.
          </p>
        </div>
      ) : (
        /* A bar each month rather than a chart library. Two quantities, twelve
           points, and the only comparison that matters is one month against the
           next — which a row of bars makes and a line chart of two series does
           not. */
        <ol className="usage-bars">
          {data.months.map((m) => {
            const out = Math.round((m.out / busiest) * 100);
            const came = Math.round((m.in / busiest) * 100);
            const note = [
              m.out ? `${m.out} out` : "",
              m.in ? `${m.in} in` : "",
              m.written_off ? `${m.written_off} written off` : "",
              m.moved ? `${m.moved} moved between branches` : "",
              m.adjusted ? `${m.adjusted} adjusted` : "",
            ].filter(Boolean).join(", ") || "Nothing moved";
            return (
              <li key={m.month} className={m.month === data.busiest ? "is-peak" : ""}>
                <span className="usage-when">{readable(m.month)}</span>
                <span className="usage-track" title={note}>
                  <span className="usage-out" style={{ width: `${out}%` }} />
                  {m.in > 0 && <span className="usage-in" style={{ width: `${came}%` }} />}
                </span>
                <span className="usage-n">{m.out || ""}</span>
              </li>
            );
          })}
        </ol>
      )}

      <p className="muted small usage-key">
        <span className="usage-swatch is-out" /> went out
        <span className="usage-swatch is-in" /> came in
        {data && data.written_off_total > 0 && (
          <> · write-offs are counted out and named in the tooltip, because a
             month that fell because of breakages is not a month demand fell.</>
        )}
      </p>
    </section>
  );
}
