/** A supplier: what has been ordered, what has been billed, what has been paid.
 *
 *  The creditor ageing named six suppliers and none of them led anywhere, so
 *  the obvious next question — what is behind this two thousand dollars — had
 *  no answer short of running three reports.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Order {
  id: number; order_number: string; status: string;
  created_at: string; received_at: string | null; value: number;
}
interface Invoice {
  id: number; invoice_number: string; invoice_date: string; due_date: string | null;
  total: number; outstanding: number; status: string; order_id: number | null;
}
interface Payment {
  id: number; paid_on: string; amount: number; method: string; reference: string;
}
interface Supplies {
  product_id: number; product: string; units_received: number; last_cost: number;
}
interface Data {
  id: number; name: string; contact_person: string; phone: string; email: string;
  owed: number; orders: Order[]; invoices: Invoice[];
  payments: Payment[]; supplies: Supplies[];
}

export default function SupplierDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/suppliers/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That supplier could not be opened.")));
  }, [id]);

  const received = d?.orders.filter((o) => o.status === "received").length ?? 0;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Supplier accounts", to: "/payables" },
              { label: d?.name ?? "This supplier" }]}
      eyebrow="Supplier"
      title={d?.name ?? ""}
      subtitle={d && [d.contact_person, d.phone, d.email].filter(Boolean).join(" · ")}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Owed now", value: money(d.owed),
          hint: d.owed > 0 ? "unpaid invoices" : "nothing outstanding" },
        { label: "Orders", value: d.orders.length,
          hint: `${received} received` },
        { label: "Invoices", value: d.invoices.length },
        { label: "Paid to date",
          value: money(d.payments.reduce((s, p) => s + p.amount, 0)) },
      ] : undefined}
    >
      {d && (
        <>
          <Panel title="Invoices" count={d.invoices.length}
                 empty="Nothing has been billed by this supplier yet.">
            <table className="dt">
              <thead>
                <tr>
                  <th>Invoice</th><th>Dated</th><th>Due</th>
                  <th className="num">Total</th><th className="num">Outstanding</th>
                  <th>Status</th><th>Order</th>
                </tr>
              </thead>
              <tbody>
                {d.invoices.map((i) => (
                  <tr key={i.id}>
                    <td className="mono">
                      <EntityLink kind="invoice" id={i.id}>{i.invoice_number}</EntityLink>
                    </td>
                    <td>{fmtDate(i.invoice_date)}</td>
                    <td>{i.due_date ? fmtDate(i.due_date) : "—"}</td>
                    <td className="num">{money(i.total)}</td>
                    <td className="num">
                      {i.outstanding > 0.005 ? money(i.outstanding)
                        : <span className="muted">settled</span>}
                    </td>
                    <td><span className="badge">{i.status}</span></td>
                    <td className="mono">
                      <EntityLink kind="order" id={i.order_id}>
                        {i.order_id ? `#${i.order_id}` : "—"}
                      </EntityLink>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <div className="grid cols-2">
            <Panel title="Orders" count={d.orders.length}
                   empty="No order has been raised with this supplier.">
              <table className="dt">
                <thead>
                  <tr><th>Order</th><th>Status</th><th>Received</th><th className="num">Value</th></tr>
                </thead>
                <tbody>
                  {d.orders.map((o) => (
                    <tr key={o.id}>
                      <td className="mono">
                        <EntityLink kind="order" id={o.id}>{o.order_number}</EntityLink>
                      </td>
                      <td><span className="badge">{o.status}</span></td>
                      <td>{o.received_at ? fmtDate(o.received_at) : "—"}</td>
                      <td className="num">{money(o.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel title="Payments" count={d.payments.length}
                   empty="Nothing has been paid to this supplier.">
              <table className="dt">
                <thead>
                  <tr><th>Paid</th><th>Method</th><th>Reference</th><th className="num">Amount</th></tr>
                </thead>
                <tbody>
                  {d.payments.map((p) => (
                    <tr key={p.id}>
                      <td>{fmtDate(p.paid_on)}</td>
                      <td>{p.method}</td>
                      <td className="mono">{p.reference || "—"}</td>
                      <td className="num">{money(p.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>

          <Panel title="What they supply" count={d.supplies.length}
                 empty="Nothing has been received from this supplier yet, so there is nothing to list."
                 aside={<span className="muted small">
                   Taken from what has actually been delivered
                 </span>}>
            <table className="dt">
              <thead>
                <tr><th>Medicine</th><th className="num">Units received</th><th className="num">Last cost</th></tr>
              </thead>
              <tbody>
                {d.supplies.map((s) => (
                  <tr key={s.product_id}>
                    <td>
                      <EntityLink kind="product" id={s.product_id}>{s.product}</EntityLink>
                    </td>
                    <td className="num">{s.units_received}</td>
                    <td className="num">{money(s.last_cost)}</td>
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
