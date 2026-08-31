/** Basket value on a repeat, and what sells in which month.
 *
 *  Two questions an owner asks that nothing here answered.
 *
 *  **What is a repeat patient really worth.** The line value is what has been
 *  measured — the tablets, at the shelf price. A patient collecting a chronic
 *  repeat also buys plasters, a toothbrush, formula, something for their
 *  mother's headache. The repeat is the reason they walked in; the basket is
 *  what they spent. A shop deciding whether to chase a fifteen-dollar repeat is
 *  really deciding about a forty-eight-dollar visit, twelve times a year, for
 *  as long as that patient lives nearby.
 *
 *  **What to have on the shelf before the season.** Malaria treatment moves
 *  with the rains, cough and cold with the cold months, antihistamines with the
 *  jacaranda. A shop ordering on last month's usage is permanently one month
 *  behind its own year.
 *
 *  Both per branch and consolidated, because they are used for different
 *  decisions: the group figure buys from a wholesaler, the branch figure
 *  decides what goes on which shelf.
 *
 *  The screen shows what the data can carry and says so where it cannot. A
 *  seasonal index computed from one observation of a month is labelled as an
 *  observation, not dressed as a season — that label is the most useful thing
 *  on the page, because it is the difference between a buyer committing to an
 *  order and watching for another year.
 */
