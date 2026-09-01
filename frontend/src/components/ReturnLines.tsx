/** Taking part of a sale back.
 *
 *  A customer buys four things and brings one back. It happens at every till
 *  every day, and the system could not do it: void and the fiscal credit note
 *  both take back the whole sale. So the till reversed all four and rang three
 *  up again, which changes the receipt number, reverses the claim, earns the
 *  loyalty points twice, and counts the day's sales wrong in both directions.
 *  In practice it was done on paper, and the stock drifted.
 *
 *  Two steps, because a return moves money and stock at once and both are
 *  awkward to undo. What the preview shows is not a summary — it is the lines,
 *  what comes off, what goes back on the shelf, and what cannot go back at all
 *  with the reason in a sentence.
 *
 *  A scheduled medicine is shown as returnable but never restockable. Once a
 *  controlled item has left the pharmacy it cannot re-enter saleable stock, and
 *  the screen says why rather than silently doing something different from what
 *  the operator expects.
 */
import { useState } from "react";
import { ArrowUUpLeft, Warning } from "@phosphor-icons/react";
import { api, errorText, money } from "../api";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";
import { useToast } from "./Toast";
import { SaleItem } from "../types";

interface PlanLine {
  sale_item_id: number; product_id: number; description: string;
  sold: number; already_returned: number; returning: number;
  value: number; schedule: number; restock: boolean; why_not: string;
}
interface Plan {
  sale_id: number; sale_number: string; sale_total: number;
  lines: PlanLine[]; refund: number; refused: string[];
  is_whole_sale: boolean;
  applied?: boolean; restocked?: number; written_off?: number;
  sale_total_now?: number; message?: string;
}

export default function ReturnLines(
  { saleId, items, onDone, onClose }:
  { saleId: number; items: SaleItem[]; onDone: () => void; onClose: () => void },
) {
  const [qty, setQty] = useState<Record<number, string>>({});
  const [plan, setPlan] = useState<Plan | null>(null);
  const [reason, setReason] = useState("");
  // Off means it comes back and is written off in the same movement — damaged,
  // opened, past its date. Two facts kept apart, so a shop can see how much of
  // what it takes back it cannot resell.
  const [restock, setRestock] = useState(true);
  const toast = useToast();

  const lines = () => Object.entries(qty)
    .map(([id, n]) => ({ sale_item_id: Number(id), quantity: Number(n) || 0 }))
    .filter((l) => l.quantity > 0);

  async function preview() {
    try {
      setPlan(await api.post<Plan>(`/api/pos/sales/${saleId}/return`,
                                   { lines: lines(), apply: false }));
    } catch (e) {
      toast.error(errorText(e, "That could not be worked out."));
    }
  }

  async function apply() {
    try {
      const r = await api.post<Plan>(`/api/pos/sales/${saleId}/return`, {
        lines: lines(), apply: true, reason: reason.trim(), restock,
      });
      setPlan(r);
      toast.ok(r.message || "Returned.");
      onDone();
    } catch (e) {
      // The server refuses a whole-sale return and says to void or credit-note
      // it instead, and refuses a quantity larger than what is left. Shown as
      // written — both are the instruction, not a description of a failure.
      toast.error(errorText(e, "That return could not be recorded."));
    }
  }

  const chosen = lines().length > 0;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <h2>Return part of this sale</h2>
        <p className="muted">
          Say how many of each line are coming back. Everything coming back is a
          reversal of the whole sale and has its own route — void it, or issue a
          credit note if the receipt has been filed.
        </p>

        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Line</th>
                <th className="num">Sold</th>
                <th className="num">Back already</th>
                <th className="num">Returning</th>
                <th className="num">Worth</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const back = it.quantity_returned ?? 0;
                const left = it.quantity - back;
                const each = it.quantity ? it.line_total / it.quantity : 0;
                const n = Number(qty[it.id] ?? 0);
                return (
                  <tr key={it.id} className={left <= 0 ? "row-muted" : undefined}>
                    <td>
                      {it.description}
                      {left <= 0 && (
                        <div className="muted small">all of it has come back</div>
                      )}
                    </td>
                    <td className="num">{it.quantity}</td>
                    <td className="num">
                      {back || <span className="muted">—</span>}
                    </td>
                    <td className="num">
                      <input
                        type="number" min={0} max={left} value={qty[it.id] ?? ""}
                        disabled={left <= 0}
                        style={{ width: "5rem" }}
                        onChange={(e) => setQty((q) => ({
                          ...q, [it.id]: e.target.value }))}
                        placeholder="0"
                      />
                    </td>
                    <td className="num mono">
                      {n > 0 ? money(each * n) : <span className="muted">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {plan && (
          <>
            {plan.refused.length > 0 && (
              <p className="alert warn">
                <Warning size={16} weight="fill" />
                <span>{plan.refused.join(" ")}</span>
              </p>
            )}

            {plan.is_whole_sale && (
              <p className="alert warn">
                <Warning size={16} weight="fill" />
                <span>
                  Every line is coming back, so this is a reversal of the whole
                  sale rather than a return. Close this and use Reverse — it
                  keeps the claim and the loyalty points right, which a
                  line-by-line return does not.
                </span>
              </p>
            )}

            {plan.lines.some((l) => !l.restock) && (
              <p className="alert bad">
                <Warning size={16} weight="fill" />
                <span>
                  {plan.lines.filter((l) => !l.restock)
                    .map((l) => l.why_not).join(" ")}
                </span>
              </p>
            )}

            {!plan.applied && plan.lines.length > 0 && (
              <div className="wc-bands" style={{ marginTop: 12 }}>
                <div className="wl-stat">
                  <b>{money(plan.refund)}</b><span>comes off the sale</span>
                </div>
                <div className="wl-stat">
                  <b>{money(plan.sale_total - plan.refund)}</b>
                  <span>the sale becomes</span>
                </div>
                <div className="wl-stat">
                  <b>{plan.lines.filter((l) => l.restock).length}</b>
                  <span>line(s) back on the shelf</span>
                </div>
              </div>
            )}

            {plan.applied && (
              <p className="alert ok"><span>{plan.message}</span></p>
            )}
          </>
        )}

        {!plan?.applied && (
          <>
            <label className="field">
              <span>Why <span className="muted">optional</span></span>
              <input value={reason} maxLength={200}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Wrong size, damaged, rung up twice" />
            </label>
            <Checkbox checked={restock} onChange={setRestock}>
              Put it back on the shelf.{" "}
              <span className="muted">
                Off if it cannot be sold again — it is still recorded as
                returned, and written off in the same movement, so the shop can
                see how much of what it takes back it loses.
              </span>
            </Checkbox>
          </>
        )}

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>
            {plan?.applied ? "Close" : "Cancel"}
          </button>
          {!plan?.applied && (
            plan
              ? <BusyButton className="btn primary" onClick={apply}
                  disabled={!plan.lines.length || plan.is_whole_sale}
                  icon={ArrowUUpLeft} busyLabel="Recording…">
                  Return {money(plan.refund)}
                </BusyButton>
              : <BusyButton className="btn primary" onClick={preview}
                  disabled={!chosen} busyLabel="Working it out…">
                  Show what this does
                </BusyButton>
          )}
        </div>
      </div>
    </div>
  );
}
