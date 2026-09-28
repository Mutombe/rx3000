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
import { Block, Figure, GhostRows } from "../components/Skeleton";
import { rateTone } from "../tone";
import { Link } from "react-router-dom";
import PageHead from "../components/PageHead";

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
  if (value === null) return <span className="muted">Not counted</span>;
  // Through the shared rule rather than a copy of it. Two screens each with
  // their own thresholds is how a 79% comes to be amber on one page and green
  // on the next, which teaches a reader to distrust the colour.
  return <span className={`badge ${rateTone(value, good)}`}>{value}%</span>;
}

export default function Scorecard() {
  /* `data` being null IS "there is nothing on screen yet", so there is no
     separate loading flag any more: the bands read it directly and pulse the
     figure they are still waiting for. `spinning` is a different thing, the
     deliberate half-second on the Refresh button. */
  const [data, setData] = useState<Card | null>(null);
  const [days, setDays] = useState("30");
  const [error, setError] = useState("");
  const [spinning, setSpinning] = useState(false);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Card>(`/api/scorecard?days=${days}`)
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(errorText(e, "The scorecard could not be loaded.")))
      .finally(() => {
        window.setTimeout(() => setSpinning(false), 350);
      });
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const rows = data?.branches ?? [];
  const t = data?.totals ?? {};

  return (
    <>
      <PageHead
        title="Branch scorecard"
        sub="Which shop is working, and which is quietly not"
        /* The period IS the subject on a comparison page rather than a filter
           over a list, so it sits with the actions rather than in a rail the
           page does not have. */
        also={
          <>
            <Select value={days} onChange={setDays} options={WINDOWS} />
            <button className="btn secondary" onClick={load}>
              <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
            </button>
          </>
        }
      />

      {error && <div className="alert error">{error}</div>}

      {/* SCOPED LOADING.
       *
       * The whole page used to sit behind `data &&`, with a seven column table
       * skeleton standing in for it. What that withheld was not figures: it was
       * the seven band labels, the heading "How the money arrived" and the
       * three payment labels under it, none of which are fetched. They say the
       * same thing on every visit, and a manager opening this screen on a slow
       * morning was shown grey bars instead of being told what the page was
       * about to compare.
       *
       * So the bands and their words are unconditional and only the figures
       * pulse. One `data` flag for all of them, because they all come out of
       * the one request. */}
      <div className="wc-bands">
        <div className="wl-stat">
          <b><Figure ready={!!data} w="9ch">{money(t.sales_value ?? 0)}</Figure></b>
          <span>Taken, all branches</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!data} w="4ch">{t.sales_count ?? 0}</Figure></b>
          <span>Sales</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!data} w="9ch">{money(t.stock_at_cost ?? 0)}</Figure></b>
          <span>Stock at cost</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!data} w="4ch">{t.claims_raised ?? 0}</Figure></b>
          <span>Claims raised</span>
        </div>
        {/* The warning tones are held back until the figure behind them is
            real. A band cannot be flagged stale on the strength of a nought
            nobody has counted yet. */}
        <div className={`wl-stat${(t.repeats_overdue ?? 0) > 0 ? " wc-stale" : ""}`}>
          <b><Figure ready={!!data} w="3ch">{t.repeats_overdue ?? 0}</Figure></b>
          <span>Repeats overdue</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!data} w="3ch">{t.orders_raised ?? 0}</Figure></b>
          <span>Orders raised</span>
        </div>
        <div className={`wl-stat${(t.portal_waiting ?? 0) > 0 ? " wc-stale" : ""}`}>
          <b><Figure ready={!!data} w="3ch">{t.portal_waiting ?? 0}</Figure></b>
          <span>Portal scripts waiting</span>
        </div>
      </div>

      {/* How the money arrived across the group. A shop taking everything in
          cash and a shop taking half on mobile are different businesses to
          run, and the difference is invisible in a takings total. */}
      <div className="card">
        <h3>How the money arrived</h3>
        <div className="wc-bands">
          <div className="wl-stat">
            <b><Figure ready={!!data} w="9ch">{money(t.cash ?? 0)}</Figure></b>
            <span>Cash</span>
          </div>
          <div className="wl-stat">
            <b><Figure ready={!!data} w="9ch">{money(t.card ?? 0)}</Figure></b>
            <span>Card</span>
          </div>
          <div className="wl-stat">
            <b><Figure ready={!!data} w="9ch">{money(t.mobile_money ?? 0)}</Figure></b>
            <span>Mobile money</span>
          </div>
        </div>
      </div>

      {/* Twelve columns of figures across one row is not a comparison,
          it is a wall. Every value truncated mid-word, and the branch
          names clipped to "RX5000 …". One card per branch instead, ordered
          by takings, with the numbers grouped the way somebody actually
          reads them: what came in, what it cost, who did it, and what went
          wrong. The detail is a page of its own. */}
      <div className="bp-grid">
        {/* A branch card is nothing but its branch: the name, the takings and
            the findings are all fetched, so there are no words here to keep.
            Three cards of the right shape hold the grid open instead, and the
            "no branches on file" answer below waits until the answer is
            actually in hand. The name keeps its own heading while it waits,
            so the card is the same shape loaded or not and the grid does not
            re-flow around a heading that appears late. */}
        {!data
          ? Array.from({ length: 3 }).map((_, i) => (
              <article key={i} className="card bp-card" aria-busy="true">
                <header className="bp-head">
                  <div>
                    <h3><Figure ready={false} w="14ch">{null}</Figure></h3>
                    <div className="muted small">
                      <Figure ready={false} w="10ch">{null}</Figure>
                    </div>
                  </div>
                </header>
                <div className="bp-headline">
                  <Block w="9ch" h={22} />
                  <Block w="26ch" h={12} />
                </div>
                <div className="bp-figures">
                  {Array.from({ length: 8 }).map((__, j) => (
                    <div key={j}><Block w="60%" h={11} /><Block w="7ch" h={13} /></div>
                  ))}
                </div>
              </article>
            ))
          : rows.map((b) => (
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
                  /* NAMED, AND NOW WITH SOMEWHERE TO GO.
                     Seven findings, every one of them the subject of a screen
                     that can do something about it, and not one of them was a
                     link. A manager read "14 uncollected" here and then went
                     looking for the will call shelf through the navigation,
                     which is the moment most of these stop being acted on.
                     The dashboard already does it this way: the sentence and
                     the route it leads to, together. */
                  <ul className="bp-flags">
                    {b.sales.pending > 0 && (
                      <li><Link to="/money-owed">
                        <b>{b.sales.pending}</b> sales unpaid</Link></li>)}
                    {b.cashup.total_variance > 0.005 && (
                      <li><Link to="/reconciliation">
                        <b>{money(b.cashup.total_variance)}</b> out at cash-up</Link></li>)}
                    {b.stock.short_dated > 0 && (
                      <li><Link to="/stock?tab=batches">
                        <b>{b.stock.short_dated}</b> short dated</Link></li>)}
                    {b.claims.rejected > 0 && (
                      <li><Link to="/claiming">
                        <b>{b.claims.rejected}</b> claims rejected</Link></li>)}
                    {b.dispensing.uncollected > 0 && (
                      <li><Link to="/will-call">
                        <b>{b.dispensing.uncollected}</b> uncollected</Link></li>)}
                    {b.deliveries.failed > 0 && (
                      <li><Link to="/deliveries?tab=failed">
                        <b>{b.deliveries.failed}</b> deliveries failed</Link></li>)}
                    {b.buying.outstanding > 0 && (
                      <li><Link to="/orders">
                        <b>{b.buying.outstanding}</b> orders outstanding</Link></li>)}
                  </ul>
                )}
              </article>
            ))}
      </div>
      {data && rows.length === 0 && (
        <div className="card">
          <div className="empty">
            <b>This pharmacy has no branches on file</b>
            <p>Every figure on this page is grouped by branch, so there is
               nothing to compare until there is more than one.</p>
          </div>
        </div>
      )}

      {/* Said in words rather than shown as nought.
          WHICH measures are unmeasured is the answer; that this page has a
          section admitting to some is written here, so the heading and the
          paragraph under it are on screen from the first frame and only the
          list of gaps pulses. The card goes away once the answer says there
          are no gaps, which is a thing that can only be known afterwards. */}
      {(!data || data.not_measured.length > 0) && (
            <div className="card">
              <h3><Info size={15} /> What this screen does not measure</h3>
              <p className="muted">
                These would each show a confident nought if the screen pretended
                to know them, and a nought here reads as &ldquo;we did none of
                it&rdquo; rather than &ldquo;nobody is recording it&rdquo;. They
                are listed so the gap is a decision rather than a surprise.
              </p>
              <table className="dt">
                {!data ? (
                  <GhostRows cols={2} rows={3} widths={["12ch", "70%"]} />
                ) : (
                  <tbody>
                    {data.not_measured.map((m) => (
                      <tr key={m.metric}>
                        <td style={{ width: "16rem" }}><b>{m.metric}</b></td>
                        <td className="wrap muted">{m.why}</td>
                      </tr>
                    ))}
                  </tbody>
                )}
              </table>
            </div>
          )}
    </>
  );
}
