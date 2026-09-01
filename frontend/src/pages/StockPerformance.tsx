/** Which lines earn their shelf space, and which are eating the float.
 *
 *  A pharmacy's money is on its shelves. Four thousand lines, and the
 *  difference between a good year and a bad one is almost entirely which of
 *  them the buyer puts money into, yet the numbers usually available are
 *  "units sold" and "what is in stock", and neither answers a buying question.
 *
 *  Five columns here, each answering one:
 *
 *    **out** what left the shelf, however it was paid for
 *    **a month** how often somebody wants it — the reorder driver
 *    **cover** how many days the shelf lasts at that rate. The one figure that
 *    says *when*
 *    **GP** earned at the cost frozen on the sale, not at today's cost price
 *    **GMROI** gross profit per dollar of stock held. The figure that exposes
 *    a line with a lovely margin that sells twice a year, and the one nobody
 *    has
 *
 *  On the demo data the last column earns its place immediately: Loratadine
 *  returns 51.9 for every dollar sitting in it, Salbutamol 0.74 — and
 *  Salbutamol sells nearly three times the units. A shop reading units would
 *  buy the wrong one.
 *
 *  **Money only ever comes from lines that carry money.** A dispensing that
 *  never reached a sale has a known quantity and an unknown price. The first
 *  version of this priced them anyway and reported a 1.9 million loss.
 */
