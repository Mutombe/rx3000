/** The Command Centre: what to do about today.
 *
 *  This was four counts and a bar chart. A count is a fact — "fourteen low
 *  stock lines" — and a fact is not a decision. It becomes one when it says
 *  what those lines are worth and what happens if nobody acts.
 *
 *  So every figure here is money or leads to money, is compared with the same
 *  period before it so it can be read as good or bad, and links to the screen
 *  that can do something about it. The four questions, in the order an owner
 *  actually asks them:
 *
 *    Is today better or worse than the same day last week?
 *    Which shop is working, and which is only busy?
 *    What am I losing without seeing it — the repeat book?
 *    What is my money doing?
 *
 *  The last card is the point of the page: everything above it, ranked by what
 *  it is worth, with the thing to do written out. A dashboard's job is finished
 *  when somebody knows what to do next.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown, ArrowRight, ArrowUp, ArrowClockwise, Minus,
} from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import { ColumnChart, Donut, Legend, useSeries } from "../components/charts";
import { EntityLink } from "../components/Filters";
import { Block, Refreshable } from "../components/Skeleton";
import { useToast } from "../components/Toast";

interface Trend {
  change: number | null;
  direction: "up" | "down" | "flat";
  was: number;
  compared_with?: string;
}
interface Day {
  date: string; sales: number; value: number; before: number; today: boolean;
}
interface Branch {
  branch_id: number; branch: string; value: number; count: number;
  average: number; cashup_accuracy: number | null; variance: number;
  scripts: number; claims_recovered: number | null; share: number;
}
interface Split {
  reason: string; count: number; value: number; share: number; fix: string;
}
interface Data {
  as_at: string; days: number;
  today: Trend & { value: number; sales: number };
  period: Trend & { value: number };
  series: Day[];
  branches: Branch[];
  repeats: {
    due: number; due_value: number; captured: number; captured_value: number;
    lost: number; lost_value: number; value_loss_rate: number | null;
    on_time: number | null; on_time_rate: number | null;
    due_today: number; due_today_value: number;
    split: Split[]; average_value: number;
  };
  money: { owed_to_us: number; owed_to_us_count: number;
           claims_recovered: number | null };
  shelf: { short_lines: number; reorder_cost: number;
           expiring_batches: number; expiring_value: number };
  actions: { what: string; worth: number; do: string; to: string; tone: string }[];
}

/** A figure with the direction it moved, or silence where there is nothing to
 *  compare against. "+100%" on a first week in business is a number somebody
 *  could act on wrongly. */
