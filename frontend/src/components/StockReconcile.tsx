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
 *  nothing expired — and that is what decides whether medicine can actually go
 *  out. Almost every screen shows the product's own count instead. So a
 *  pharmacy can be told it has none of something it has three hundred of, and
 *  reorder it.
 *
 *  This does not correct one from the other. Which is right is a question only
 *  somebody holding the box can answer, and the answer is a stock take.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import { EntityLink } from "./Filters";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { useToast } from "./Toast";

interface Line {
  product_id: number; product: string;
  on_hand: number; in_batches: number; usable: number; expired: number;
  difference: number; negative: boolean; value_at_risk: number;
}
interface Report {
  as_at: string; products: number; disagreeing: number; agree_rate: number;
  counted_low: number; counted_high: number; negative: number;
  value_at_risk: number; reconciled: boolean; message: string;
  lines: Line[]; truncated: boolean;
}

export default function StockReconcile() {
  const [data, setData] = useState<Report | null>(null);
  const [spinning, setSpinning] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Report>("/api/stock/reconcile")
      .then(setData)
      .catch((e) => toast.error(errorText(e, "Stock could not be reconciled.")))
      .finally(() => window.setTimeout(() => setSpinning(false), 300));
  }, []);
  useEffect(() => { load(); }, [load]);

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
        <button className="btn secondary" onClick={load}>
          <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
        </button>
      </div>

      <Refreshable loading={spinning || !data} hasData={!!data}
                   skeleton={<TableSkeleton cols={6} rows={8} />}>
        {data && (
          <>
            <div className="wc-bands">
              <div className="wl-stat">
                <b className={data.reconciled ? "tone-ok" : "tone-danger"}>
                  {data.disagreeing}
                </b>
                <span>of {data.products} products disagree</span>
              </div>
              <div className="wl-stat">
                <b>{Math.round(data.agree_rate * 100)}%</b>
                <span>agree with their batches</span>
              </div>
              <div className={`wl-stat${data.value_at_risk > 0.005 ? " wc-stale" : ""}`}>
                <b className={data.value_at_risk > 0.005 ? "neg" : undefined}>
                  {money(data.value_at_risk)}
                </b>
                <span>at cost, on the difference</span>
              </div>
              {data.negative > 0 && (
                <div className="wl-stat wc-abandoned">
                  <b className="tone-danger">{data.negative}</b>
                  <span>counted below nothing</span>
                </div>
              )}
            </div>

            <p className={`alert ${data.reconciled ? "ok" : "warn"}`}>
              {!data.reconciled && <Warning size={16} weight="fill" />}
              <span>{data.message}</span>
            </p>

            {data.lines.length === 0 ? (
              <div className="empty">
                <b>Every product agrees with its batches</b>
                <p>
                  The shelf count and the batch records are the same number
                  everywhere. Nothing to reconcile.
                </p>
              </div>
            ) : (
              <>
                <div className="dt-scroll">
                  <table className="dt">
                    <thead>
                      <tr>
                        <th>Product</th>
                        <th className="num">Own count</th>
                        <th className="num">In batches</th>
                        <th className="num">Usable today</th>
                        <th className="num">Out by</th>
                        <th className="num">At cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.lines.map((l) => (
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
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {data.truncated && (
                  <p className="muted small">
                    The largest differences by value are shown. A stock take is
                    what settles them — this only says where to look.
                  </p>
                )}
              </>
            )}
          </>
        )}
      </Refreshable>
    </div>
  );
}
