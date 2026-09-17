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
  if (!data) return <p className="muted">Reading the movements…</p>;

  const busiest = Math.max(1, ...data.months.map((m) => Math.max(m.out, m.in)));
  const everything = data.months.some((m) => m.out || m.in || m.adjusted
    || m.written_off || m.moved);

  return (
    <section className="usage">
      <div className="usage-head">
        <div className="usage-sum">
          <b>{data.out_total}</b> units out over {data.months.length} months,
          about <b>{data.a_month}</b> a month
          {data.in_total > 0 && <> · <b>{data.in_total}</b> received</>}
          {data.written_off_total > 0 && (
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

      {!everything ? (
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
            ].filter(Boolean).join(", ") || "nothing moved";
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
        {data.written_off_total > 0 && (
          <> · write-offs are counted out and named in the tooltip, because a
             month that fell because of breakages is not a month demand fell.</>
        )}
      </p>
    </section>
  );
}
