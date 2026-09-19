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
}

export default function Quarantine() {
  const toast = useToast();
  const [lines, setLines] = useState<Held[]>([]);
  const [value, setValue] = useState(0);
  const [units, setUnits] = useState(0);
  const [loading, setLoading] = useState(true);
  const mayRelease = useCan("stock.write_off");

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

  return (
    <>
      <div className="qn-head">
        <p className="muted qn-say">
          {lines.length === 0 && !loading
            ? "Nothing is being held. Expired stock is taken off the shelf "
              + "automatically each morning and would appear here."
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

      <Refreshable loading={loading} hasData={lines.length > 0}
                   skeleton={<TableSkeleton cols={5} rows={6}
                                            widths={["30ch", "14ch", "10ch", "12ch", "12ch"]} />}>
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Medicine</th>
                <th>Batch</th>
                <th className="num">Units</th>
                <th className="num">Value at cost</th>
                <th>Why, and since</th>
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
                    {l.batch || "—"}
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
    </>
  );
}