function Move({ trend }: { trend: Trend }) {
  if (trend.change === null) {
    return <span className="muted small">nothing to compare against yet</span>;
  }
  const pct = Math.abs(Math.round(trend.change * 100));
  const Icon = trend.direction === "up" ? ArrowUp
    : trend.direction === "down" ? ArrowDown : Minus;
  return (
    <span className={`cc-move is-${trend.direction}`}>
      <Icon size={12} weight="bold" />
      {pct}% <span className="muted">against {trend.compared_with}</span>
    </span>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [spinning, setSpinning] = useState(false);
  const series = useSeries();
  const toast = useToast();

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Data>("/api/reports/command-centre?days=14")
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(errorText(e, "The command centre could not be loaded.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 300));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (error) {
    return (
      <>
        <div className="page-head"><h1>Command Centre</h1></div>
        <div className="alert error">{error}</div>
      </>
    );
  }

  const compact = (n: number) => money(n);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Command Centre</h1>
          <div className="sub">
            {data
              ? <>The last {data.days} days, to {fmtDate(data.as_at)}</>
              : "Loading the morning's figures"}
          </div>
        </div>
        <div className="row-actions">
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
          <Link to="/pos" className="btn primary">New sale</Link>
        </div>
      </div>

      <Refreshable
        loading={spinning || !data}
        hasData={!!data}
        skeleton={
          <div className="grid cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="card stat"><Block h={64} round="md" /></div>
            ))}
          </div>
        }
      >
        {data && (
          <>
            {/* Four figures, each with the thing it should be read against.
                A number on its own cannot be good or bad. */}
            <div className="grid cols-4">
              <div className="card stat hero">
                <div className="label">Taken today</div>
                <div className="value accent">{money(data.today.value)}</div>
                <div className="hint">
                  {data.today.sales} sale{data.today.sales === 1 ? "" : "s"} ·{" "}
                  <Move trend={data.today} />
                </div>
              </div>
              <div className="card stat">
                <div className="label">Taken over {data.days} days</div>
                <div className="value">{money(data.period.value)}</div>
                <div className="hint"><Move trend={data.period} /></div>
              </div>
              <div className="card stat">
                <div className="label">Repeat book lost</div>
                <div className="value neg">{money(data.repeats.lost_value)}</div>
                <div className="hint">
                  {data.repeats.value_loss_rate !== null
                    && `${Math.round(data.repeats.value_loss_rate * 100)}% of what fell due · `}
                  <Link to="/repeats?tab=value">
                    where it went <ArrowRight size={12} weight="bold" />
                  </Link>
                </div>
              </div>
              <div className="card stat">
                <div className="label">Dispensed, never settled</div>
                <div className="value">{money(data.money.owed_to_us)}</div>
                <div className="hint">
                  {data.money.owed_to_us_count} sale
                  {data.money.owed_to_us_count === 1 ? "" : "s"} ·{" "}
                  <Link to="/money-owed">chase <ArrowRight size={12} weight="bold" /></Link>
                </div>
              </div>
            </div>

            <div className="grid cols-2">
              {/* Takings, with the same weekday a fortnight ago drawn across
                  each column. A Monday compared with a Monday: comparing a
                  Saturday with the Friday before it is how a pharmacy
                  convinces itself trade collapses every weekend. */}
              <div className="card">
                <div className="card-head">
                  <div>
                    <h3>What came in, day by day</h3>
                    <span className="muted small">
                      The bar is this fortnight. The line across it is the same
                      weekday, the fortnight before.
                    </span>
                  </div>
                </div>
                <ColumnChart
                  height={240}
                  format={compact}
                  markerLabel="the same weekday, a fortnight ago"
                  columns={data.series.map((d) => ({
                    label: fmtDate(d.date).replace(/,.*/, ""),
                    segments: [{ key: "Taken", value: d.value, colour: series[0] }],
                    marker: d.before || undefined,
                  }))}
                />
                <Legend items={[
                  { key: "Taken", colour: series[0] },
                  { key: "A fortnight ago", colour: series[0], dashed: true },
                ]} />
              </div>

              {/* Where the repeat book went. Four buckets that sum exactly to
                  the loss — a breakdown accounting for most of a number and
                  silent about the rest is one nobody trusts. */}
              <div className="card">
                <div className="card-head">
                  <div>
                    <h3>The repeat book, and what happened to it</h3>
                    <span className="muted small">
                      {money(data.repeats.due_value)} fell due ·{" "}
                      {money(data.repeats.captured_value)} filled
                      {data.repeats.on_time_rate !== null
                        && `, ${Math.round(data.repeats.on_time_rate * 100)}% on time`}
                    </span>
                  </div>
                </div>
                <Donut
                  size={172}
                  format={compact}
                  centreLabel="lost"
                  empty="Nothing fell due and went unfilled. The whole book was kept."
                  slices={data.repeats.split.map((s, i) => ({
                    key: s.reason, value: s.value, colour: series[i % series.length],
                  }))}
                />
                <p className="muted small">
                  A repeat that was not filled leaves no record anywhere — the
                  patient simply goes elsewhere next month. This is the one
                  place it appears.
                </p>
              </div>
            </div>

            {/* Which shop is working. Not which is busiest: the branch taking
                the most money is not always the one earning it, so the average
                sale and the cash-up sit beside the total. */}
            <div className="card">
              <div className="card-head">
                <div>
                  <h3>Branches, side by side</h3>
                  <span className="muted small">
                    Over the last {data.days} days. Open one for the workings.
                  </span>
                </div>
                <Link to="/scorecard" className="btn secondary small">
                  Full scorecard
                </Link>
              </div>
              {data.branches.filter((b) => b.value > 0).length === 0 ? (
                <div className="empty">
                  <b>No branch took anything in this period</b>
                  <p>
                    Either trade has stopped or sales are not being recorded
                    against a branch. Both are worth knowing about today.
                  </p>
                </div>
              ) : (
                // Eight columns will not fit a phone, and squeezing them makes
                // the figures unreadable rather than the table narrow. It
                // scrolls inside its own card instead, so the page never does.
                <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Branch</th>
                      <th className="num">Taken</th>
                      <th className="num">Share</th>
                      <th className="num">Sales</th>
                      <th className="num">Average sale</th>
                      <th className="num">Scripts</th>
                      <th className="num">Drawer</th>
                      <th style={{ width: "12rem" }} />
                    </tr>
                  </thead>
                  <tbody>
                    {data.branches.map((b) => {
                      const best = data.branches[0]?.value || 1;
                      return (
                        <tr key={b.branch_id}>
                          <td>
                            <EntityLink to={`/branches/${b.branch_id}/performance`}>
                              <b>{b.branch}</b>
                            </EntityLink>
                          </td>
                          <td className="num"><b>{money(b.value)}</b></td>
                          <td className="num">{Math.round(b.share * 100)}%</td>
                          <td className="num">{b.count.toLocaleString()}</td>
                          <td className="num">{money(b.average)}</td>
                          <td className="num">{b.scripts.toLocaleString()}</td>
                          <td className="num">
                            {b.cashup_accuracy === null
                              ? <span className="muted">not counted</span>
                              : <span className={`badge ${b.cashup_accuracy >= 95
                                  ? "ok" : b.cashup_accuracy >= 80 ? "warn" : "bad"}`}>
                                  {b.cashup_accuracy}%
                                </span>}
                          </td>
                          <td>
                            {/* Against the best branch, so the bar is a
                                comparison and not decoration. */}
                            <span className="cc-bar"
                                  style={{ width: `${Math.max(2, (b.value / best) * 100)}%`,
                                           background: series[0] }} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                </div>
              )}
            </div>

            {/* The point of the page. */}
            <div className="card">
              <div className="card-head">
                <div>
                  <h3>What to do about it</h3>
                  <span className="muted small">
                    Worth most first. Every line is a figure from this page with
                    the thing to do written out.
                  </span>
                </div>
              </div>
              {data.actions.length === 0 ? (
                <div className="empty">
                  <b>Nothing is waiting</b>
                  <p>
                    No repeat is overdue, nothing is short on the shelf, and
                    every sale has been settled. That is what this page looks
                    like on a good morning.
                  </p>
                </div>
              ) : (
                <ul className="cc-actions">
                  {data.actions.map((a, i) => (
                    <li key={i} className={`cc-action is-${a.tone}`}>
                      <div className="cc-action-worth">
                        <b>{money(a.worth)}</b>
                      </div>
                      <div className="cc-action-what">
                        <b>{a.what}</b>
                        <span className="muted">{a.do}</span>
                      </div>
                      <Link to={a.to} className="btn small secondary">
                        Open <ArrowRight size={12} weight="bold" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </Refreshable>
    </>
  );
}
