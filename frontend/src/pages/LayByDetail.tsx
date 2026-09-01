/** One lay-by: what is being held, what has been paid, and what is left.
 *
 *  The lay-by list showed a balance. The thing the person at the counter is
 *  actually holding — a receipt, and a question about their daughter's inhaler
 *  — needs the items and the payment history, and neither was reachable.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import BusyButton from "../components/BusyButton";
import { useAsk, useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { useParams } from "react-router-dom";

interface Item {
  product_id: number; product: string; quantity: number; unit_price: number;
}
interface Payment {
  id?: number; amount: number; paid_at?: string; created_at?: string;
  method?: string; reference?: string;
}
interface Data {
  id: number; layby_number: string; patient_id: number | null; patient: string;
  status: string; total: number; paid: number; balance: number;
  minimum_deposit: number; due_date: string | null; created_at: string | null;
  items: Item[]; payments?: Payment[];
}

export default function LayByDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Data>(`/api/laybys/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That lay-by could not be opened.")));
  }, [id]);
  useEffect(load, [load]);

  const overdue = Boolean(d?.due_date && d.status === "open"
    && d.due_date < new Date().toISOString().slice(0, 10));
  const payments = d?.payments ?? [];

  const toast = useToast();
  const ask = useAsk();
  const confirm = useConfirm();
  /** Take a payment against the lay-by.
   *
   *  A lay-by IS a series of payments — it is the entire reason the record
   *  exists, and this page could show the balance and not move it. The
   *  endpoint has been there since lay-bys were built.
   */
  async function pay() {
    if (!d) return;
    const answer = await ask({
      title: `Take a payment from ${d.patient}`,
      body: (
        <>
          <b>{money(d.balance)}</b> outstanding of {money(d.total)}.
          {d.minimum_deposit > 0 && d.paid < d.minimum_deposit && (
            <> The minimum deposit of {money(d.minimum_deposit)} has not been
              reached yet.</>
          )}
        </>
      ),
      field: "Amount",
      placeholder: d.balance.toFixed(2),
      required: true,
      confirmLabel: "Take it",
    });
    if (!answer.ok) return;
    try {
      await api.post(`/api/laybys/${d.id}/pay`,
                     { amount: Number(answer.value), method: "cash" });
      toast.ok(`${money(Number(answer.value))} taken.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That payment could not be taken."));
    }
  }

  /** Hand the goods over. The server refuses while a balance is owed. */
  async function complete() {
    if (!d) return;
    const ok = await confirm({
      title: `Hand over ${d.layby_number}?`,
      body: `${d.items.length} item(s) leave the shelf and go to ${d.patient}.`,
      confirmLabel: "Hand it over",
    });
    if (!ok) return;
    try {
      await api.post(`/api/laybys/${d.id}/complete`, {});
      toast.ok("Handed over.");
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  /** Cancel it. The goods go back on the shelf and what was paid is owed
   *  back, which is why this asks for a reason rather than just confirming. */
  async function cancel() {
    if (!d) return;
    const answer = await ask({
      title: `Cancel ${d.layby_number}?`,
      body: (
        <>
          The goods go back on the shelf.
          {d.paid > 0 && (
            <> <b>{money(d.paid)}</b> has already been paid and is owed back to
              {" "}{d.patient}.</>
          )}
        </>
      ),
      field: "Why",
      placeholder: "Changed their mind, cannot afford it",
      required: true,
      confirmLabel: "Cancel the lay-by",
      destructive: true,
    });
    if (!answer.ok) return;
    try {
      await api.post(`/api/laybys/${d.id}/cancel`, { reason: answer.value });
      toast.warn("Cancelled. The goods are back on the shelf.");
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }
  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Lay-bys", to: "/laybys" },
              { label: d?.layby_number ?? "This lay-by" }]}
      eyebrow="Lay-by"
      title={d?.layby_number ?? ""}
      subtitle={d && <EntityLink kind="patient" id={d.patient_id}>
        {d.patient || "Walk-in"}</EntityLink>}
      loading={!d && !error}
      error={error}
      actions={d && (
        <div className="page-actions">
          {d.status !== "cancelled" && d.balance > 0.005 && (
            <BusyButton className="btn primary" onClick={pay}
                        busyLabel="Taking…">
              Take a payment
            </BusyButton>
          )}
          {d.status === "active" && d.balance <= 0.005 && (
            <BusyButton className="btn primary" onClick={complete}
                        busyLabel="Handing over…">
              Hand it over
            </BusyButton>
          )}
          {d.status === "active" && (
            <BusyButton className="btn" onClick={cancel} busyLabel="Cancelling…">
              Cancel it
            </BusyButton>
          )}
        </div>
      )}
      facts={d ? [
        { label: "Total", value: money(d.total) },
        { label: "Paid", value: money(d.paid) },
        { label: "Balance", value: money(d.balance) },
        { label: "Due", value: d.due_date ? fmtDate(d.due_date) : "no date set",
          hint: overdue ? "past its date" : undefined },
      ] : undefined}
    >
      {d && (
        <>
          {overdue && (
            <div className="alert warn">
              This lay-by passed its date on {fmtDate(d.due_date!)} and still has{" "}
              <b>{money(d.balance)}</b> outstanding.
            </div>
          )}

          <Panel title="What is being held" count={d.items.length}
                 empty="Nothing is recorded against this lay-by.">
            <table className="dt">
              <thead>
                <tr><th>Item</th><th className="num">Qty</th><th className="num">Unit</th><th className="num">Value</th></tr>
              </thead>
              <tbody>
                {d.items.map((i, n) => (
                  <tr key={`${i.product_id}-${n}`}>
                    <td>
                      <EntityLink kind="product" id={i.product_id}>{i.product}</EntityLink>
                    </td>
                    <td className="num">{i.quantity}</td>
                    <td className="num">{money(i.unit_price)}</td>
                    <td className="num">{money(i.unit_price * i.quantity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Payments" count={payments.length}
                 empty="Nothing has been paid against this lay-by yet.">
            <table className="dt">
              <thead>
                <tr><th>When</th><th>Method</th><th>Reference</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {payments.map((p, n) => (
                  <tr key={p.id ?? n}>
                    <td>{p.paid_at || p.created_at
                      ? fmtDateTime((p.paid_at || p.created_at)!) : "—"}</td>
                    <td>{p.method || "—"}</td>
                    <td className="mono">{p.reference || "—"}</td>
                    <td className="num">{money(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