import { useEffect, useState } from "react";
import { Info, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import Select from "../components/Select";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

interface Row {
  product_id: number; product: string; department: string; schedule: number;
  units: number; sold_units: number; unpriced_units: number; occasions: number;
  revenue: number; cost: number; profit: number; margin: number | null;
  monthly_usage: number; times_out_a_month: number;
  on_hand: number; held_at_cost: number; days_cover: number | null;
  gmroi: number | null; movement: string; priced: boolean;
  rank?: number; share_of_profit?: number | null; abc?: string;
}
interface Report {
  days: number; products: Row[]; dead: Row[];
  lines_stocked: number; lines_moved: number;
  lines_priced: number; lines_unpriced: number; unpriced_note: string;
  revenue: number; profit: number; margin: number | null;
  held_at_cost: number; dead_money: number; gmroi: number | null;
  classes: Record<string, number>; a_lines: number; headline: string;
}
interface ByBranch {
  days: number;
  branches: { branch_id: number; branch: string; revenue: number;
              profit: number; margin: number | null; gmroi: number | null;
              held_at_cost: number; dead_money: number; lines_moved: number;
              top: { product: string; profit: number; units: number }[] }[];
  group: Record<string, number | null>;
  headline: string;
  /** Dispensings in the window that no branch can claim, because nothing ties
   *  them to a till. They are in the group figures and in none of the branch
   *  figures, which is why the branches need not sum to the group. */
  unattributed_dispensings: number;
  unattributed_share: number;
  /** The same, as a sentence. Empty when the share is too small to matter. */
  caveat: string;
}

type Tab = "lines" | "dead" | "branches";

/** How each movement class reads. Only "dead" is loud, because it is the only
 *  one that is a finding rather than a description. */
const MOVE: Record<string, string> = {
  fast: "ok", steady: "muted", slow: "warn", dead: "bad", none: "muted",
};

export default function StockPerformance() {
  const [report, setReport] = useState<Report | null>(null);
  const [branches, setBranches] = useState<ByBranch | null>(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "lines", label: "What earns", count: report?.lines_moved,
      hint: "Ranked by contribution, not by units" },
    { key: "dead", label: "Not moving", count: report?.dead.length,
      hint: "Money already spent that waiting will not recover" },
    { key: "branches", label: "By branch",
      hint: "A line that flies in one shop is dead in another" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "lines");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<Report>(`/api/insight/movement?days=${days}&limit=200`),
      api.get<ByBranch>(`/api/insight/movement/branches?days=${days}`),
    ])
      .then(([r, b]) => { setReport(r); setBranches(b); })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [days]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Stock performance</h1>
          <p className="muted">
            {report?.headline ?? "What moves, what it earns, and how long the "
              + "shelf lasts."}
          </p>
        </div>
        <div className="page-actions">
          <Select value={String(days)} onChange={(v) => setDays(Number(v))}
            options={[30, 90, 180, 365].map((d) => ({
              value: String(d), label: `Last ${d} days` }))} />
        </div>
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      <Refreshable loading={loading} hasData={!!report}
        skeleton={<TableSkeleton cols={8} rows={8} />}>

        {report && report.unpriced_note && (
          // Said out loud rather than left to be inferred from a small revenue
          // figure. A shop whose dispensings never reached a sale cannot be
          // told anything about margin, and pretending otherwise is worse.
          <div className="alert warn">
            <Info size={16} weight="fill" /> <span>{report.unpriced_note}</span>
          </div>
        )}

        {tab === "lines" && report && (
          <>
            <div className="wc-bands">
              <div className="wl-stat">
                <b>{money(report.revenue)}</b><span>taken</span>
              </div>
              <div className="wl-stat">
                <b className="tone-ok">{money(report.profit)}</b>
                <span>gross profit{report.margin !== null
                  && ` · ${report.margin}%`}</span>
              </div>
              <div className="wl-stat">
                <b>{report.a_lines}</b>
                <span>lines make 80% of it</span>
              </div>
              <div className="wl-stat">
                <b>{money(report.held_at_cost)}</b><span>on the shelves, at cost</span>
              </div>
              <div className={`wl-stat${report.dead_money ? " wc-abandoned" : ""}`}>
                <b className={report.dead_money ? "tone-danger" : undefined}>
                  {money(report.dead_money)}
                </b>
                <span>in lines that have not moved</span>
              </div>
              <div className="wl-stat">
                <b>{report.gmroi ?? "—"}</b>
                <span>gross profit per dollar of stock</span>
              </div>
            </div>

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th className="num">Out</th>
                    <th className="num">A month</th>
                    <th className="num">On hand</th>
                    <th className="num">Cover</th>
                    <th className="num">Taken</th>
                    <th className="num">GP</th>
                    <th className="num">GMROI</th>
                  </tr>
                </thead>
                <tbody>
                  {report.products.map((p) => (
                    <tr key={p.product_id}>
                      <td>
                        <EntityLink kind="product" id={p.product_id}>
                          {p.product}
                        </EntityLink>
                        <div className="muted small">
                          {p.abc && <span className={`badge ${
                            p.abc === "A" ? "ok" : "muted"}`}>{p.abc}</span>}
                          {" "}
                          <span className={`badge ${MOVE[p.movement]}`}>
                            {p.movement}
                          </span>
                          {p.department && ` · ${p.department}`}
                        </div>
                      </td>
                      <td className="num">
                        {p.units.toLocaleString()}
                        {/* Where part of it left without a sale, the money
                            columns beside it describe only the rest. */}
                        {p.unpriced_units > 0 && (
                          <div className="muted small">
                            {p.unpriced_units.toLocaleString()} unpriced
                          </div>
                        )}
                      </td>
                      <td className="num">{p.times_out_a_month}</td>
                      <td className="num">{p.on_hand.toLocaleString()}</td>
                      <td className="num">
                        {p.days_cover === null ? <span className="muted">—</span>
                          : (
                            // The figure that says WHEN. Under a fortnight and
                            // it is on this week's order.
                            <b className={p.days_cover < 14 ? "tone-danger"
                              : p.days_cover < 30 ? "tone-warn" : undefined}>
                              {p.days_cover}d
                            </b>
                          )}
                      </td>
                      <td className="num mono">
                        {p.priced ? money(p.revenue)
                          : <span className="muted">not priced</span>}
                      </td>
                      <td className="num mono">
                        {p.priced ? (
                          <>{money(p.profit)}
                            {p.margin !== null && (
                              <div className="muted small">{p.margin}%</div>
                            )}</>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="num">
                        {p.gmroi === null ? <span className="muted">—</span> : (
                          <b className={p.gmroi >= 3 ? "tone-ok"
                            : p.gmroi < 1 ? "tone-danger" : undefined}>
                            {p.gmroi}
                          </b>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === "dead" && report && (
          <>
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                <b>{money(report.dead_money)}</b> in {report.dead.length} line(s)
                that have not moved in {report.days} days. This is capital
                already spent, and waiting will not recover it, but a slow line
                is not automatically a bad one. A pharmacy stocks some things
                because a patient needs them, not because they turn. The money
                is shown; the decision belongs to somebody who knows the shop.
              </span>
            </div>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Line</th><th>Department</th>
                    <th className="num">On hand</th>
                    <th className="num">Tied up</th>
                  </tr>
                </thead>
                <tbody>
                  {report.dead.map((p) => (
                    <tr key={p.product_id}>
                      <td>
                        <EntityLink kind="product" id={p.product_id}>
                          {p.product}
                        </EntityLink>
                      </td>
                      <td className="muted small">{p.department || "—"}</td>
                      <td className="num">{p.on_hand.toLocaleString()}</td>
                      <td className="num mono"><b>{money(p.held_at_cost)}</b></td>
                    </tr>
                  ))}
                  {!report.dead.length && (
                    <tr><td colSpan={4} className="muted pad">
                      Everything on the shelf has moved in this period.
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === "branches" && branches && (
          <>
            <p className="muted">{branches.headline}</p>
            {/* Said above the table, not under it. A reader who has already
                compared two shops and drawn a conclusion is not going to
                revise it because of a footnote. */}
            {branches.caveat && (
              <div className="alert warn">
                <Warning size={16} weight="fill" />
                <span>{branches.caveat}</span>
              </div>
            )}
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th className="num">Taken</th>
                    <th className="num">GP</th>
                    <th className="num">Margin</th>
                    <th className="num">GMROI</th>
                    <th className="num">Not moving</th>
                    <th>Its best lines</th>
                  </tr>
                </thead>
                <tbody>
                  {branches.branches.map((b) => (
                    <tr key={b.branch_id}>
                      <td><b>{b.branch}</b></td>
                      <td className="num mono">{money(b.revenue)}</td>
                      <td className="num mono">{money(b.profit)}</td>
                      <td className="num">
                        {b.margin !== null ? `${b.margin}%`
                          : <span className="muted">—</span>}
                      </td>
                      {/* The fair comparison. Revenue rewards the biggest shop;
                          this rewards the one that earns most per dollar it has
                          tied up, which is the question an owner is asking. */}
                      <td className="num">
                        {b.gmroi === null ? <span className="muted">—</span> : (
                          <b className={b.gmroi >= 3 ? "tone-ok"
                            : b.gmroi < 1 ? "tone-danger" : undefined}>
                            {b.gmroi}
                          </b>
                        )}
                      </td>
                      <td className="num mono">{money(b.dead_money)}</td>
                      <td className="muted small wrap">
                        {b.top.map((t) => t.product).slice(0, 3).join(", ")
                          || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Refreshable>
    </div>
  );
}
