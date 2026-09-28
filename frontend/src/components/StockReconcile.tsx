/** Does the shelf count agree with the batches behind it?
 *
 *  A product carries its own `quantity_on_hand`. Its batches each carry what is
 *  left of them. Two records of the same fact, and the ledger has had a
 *  control-versus-subledger check since it was written for exactly this reason.
 *  Stock had none, and on this database the two had drifted apart on more than
 *  half the catalogue.
 *
 *  It matters because different parts of the software believe different ones.
 *  Dispensing draws against the batches — first expiry first, one branch,
 *  nothing expired, and that is what decides whether medicine can actually go
 *  out. Almost every screen shows the product's own count instead. So a
 *  pharmacy can be told it has none of something it has three hundred of, and
 *  reorder it.
 *
 *  This does not correct one from the other. Which is right is a question only
 *  somebody holding the box can answer, and the answer is a stock take.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowClockwise, ClipboardText, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { EntityLink, FilterToggle } from "./Filters";
import { Figure, GhostRows } from "./Skeleton";
import { useToast } from "./Toast";
import Th from "./Th";

interface Line {
  product_id: number; product: string;
  on_hand: number; in_batches: number; usable: number; expired: number;
  difference: number; negative: boolean; value_at_risk: number;
}
/** A batch whose cost sits a long way from the catalogue's. The other half of
 *  the same question the count answers: not how many, but at what. */
interface CostDrift {
  product_id: number; product: string; batch: string; quantity: number;
  batch_cost: number; catalogue_cost: number; times: number; per_pack: number;
  says: string; value: number;
}
interface Report {
  as_at: string; products: number; disagreeing: number; agree_rate: number;
  counted_low: number; counted_high: number; negative: number;
  value_at_risk: number; reconciled: boolean; message: string;
  lines: Line[]; truncated: boolean;
  cost_drift?: CostDrift[]; cost_drift_total?: number; cost_drift_value?: number;
}

