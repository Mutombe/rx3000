/** Stock the pharmacy owns and may not hand over.
 *
 *  Expired stock was already unsellable, because the dispensing walk filters
 *  on the date. That is the safety half and only the safety half: the stock
 *  was invisible rather than held. Nobody could list it, nobody was asked to
 *  do anything about it, and it sat on a real shelf where a person could
 *  reach it.
 *
 *  WHY THE VALUE IS AT THE TOP
 *
 *  Because that is the decision. A pharmacy holding two hundred dollars of
 *  expired stock tidies it up when there is a quiet afternoon; one holding
 *  four thousand has a conversation with a supplier this week. The list
 *  underneath is what that conversation is about, dearest first.
 *
 *  RELEASING IS NOT THE SAME BUTTON AS HOLDING
 *
 *  Holding is offered to anybody who may adjust stock, because stopping
 *  goods going out is what somebody should be able to do the moment they see
 *  a cracked bottle. Releasing asks for the write-off capability instead, and
 *  the asymmetry is deliberate: deciding a problem is over is a bigger
 *  decision than noticing one.
 */
import { useCallback, useEffect, useState } from "react";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { EntityLink } from "./Filters";
import { useToast } from "./Toast";
import { useCan } from "../session";

interface Held {
  batch_id: number;
  product_id: number;
  product: string;
  batch: string;
  expiry: string;
  quantity: number;
  value: number;
  why: string;
  reason_code: string;
  note: string;
  since: string;
  by: string;
  supplier_id: number | null;
  supplier: string;
  on_return: boolean;
}

export default function Quarantine() {
  const toast = useToast();
  const [lines, setLines] = useState<Held[]>([]);
  const [value, setValue] = useState(0);
  const [units, setUnits] = useState(0);
  const [loading, setLoading] = useState(true);
  const mayRelease = useCan("stock.write_off");
  const mayReturn = useCan("stock.adjust");

  const load = useCallback(() => {
    setLoading(true);
    api.get<{ lines: Held[]; value: number; units: number }>("/api/stock/quarantine")
      .then((r) => { setLines(r.lines); setValue(r.value); setUnits(r.units); })
      .catch((e) => toast.error(errorText(e, "The held stock could not be read.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  async function release(line: Held) {
    // Optimistic: the row leaves on the click, because it has. If the server
    // disagrees it comes back where it was rather than the list reloading,
    // which would lose the place of somebody working down it.
    setLines((all) => all.filter((l) => l.batch_id !== line.batch_id));
    setValue((v) => Math.round((v - line.value) * 100) / 100);
    setUnits((u) => u - line.quantity);
    try {
      const r = await api.post<{ message: string }>(
        `/api/stock/batches/${line.batch_id}/release`, {});
      toast.ok(r.message);
    } catch (e) {
      setLines((all) => [...all, line].sort((a, b) => b.value - a.value));
      setValue((v) => Math.round((v + line.value) * 100) / 100);
      setUnits((u) => u + line.quantity);
      toast.error(errorText(e, "That batch could not be released."));
    }
  }

  async function sendBack(line: Held) {
    if (!line.supplier_id) return;
    // Raised, not approved: the goods are already held, and this adds the
    // paperwork and the claim. Somebody with the write-off capability agrees
    // it afterwards, which is when the stock actually leaves.
    try {
      const said = await api.post<{ message: string }>("/api/supplier-returns", {
        supplier_id: line.supplier_id,
        reason: line.reason_code || "damaged",
        notes: `Raised from held stock. ${line.note}`.trim(),
        lines: [{ batch_id: line.batch_id, quantity: line.quantity }],
      });
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That return could not be raised."));
    }
  }

  return (
    <>
      <div className="qn-head">
        <p className="muted qn-say">
          {lines.length === 0 && !loading
            ? null
            : <>
                <b>{lines.length.toLocaleString()}</b> batch
                {lines.length === 1 ? "" : "es"} held,
                {" "}{units.toLocaleString()} unit{units === 1 ? "" : "s"},
                {" "}<b>{money(value)}</b> at cost. This stock is still owned and
                still counted. It cannot be dispensed, sold or sent to another
                branch until somebody decides what happens to it.
              </>}
        </p>
      </div>

      {/* An empty table is a header over a void, which reads as a screen that
          failed rather than one with nothing to show. The house empty block
          says what would be here and why it is not. */}
      {lines.length === 0 && !loading ? (
        <div className="empty">
          <b>Nothing is being held</b>
          <p>
            Expired stock is taken off the shelf automatically each morning and
            would appear here, along with anything pulled by hand for damage or
            a recall. Held stock stays owned and counted; it simply cannot be
            dispensed, sold or sent to another branch.
          </p>
        </div>
      ) : (
      <Refreshable loading={loading} hasData={lines.length > 0}
                   skeleton={<TableSkeleton cols={5} rows={6}
                                            widths={["30ch", "14ch", "10ch", "12ch", "12ch"]} />}>
        <div className="dt-scroll">
          <table className="dt dt-wider">
            <thead>
              <tr>
                <th>Medicine</th>
                <th>Batch</th>
                <th className="num">Units</th>
                <th className="num">Value at cost</th>
                <th className="col-why wrap-cell">Why, and since</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.batch_id}>
                  <td>
                    <EntityLink kind="product" id={l.product_id}>{l.product}</EntityLink>
                  </td>
                  <td className="mono small">
                    {l.batch || "none"}
                    {l.expiry && (
                      <div className="muted small">expires {fmtDate(l.expiry)}</div>
                    )}
                  </td>
                  <td className="num">{l.quantity.toLocaleString()}</td>
                  <td className="num">{money(l.value)}</td>
                  <td className="qn-why">
                    <span className="badge warn">{l.why}</span>
                    {l.note && <div className="muted small">{l.note}</div>}
                    <div className="muted small">
                      {l.since ? fmtDate(l.since) : ""}{l.by ? ` · ${l.by}` : ""}
                    </div>
                  </td>
                  <td className="actions">
                    {mayReturn && l.supplier_id && !l.on_return && (
                      <button type="button" className="btn small ghost"
                              onClick={() => sendBack(l)}
                              title={`Raise a return to ${l.supplier}. The goods stay held until it is approved.`}>
                        Return to supplier
                      </button>
                    )}
                    {mayRelease && (
                      <button type="button" className="btn small ghost"
                              onClick={() => release(l)}
                              title="Put this batch back on the shelf. It can be dispensed again.">
                        Release
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Refreshable>
      )}
    </>
  );
}
