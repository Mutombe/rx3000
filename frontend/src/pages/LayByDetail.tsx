/** One lay-by: what is being held, what has been paid, and what is left.
 *
 *  The lay-by list showed a balance. The thing the person at the counter is
 *  actually holding — a receipt, and a question about their daughter's inhaler
 *  — needs the items and the payment history, and neither was reachable.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
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

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/laybys/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That lay-by could not be opened.")));
  }, [id]);

  const overdue = Boolean(d?.due_date && d.status === "open"
    && d.due_date < new Date().toISOString().slice(0, 10));
  const payments = d?.payments ?? [];

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