import { useEffect, useState } from "react";
import { Info, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import Select from "../components/Select";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface BranchBasket {
  branch_id: number | null; branch: string; repeats: number;
  repeat_value: number; basket_value: number; uplift: number;
  average_repeat: number; average_basket: number; average_uplift: number;
  multiple: number | null; attach_rate: number; with_extras: number;
}
interface Basket {
  days: number; repeats: number; unmatched: number; unmatched_note: string;
  linked_directly: number; link_note: string;
  repeat_value: number; basket_value: number; uplift: number;
  average_repeat: number; average_basket: number; average_uplift: number;
  multiple: number | null; attach_rate: number;
  branches: BranchBasket[]; headline: string;
  untrustworthy?: boolean;
  diagnosis?: { repeat_value: number; basket_value: number;
                matched: number; linked_directly: number };
}

interface SeasonRow {
  product_id: number; product: string; occasions: number;
  index: (number | null)[]; peak_month: string; peak_index: number | null;
  trough_month: string; swing: number; seasonal: boolean;
  years_at_peak: number; confident: boolean; action: string;
}
interface Seasons {
  products: SeasonRow[]; counted: number; seasonal: number;
  confident: number; years_needed: number; note: string;
}

interface MonthRow { month: string; sales: number; value: number; share: number }
interface Group {
  group: MonthRow[]; group_busiest: string; group_value: number;
  branches: { branch_id: number; branch: string; months: MonthRow[];
              busiest: string; quietest: string; value: number;
              swing: number; traded: boolean }[];
  disagree: string[];
}

type Tab = "basket" | "seasons" | "group";

export default function Seasons() {
  const [basket, setBasket] = useState<Basket | null>(null);
  const [seasons, setSeasons] = useState<Seasons | null>(null);
  const [group, setGroup] = useState<Group | null>(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "basket", label: "Basket on a repeat",
      hint: "What a repeat visit is worth beyond the line itself" },
    { key: "seasons", label: "What sells when", count: seasons?.seasonal,
      hint: "Lines that move with the calendar" },
    { key: "group", label: "Branch against group",
      hint: "Where a branch's year disagrees with the group's" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "basket");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<Basket>(`/api/insight/basket?days=${days}`),
      api.get<Seasons>("/api/insight/seasons?limit=40"),
      api.get<Group>("/api/insight/seasons/group"),
    ])
      .then(([b, s, g]) => { setBasket(b); setSeasons(s); setGroup(g); })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [days]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Basket &amp; seasons</h1>
          <p className="muted">
            What a repeat patient is worth beyond the line, and what to have on
            the shelf before the month that sells it.
          </p>
        </div>
        {tab === "basket" && (
          <div className="page-actions">
            <Select value={String(days)} onChange={(v) => setDays(Number(v))}
              options={[30, 90, 180, 365].map((d) => ({
                value: String(d), label: `Last ${d} days` }))} />
          </div>
        )}
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      <Refreshable loading={loading} hasData={!!basket}
        skeleton={<TableSkeleton cols={5} rows={6} />}>

        {tab === "basket" && basket && (
          <>
            {/* The refusal, when the two halves of the figure do not describe
                the same transaction. Publishing a multiple below 1 would have
                somebody conclude repeat patients spend nothing. */}
            {basket.untrustworthy ? (
              <div className="alert warn">
                <Warning size={16} weight="fill" />
                <span>{basket.headline}</span>
              </div>
            ) : (
              <>
                <p className="muted">{basket.headline}</p>
                <div className="wc-bands">
                  <div className="wl-stat">
                    <b>{money(basket.average_repeat)}</b>
                    <span>the repeat line is worth</span>
                  </div>
                  <div className="wl-stat">
                    <b className="tone-ok">{money(basket.average_basket)}</b>
                    <span>the visit is worth</span>
                  </div>
                  <div className="wl-stat">
                    <b>{basket.multiple ? `${basket.multiple}×` : "—"}</b>
                    <span>basket per dollar of repeat</span>
                  </div>
                  <div className="wl-stat">
                    <b>{basket.attach_rate}%</b>
                    <span>of repeat visits buy something else</span>
                  </div>
                  <div className="wl-stat">
                    <b>{money(basket.uplift)}</b>
                    <span>beyond the repeats, in this period</span>
                  </div>
                </div>

                <div className="dt-scroll">
                  <table className="dt">
                    <thead>
                      <tr>
                        <th>Branch</th>
                        <th className="num">Repeats</th>
                        <th className="num">Line</th>
                        <th className="num">Basket</th>
                        <th className="num">Multiple</th>
                        <th className="num">Buy extras</th>
                      </tr>
                    </thead>
                    <tbody>
                      {basket.branches.map((b) => (
                        <tr key={b.branch_id ?? "none"}>
                          <td><b>{b.branch}</b></td>
                          <td className="num">{b.repeats.toLocaleString()}</td>
                          <td className="num mono">{money(b.average_repeat)}</td>
                          <td className="num mono">
                            <b>{money(b.average_basket)}</b>
                          </td>
                          {/* The one figure that compares branches fairly
                              whatever medicines they happen to dispense. */}
                          <td className="num">
                            {b.multiple ? `${b.multiple}×`
                              : <span className="muted">—</span>}
                          </td>
                          <td className="num">{b.attach_rate}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {(basket.link_note || basket.unmatched_note) && (
              <p className="muted small">
                <Info size={13} /> {basket.link_note} {basket.unmatched_note}
              </p>
            )}
          </>
        )}

        {tab === "seasons" && seasons && (
          <>
            {/* The honest half, and the first thing on the tab rather than a
                footnote. A buyer who knows a figure came from one December
                treats it differently from one who does not, and that is the
                difference between committing to an order and watching. */}
            <div className={`alert ${seasons.confident ? "" : "warn"}`}>
              <Info size={16} weight="fill" />
              <span>{seasons.note}</span>
            </div>

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th className="num">Times out</th>
                    <th>Busiest</th>
                    <th className="num">vs a typical month</th>
                    <th>The year</th>
                    <th>What to do</th>
                  </tr>
                </thead>
                <tbody>
                  {seasons.products.filter((p) => p.seasonal).map((p) => (
                    <tr key={p.product_id}>
                      <td>
                        <EntityLink kind="product" id={p.product_id}>
                          {p.product}
                        </EntityLink>
                        <div>
                          <span className={`badge ${p.confident ? "ok" : "muted"}`}>
                            {p.confident
                              ? `seen in ${p.years_at_peak} years`
                              : "one observation"}
                          </span>
                        </div>
                      </td>
                      <td className="num">{p.occasions.toLocaleString()}</td>
                      <td><b>{p.peak_month}</b></td>
                      <td className="num">
                        {p.peak_index ? `${p.peak_index}×` : "—"}
                      </td>
                      {/* Twelve cells, one per month, so the shape is read
                          rather than inferred from two numbers. */}
                      <td>
                        <span className="season-strip">
                          {p.index.map((v, i) => (
                            <span key={i}
                              className={`season-cell${v === null ? " is-blank" : ""}`}
                              title={`${MONTHS[i]}: ${v === null ? "not seen"
                                : `${v}× a typical month`}`}
                              style={v === null ? undefined : {
                                opacity: Math.min(1, 0.15 + v / 3),
                              }} />
                          ))}
                        </span>
                      </td>
                      <td className="wrap muted small">{p.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {tab === "group" && group && (
          <>
            <div className="wc-bands">
              <div className="wl-stat">
                <b>{group.group_busiest}</b><span>the group's busiest month</span>
              </div>
              <div className="wl-stat">
                <b>{money(group.group_value)}</b><span>across the year</span>
              </div>
              <div className={`wl-stat${group.disagree.length ? " wc-stale" : ""}`}>
                <b>{group.disagree.length}</b>
                <span>branches whose year differs</span>
              </div>
            </div>

            {group.disagree.length > 0 && (
              // The rows worth reading. A branch whose busiest month is not the
              // group's is one the group buying pattern is actively wrong for.
              <p className="alert warn">
                <Warning size={16} weight="fill" />
                <span>
                  <b>{group.disagree.join(", ")}</b>{" "}
                  {group.disagree.length === 1 ? "has a" : "have"} busiest
                  month{group.disagree.length === 1 ? "" : "s"} that
                  {group.disagree.length === 1 ? " is" : " are"} not the
                  group's. Buying to the group's year is actively wrong for
                  {group.disagree.length === 1 ? " it" : " them"}.
                </span>
              </p>
            )}

            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Branch</th><th className="num">Year</th>
                    <th>Busiest</th><th>Quietest</th>
                    <th className="num">Swing</th><th>The year</th>
                  </tr>
                </thead>
                <tbody>
                  {group.branches.map((b) => {
                    const top = Math.max(...b.months.map((m) => m.value), 1);
                    return (
                      <tr key={b.branch_id}>
                        <td><b>{b.branch}</b></td>
                        <td className="num mono">{money(b.value)}</td>
                        <td>
                          {b.traded ? b.busiest
                            : <span className="muted">no trade recorded</span>}
                          {b.traded && b.busiest !== group.group_busiest && (
                            <div><span className="badge warn">
                              not the group's
                            </span></div>
                          )}
                        </td>
                        <td className="muted">{b.quietest || "—"}</td>
                        <td className="num">{b.swing}</td>
                        <td>
                          <span className="season-strip">
                            {b.months.map((m, i) => (
                              <span key={i} className="season-cell"
                                title={`${m.month}: ${money(m.value)}`}
                                style={{ opacity: Math.max(0.08, m.value / top) }} />
                            ))}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Refreshable>
    </div>
  );
}
