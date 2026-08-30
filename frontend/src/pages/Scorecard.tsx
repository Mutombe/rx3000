/** How each branch of this pharmacy is doing, side by side.
 *
 *  A group with four shops has one question none of the other screens answer:
 *  which of them is working, and which is quietly not. Every existing report
 *  totals the pharmacy, so a branch losing forty dollars a week at cash-up, or
 *  claiming nothing at all, disappears into the group's figures.
 *
 *  Ordered by takings and read across, because that is how somebody actually
 *  uses it: find the branch, then read what is wrong with it.
 *
 *  Where a measure has nothing behind it the screen says so in words rather
 *  than showing nought. "SOP compliance 0%" gets acted on; "not recorded" gets
 *  the feature asked for, and only one of those is true.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Info, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { EntityLink } from "../components/Filters";
import Select from "../components/Select";
import { TableSkeleton } from "../components/Skeleton";
import { rateTone } from "../tone";

interface Money { count: number; amount: number }
interface Branch {
  branch_id: number; branch: string; code: string; city: string;
  active: boolean; is_default: boolean;
  sales: { count: number; value: number; pending: number; part_paid: number; average: number };
  money: { cash: Money; card: Money; mobile_money: Money; medical_aid: Money; other: Money };
  stock: { batches: number; units: number; at_cost: number; short_dated: number; product_lines_sold: number };
  people: { shifts: number; staff: number; tills: number; open_now: number };
  cashup: { shifts_counted: number; exact: number; total_variance: number; accuracy: number | null };
  dispensing: { items: number; uncollected: number; controlled: number; checked: number; checked_rate: number | null };
  counter: { sales: number; counselled: number; referred: number; counselling_rate: number | null };
  claims: { raised: number; claimed: number; settled: number; rejected: number; held: number; recovery: number | null };
  deliveries: { raised: number; delivered: number; failed: number; success: number | null };
  patients: { served: number };
  sop: {
    dispensings: number; checked: number; script_sighted: number;
    prescriber_verified: number; controlled: number; id_seen_on_controlled: number;
    checked_rate: number | null; sighted_rate: number | null;
    id_rate: number | null; counselling_rate: number | null;
  };
  buying: { orders: number; received: number; outstanding: number };
  portal: { scripts_in: number };
}
interface Card {
  days: number; as_at: string; branches: Branch[];
  totals: Record<string, number>;
  not_measured: { metric: string; why: string }[];
}

const WINDOWS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "60", label: "Last 60 days" },
  { value: "90", label: "Last quarter" },
  { value: "365", label: "Last year" },
];

/** A percentage, or the reason there is not one. */
function pct(value: number | null, good = 90): JSX.Element {
  if (value === null) return <span className="muted">not counted</span>;
  // Through the shared rule rather than a copy of it. Two screens each with
  // their own thresholds is how a 79% comes to be amber on one page and green
  // on the next, which teaches a reader to distrust the colour.
  return <span className={`badge ${rateTone(value, good)}`}>{value}%</span>;
}