export default function StockReconcile() {
  const [data, setData] = useState<Report | null>(null);
  const [spinning, setSpinning] = useState(false);
  const toast = useToast();
  const [q, setQ] = useState("");
  /** Counted below nothing: the subset that cannot be a counting error in
   *  the ordinary sense, because stock cannot be less than none. */
  const [negOnly, setNegOnly] = useState(false);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Report>("/api/stock/reconcile")
      .then(setData)
      .catch((e) => toast.error(errorText(e, "Stock could not be reconciled.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 300));
  }, []);
  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.lines ?? []).filter((l) =>
      (!needle || l.product.toLowerCase().includes(needle))
      && (!negOnly || l.negative));
  }, [data, q, negOnly]);

  const filtering = Boolean(q.trim()) || negOnly;

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>The shelf count against the batches</h3>
          <span className="muted small">
            Dispensing draws against the batches. Every other screen shows the
            product's own count. Where they disagree, the two tell a pharmacy
            different things about the same shelf.
          </span>
        </div>
        {/* THE REMEDY THIS SCREEN NAMES, IN REACH OF IT.
            Every sentence here ends at "a stock take is what settles them",
            and there was no way to open one: somebody read the worst line,
            went looking for the count screen, and typed the name in again
            from memory. */}
        <div className="rc-acts">
          <Link to="/stock-take" className="btn primary">
            <ClipboardText size={14} weight="bold" /> Start a stock take
          </Link>
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      {/* SCOPED LOADING.
       *
       * Everything below used to be held behind one skeleton table, so the first
       * paint was eight grey rows: the three band captions, the search box, the
       * "Counted below nothing" toggle and seven column heads all arrived later
       * even though every one of them is written in this file. The reader could
       * not even start typing the product name they were holding.
       *
       * Now the frame stands from the first frame and only the counts pulse. Note
       * where the "every product agrees" notice sits: after the test for `data`,
       * never before it. A screen that has not been told anything must not
       * announce that the shelves reconcile. */}
      <div className={`refreshable${spinning || !data ? " is-refreshing" : ""}`}>
          <>
            {/* TWO OF THESE ARE CONTROLS AND TWO ARE READINGS.
                All four were divs carrying .wl-stat, which sets a pointer
                cursor and a hover state because on the queue it came from
                every tile is a filter. Here two of them have nothing to
                narrow to, so they looked clickable, were not, and taught
                somebody the tiles do nothing. The two that can filter are
                buttons; the two that cannot say so by not moving. */}
            <div className="wc-bands">
              <button type="button"
                      className={`wl-stat rc-pick${filtering ? "" : " is-on"}`}
                      aria-pressed={!filtering}
                      onClick={() => { setNegOnly(false); setQ(""); }}>
                <b className={!data ? undefined : data.reconciled ? "tone-ok" : "tone-danger"}>
                  <Figure ready={!!data} w="3ch">{data?.disagreeing}</Figure>
                </b>
                <span>
                  of <Figure ready={!!data} w="4ch">{data?.products}</Figure> products disagree
                  <em className="rc-pick-do">
                    {filtering ? "show all of them" : "showing all of them"}
                  </em>
                </span>
              </button>
              <div className="wl-stat">
                <b>
                  <Figure ready={!!data} w="4ch">
                    {data && Math.round(data.agree_rate * 100)}
                  </Figure>%
                </b>
                <span>Agree with their batches</span>
              </div>
              <div className={`wl-stat${data && data.value_at_risk > 0.005 ? " wc-stale" : ""}`}>
                <b className={data && data.value_at_risk > 0.005 ? "neg" : undefined}>
                  <Figure ready={!!data} w="9ch">{data && money(data.value_at_risk)}</Figure>
                </b>
                <span>At cost, on the difference</span>
              </div>
              {/* Pressable, because it is the worst thing on the screen and
                  was the one figure nobody could act on. Stock cannot be
                  less than none, so these are not counting errors of the
                  ordinary kind: more has gone out than was ever booked in.
                  Held back until the count is in hand, because a tile that
                  says nothing has gone below nothing would be a claim. */}
              {data && data.negative > 0 && (
                <button type="button"
                        className={`wl-stat wc-abandoned rc-pick${negOnly ? " is-on" : ""}`}
                        aria-pressed={negOnly}
                        onClick={() => { setNegOnly(!negOnly); setQ(""); }}>
                  <b className="tone-danger">{data.negative}</b>
                  <span>
                    Counted below nothing
                    <em className="rc-pick-do">
                      {negOnly ? "showing only these" : "show only these"}
                    </em>
                  </span>
                </button>
              )}
            </div>

            {/* The verdict is the server's sentence, so it really is fetched.
                The strip keeps its height while it is on its way rather than
                appearing and shoving the table down. */}
            <p className={`alert ${!data ? "" : data.reconciled ? "ok" : "warn"}`}>
              {data && !data.reconciled && <Warning size={16} weight="fill" />}
              <span><Figure ready={!!data} w="48ch">{data?.message}</Figure></span>
            </p>

            {/* The cost half. Not repaired for the same reason the count is
                not: a batch priced far from the catalogue is either a dear
                delivery or a pack price in a unit column, and rewriting a real
                price to tidy a column destroys the only record of what was
                paid. */}
            {data && data.cost_drift && data.cost_drift.length > 0 && (
              <section className="rc-costs">
                <h4>
                  {data.cost_drift_total} batch
                  {data.cost_drift_total === 1 ? "" : "es"} priced a long way
                  from the catalogue
                </h4>
                <p className="muted small">
                  Holding {money(data.cost_drift_value ?? 0)} of stock between
                  them. Either the delivery was dearer than the catalogue knows,
                  or the figure is a pack price in a unit column. Both are worth
                  a look and neither is worth guessing at.
                </p>
                <ul>
                  {data.cost_drift.map((d) => (
                    <li key={`${d.product_id}-${d.batch}`}>
                      <EntityLink kind="product" id={d.product_id}>
                        {d.product}
                      </EntityLink>
                      <span className="muted">
                        {" · "}batch {d.batch || "unnamed"}
                        {" · "}{d.quantity.toLocaleString()} left
                      </span>
                      <div>{d.says}</div>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {data && data.lines.length === 0 ? (
              <div className="empty">
                <b>Every product agrees with its batches</b>
                <p>
                  The shelf count and the batch records are the same number
                  everywhere. Nothing to reconcile.
                </p>
              </div>
            ) : (
              <>
                {/* 67 lines with no way to find one. Somebody comes here
                    holding a box, and the question is about that box. */}
                <div className="dt-filters">
                  <input type="search" className="filter-search"
                         value={q} placeholder="Find a product…"
                         onChange={(e) => setQ(e.target.value)} />
                  <FilterToggle checked={negOnly} onChange={setNegOnly}
                                hint="Lines whose own count has gone below nothing">
                    Counted below nothing
                  </FilterToggle>
                  {filtering && (
                    <button className="ghost small filter-clear"
                            onClick={() => { setQ(""); setNegOnly(false); }}>
                      Clear
                    </button>
                  )}
                  <span className="dt-count muted">
                    <Figure ready={!!data} w="7ch">
                      {data && <>{shown.length} of {data.lines.length}</>}
                    </Figure>
                  </span>
                </div>

                <div className="dt-scroll">
                  <table className="dt rc-table">
                    <thead>
                      <tr>
                        <Th>Product</Th>
                        {/* col-count (5.5rem) is sized for a bare figure and
                            cut every one of these headings: "Usable today"
                            lost 28px of itself. A column has to be as wide as
                            the question it asks, not as the answer. */}
                        <Th className="num col-money">Own count</Th>
                        <Th className="num col-money">In batches</Th>
                        <Th className="num col-money">Usable today</Th>
                        <Th className="num col-money">Out by</Th>
                        <Th className="num col-money">At cost</Th>
                        <th className="actions" />
                      </tr>
                    </thead>
                    {!data ? (
                      <GhostRows cols={7} rows={8}
                                 widths={["70%", "40%", "40%", "40%", "40%", "60%", "60%"]} />
                    ) : (
                    <tbody>
                      {shown.map((l) => (
                        <tr key={l.product_id}
                            className={l.negative ? "row-danger" : "row-warn"}>
                          <td>
                            <EntityLink kind="product" id={l.product_id}>
                              {l.product}
                            </EntityLink>
                            {l.expired > 0 && (
                              <div className="muted small">
                                {l.expired} of the batch total has expired
                              </div>
                            )}
                          </td>
                          <td className="num">
                            <b className={l.negative ? "neg" : undefined}>
                              {l.on_hand}
                            </b>
                          </td>
                          <td className="num">{l.in_batches}</td>
                          <td className="num">{l.usable}</td>
                          <td className="num">
                            <b className="neg">
                              {l.difference > 0 ? `+${l.difference}` : l.difference}
                            </b>
                          </td>
                          <td className="num">{money(l.value_at_risk)}</td>
                          {/* The transaction that answers this row, on this
                              row. The count screen opens with the product
                              already picked, so the line that raised the
                              question is the line being counted. */}
                          <td className="actions">
                            <Link className="btn small secondary"
                                  to={`/stock-take?product=${l.product_id}`}>
                              Count it
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    )}
                  </table>
                </div>
                {data && shown.length === 0 && (
                  <div className="empty">
                    <b>No disagreement matches that</b>
                    <p>
                      {data.lines.length} product
                      {data.lines.length === 1 ? "" : "s"} disagree with their
                      batches. Widen the search or clear the filters.
                    </p>
                  </div>
                )}
                {data?.truncated && (
                  <p className="muted small">
                    The largest differences by value are shown. A stock take is
                    what settles them. This only says where to look.
                  </p>
                )}
              </>
            )}
          </>
      </div>
    </div>
  );
}
