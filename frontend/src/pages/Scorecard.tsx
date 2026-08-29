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
  const tone = value >= good ? "ok" : value >= good - 20 ? "warn" : "bad";
  return <span className={`badge ${tone}`}>{value}%</span>;
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

          <div className="card">
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th className="num">Taken</th>
                    <th className="num">Sales</th>
                    <th>How it arrived</th>
                    <th className="num">Stock</th>
                    <th>People</th>
                    <th>Cash-up</th>
                    <th>Dispensing</th>
                    <th>Claims</th>
                    <th>Deliveries</th>
                    <th>Procedure</th>
                    <th>Buying</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((b) => (
                    <tr key={b.branch_id} className={b.active ? "" : "row-flag"}>
                      <td>
                        <EntityLink to={`/branches`}><b>{b.branch}</b></EntityLink>
                        <div className="muted small">
                          {b.code}{b.city ? ` · ${b.city}` : ""}
                          {!b.active && " · closed"}
                        </div>
                      </td>
                      <td className="num">
                        <b>{money(b.sales.value)}</b>
                        <div className="muted small">avg {money(b.sales.average)}</div>
                      </td>
                      <td className="num">
                        {b.sales.count}
                        {/* Dispensed and never settled. The specific failure a
                            group manager is looking for. */}
                        {b.sales.pending > 0 && (
                          <div className="muted small"><b>{b.sales.pending}</b> unpaid</div>
                        )}
                      </td>
                      <td className="small">
                        <div>cash {money(b.money.cash.amount)}</div>
                        <div className="muted">card {money(b.money.card.amount)}</div>
                        <div className="muted">mobile {money(b.money.mobile_money.amount)}</div>
                        <div className="muted">aid {money(b.money.medical_aid.amount)}</div>
                      </td>
                      <td className="num">
                        {money(b.stock.at_cost)}
                        <div className="muted small">{b.stock.units} units · {b.stock.product_lines_sold} lines sold</div>
                        {b.stock.short_dated > 0 && (
                          <div className="muted small"><b>{b.stock.short_dated}</b> short dated</div>
                        )}
                      </td>
                      <td className="small">
                        {b.people.staff} staff · {b.people.tills} tills
                        <div className="muted">{b.people.shifts} shifts
                          {b.people.open_now > 0 && `, ${b.people.open_now} open now`}</div>
                      </td>
                      <td className="small">
                        {pct(b.cashup.accuracy, 95)}
                        <div className="muted">
                          {b.cashup.exact}/{b.cashup.shifts_counted} exact
                        </div>
                        {b.cashup.total_variance > 0.005 && (
                          <div className="muted">{money(b.cashup.total_variance)} out</div>
                        )}
                      </td>
                      <td className="small">
                        {b.dispensing.items} items
                        <div className="muted">checked {pct(b.dispensing.checked_rate, 95)}</div>
                        {b.dispensing.uncollected > 0 && (
                          <div className="muted">{b.dispensing.uncollected} uncollected</div>
                        )}
                        {b.dispensing.controlled > 0 && (
                          <div className="muted">{b.dispensing.controlled} controlled</div>
                        )}
                        <div className="muted">{b.counter.sales} over the counter</div>
                      </td>
                      <td className="small">
                        {b.claims.raised} raised
                        <div className="muted">recovered {pct(b.claims.recovery, 80)}</div>
                        {b.claims.rejected > 0 && (
                          <div className="muted"><b>{b.claims.rejected}</b> rejected</div>
                        )}
                        {b.claims.held > 0 && <div className="muted">{b.claims.held} held</div>}
                      </td>
                      <td className="small">
                        {b.deliveries.raised
                          ? <>{b.deliveries.raised} out<div className="muted">{pct(b.deliveries.success, 90)}</div></>
                          : <span className="muted">none</span>}
                        {b.deliveries.failed > 0 && (
                          <div className="muted"><b>{b.deliveries.failed}</b> failed</div>
                        )}
                      </td>
                      {/* Whether the steps were carried out, from the record
                          made at the time of each dispensing. */}
                      <td className="small">
                        <div>checked {pct(b.sop.checked_rate, 95)}</div>
                        <div className="muted">script sighted {pct(b.sop.sighted_rate, 90)}</div>
                        {b.sop.controlled > 0 && (
                          <div className="muted">
                            ID on controlled {pct(b.sop.id_rate, 100)}
                            <span className="muted"> ({b.sop.controlled})</span>
                          </div>
                        )}
                        {b.counter.sales > 0 && (
                          <div className="muted">counselled {pct(b.sop.counselling_rate, 90)}</div>
                        )}
                      </td>
                      <td className="small">
                        {b.buying.orders
                          ? <>{b.buying.orders} orders
                              <div className="muted">{b.buying.received} received</div>
                              {b.buying.outstanding > 0 && (
                                <div className="muted"><b>{b.buying.outstanding}</b> outstanding</div>
                              )}
                            </>
                          : <span className="muted">none</span>}
                        {b.portal.scripts_in > 0 && (
                          <div className="muted">{b.portal.scripts_in} via portal</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length === 0 && (
              <div className="empty">This pharmacy has no branches on file.</div>
            )}
          </div>

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