export default function Scorecard() {
  const [data, setData] = useState<Card | null>(null);
  /* Distinct from `spinning`, which is the deliberate half-second on the
     Refresh button. This one is "there is nothing on screen yet". */
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState("30");
  const [error, setError] = useState("");
  const [spinning, setSpinning] = useState(false);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Card>(`/api/scorecard?days=${days}`)
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(errorText(e, "The scorecard could not be loaded.")))
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 350);
      });
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const rows = data?.branches ?? [];
  const t = data?.totals ?? {};

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Branch scorecard</h1>
          <div className="sub">Which shop is working, and which is quietly not</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Select value={days} onChange={setDays} options={WINDOWS} />
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {/* Twelve columns of figures a group manager compares across branches.
          An empty frame while they arrive reads as a group with no trade. */}
      {loading && !data && (
        <TableSkeleton cols={7} rows={4}
          widths={["18ch", "12ch", "8ch", "16ch", "12ch", "12ch", "12ch"]} />
      )}

      {data && (
        <>
          <div className="wc-bands">
            <div className="wl-stat"><b>{money(t.sales_value ?? 0)}</b><span>taken, all branches</span></div>
            <div className="wl-stat"><b>{t.sales_count ?? 0}</b><span>sales</span></div>
            <div className="wl-stat"><b>{money(t.stock_at_cost ?? 0)}</b><span>stock at cost</span></div>
            <div className="wl-stat"><b>{t.claims_raised ?? 0}</b><span>claims raised</span></div>
            <div className={`wl-stat${(t.repeats_overdue ?? 0) > 0 ? " wc-stale" : ""}`}>
              <b>{t.repeats_overdue ?? 0}</b><span>repeats overdue</span>
            </div>
            <div className="wl-stat"><b>{t.orders_raised ?? 0}</b><span>orders raised</span></div>
            <div className={`wl-stat${(t.portal_waiting ?? 0) > 0 ? " wc-stale" : ""}`}>
              <b>{t.portal_waiting ?? 0}</b><span>portal scripts waiting</span>
            </div>
          </div>

          {/* How the money arrived across the group. A shop taking everything in
              cash and a shop taking half on mobile are different businesses to
              run, and the difference is invisible in a takings total. */}
          <div className="card">
            <h3>How the money arrived</h3>
            <div className="wc-bands">
              <div className="wl-stat"><b>{money(t.cash ?? 0)}</b><span>cash</span></div>
              <div className="wl-stat"><b>{money(t.card ?? 0)}</b><span>card</span></div>
              <div className="wl-stat"><b>{money(t.mobile_money ?? 0)}</b><span>mobile money</span></div>
            </div>
          </div>

          {/* Twelve columns of figures across one row is not a comparison,
              it is a wall — every value truncated mid-word, and the branch
              names clipped to "RX5000 …". One card per branch instead, ordered
              by takings, with the numbers grouped the way somebody actually
              reads them: what came in, what it cost, who did it, and what went
              wrong. The detail is a page of its own. */}
          <div className="bp-grid">
            {rows.map((b) => (
              <article key={b.branch_id}
                       className={`card bp-card${b.active ? "" : " bp-closed"}`}>
                <header className="bp-head">
                  <div>
                    <h3>{b.branch}</h3>
                    <div className="muted small">
                      {b.code}{b.city ? ` · ${b.city}` : ""}
                      {!b.active && " · closed"}
                    </div>
                  </div>
                  <EntityLink to={`/branches/${b.branch_id}/performance?days=${days}`}>
                    <button className="btn small secondary">Open</button>
                  </EntityLink>
                </header>

                {/* The headline, given the room to be read across a room. */}
                <div className="bp-headline">
                  <b>{money(b.sales.value)}</b>
                  <span>
                    taken over {b.sales.count.toLocaleString()} sale
                    {b.sales.count === 1 ? "" : "s"} · average {money(b.sales.average)}
                  </span>
                </div>

                <div className="bp-figures">
                  <div><span>Cash</span><b>{money(b.money.cash.amount)}</b></div>
                  <div><span>Card</span><b>{money(b.money.card.amount)}</b></div>
                  <div><span>Mobile</span><b>{money(b.money.mobile_money.amount)}</b></div>
                  <div><span>Medical aid</span><b>{money(b.money.medical_aid.amount)}</b></div>
                  <div><span>Stock at cost</span><b>{money(b.stock.at_cost)}</b></div>
                  <div><span>Staff</span><b>{b.people.staff}</b></div>
                  <div><span>Dispensed</span><b>{b.dispensing.items.toLocaleString()}</b></div>
                  <div><span>Over the counter</span><b>{b.counter.sales.toLocaleString()}</b></div>
                </div>

                {/* The rates, where a percentage means something. */}
                <div className="bp-rates">
                  <span>Cash-up {pct(b.cashup.accuracy, 95)}</span>
                  <span>Checked {pct(b.sop.checked_rate, 95)}</span>
                  <span>Claims recovered {pct(b.claims.recovery, 80)}</span>
                  {b.deliveries.raised > 0 && (
                    <span>Deliveries {pct(b.deliveries.success, 90)}</span>
                  )}
                </div>

                {/* What is actually wrong here, and nothing where nothing is.
                    A row of zeroes reads as noise; an empty strip reads as a
                    branch with no problems, which is the point. */}
                {(b.sales.pending > 0 || b.stock.short_dated > 0
                  || b.claims.rejected > 0 || b.dispensing.uncollected > 0
                  || b.deliveries.failed > 0 || b.buying.outstanding > 0
                  || b.cashup.total_variance > 0.005) && (
                  <ul className="bp-flags">
                    {b.sales.pending > 0 && (
                      <li><b>{b.sales.pending}</b> sales unpaid</li>)}
                    {b.cashup.total_variance > 0.005 && (
                      <li><b>{money(b.cashup.total_variance)}</b> out at cash-up</li>)}
                    {b.stock.short_dated > 0 && (
                      <li><b>{b.stock.short_dated}</b> short dated</li>)}
                    {b.claims.rejected > 0 && (
                      <li><b>{b.claims.rejected}</b> claims rejected</li>)}
                    {b.dispensing.uncollected > 0 && (
                      <li><b>{b.dispensing.uncollected}</b> uncollected</li>)}
                    {b.deliveries.failed > 0 && (
                      <li><b>{b.deliveries.failed}</b> deliveries failed</li>)}
                    {b.buying.outstanding > 0 && (
                      <li><b>{b.buying.outstanding}</b> orders outstanding</li>)}
                  </ul>
                )}
              </article>
            ))}
          </div>
          {rows.length === 0 && (
            <div className="card">
              <div className="empty">
                <b>This pharmacy has no branches on file</b>
                <p>Every figure on this page is grouped by branch, so there is
                   nothing to compare until there is more than one.</p>
              </div>
            </div>
          )}

          {/* Said in words rather than shown as nought. */}
          {data.not_measured.length > 0 && (
            <div className="card">
              <h3><Info size={15} /> What this screen does not measure</h3>
              <p className="muted">
                These would each show a confident nought if the screen pretended
                to know them, and a nought here reads as &ldquo;we did none of
                it&rdquo; rather than &ldquo;nobody is recording it&rdquo;. They
                are listed so the gap is a decision rather than a surprise.
              </p>
              <table className="dt">
                <tbody>
                  {data.not_measured.map((m) => (
                    <tr key={m.metric}>
                      <td style={{ width: "16rem" }}><b>{m.metric}</b></td>
                      <td className="wrap muted">{m.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
