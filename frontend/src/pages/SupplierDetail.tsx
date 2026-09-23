/** A supplier: what has been ordered, what has been billed, what has been paid.
 *
 *  The creditor ageing named six suppliers and none of them led anywhere, so
 *  the obvious next question, what is behind this two thousand dollars, had
 *  no answer short of running three reports.
 */
import { useEffect, useState } from "react";
import { LinkSimple, Printer } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money , sentence} from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useToast } from "../components/Toast";
import { useParams } from "react-router-dom";

interface Order {
  id: number; order_number: string; status: string;
  created_at: string; received_at: string | null; value: number;
  /** What the wholesaler said on their own link. */
  acknowledged_at: string | null;
  promised_date: string | null;
  supplier_note: string;
  lines_short: number;
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
/** One thing the buying record says about this wholesaler, in a sentence
 *  somebody can disagree with. See services/supplier_record for why these
 *  are separate findings and not a score out of five. */
interface Finding { tone: string; says: string }

interface Quoting {
  asked: number; answered: number; declined: number; never_answered: number;
  avg_reply_days: number | null; lines_quoted: number; keenest_on: number;
}

interface Behaviour {
  orders: number; orders_received: number;
  units_ordered: number; units_received: number;
  fill_rate: number | null; short_orders: number; lines_supplied: number;
  units_outstanding: number;
  spend: number; recent_spend: number;
  avg_days: number | null; slowest_days: number | null; quickest_days: number | null;
  last_ordered: string | null; last_delivered: string | null;
  delivers: boolean; few_orders: boolean;
  quoting: Quoting; findings: Finding[];
}

interface Data {
  id: number; name: string; contact_person: string; phone: string; email: string;
  owed: number; orders: Order[]; invoices: Invoice[];
  payments: Payment[]; supplies: Supplies[]; record: Behaviour;
}

export default function SupplierDetail() {
  const { id } = useParams();
  const toast = useToast();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [printing, setPrinting] = useState(false);

  /** The statement, as a document rather than a screenshot of a table.
   *
   *  This is the thing a pharmacy puts beside the wholesaler's own statement
   *  once a month, so it has to carry the same furniture: the account it is
   *  for, a brought-forward, a running balance that ties, and the ageing.
   */
  /** Mint their standing link and put a message around it on the clipboard.
   *  A pharmacy that has to compose the message itself sends a bare URL with
   *  no explanation, and nobody opens those. */
  const portalLink = async () => {
    try {
      const made = await api.post<{ share_text: string; expires_in_days: number }>(
        `/api/portal-admin/links/supplier/${id}`);
      await navigator.clipboard.writeText(made.share_text);
      toast.ok(`${d?.name ?? "Their"} order link is on the clipboard, with a `
        + `message around it. It lasts ${made.expires_in_days} days and shows `
        + "them their own orders only.");
    } catch (e) {
      toast.error(errorText(e, "That link could not be made."));
    }
  };

  const printStatement = async () => {
    setPrinting(true);
    try {
      const [head, doc] = await Promise.all([
        letterhead(),
        api.get<any>(`/api/payables/suppliers/${id}/statement`),
      ]);
      printDocument(head, {
        kind: "Statement of account",
        to: [doc.supplier, doc.contact, doc.phone, doc.email].filter(Boolean),
        meta: [
          { label: "Account", value: doc.account_code },
          { label: "Date", value: fmtDate(doc.to) },
          { label: "Period from", value: fmtDate(doc.from) },
          { label: "Amount due", value: money(doc.amount_due), strong: true },
        ],
        columns: [
          { key: "date", label: "Date", width: "22mm" },
          { key: "reference", label: "Reference", width: "30mm" },
          { key: "description", label: "Description" },
          { key: "debit", label: "Debit", numeric: true, width: "24mm" },
          { key: "credit", label: "Credit", numeric: true, width: "24mm" },
          { key: "balance", label: "Balance", numeric: true, width: "26mm" },
        ],
        opening: {
          description: "Balance brought forward",
          balance: money(doc.brought_forward),
        },
        rows: doc.lines.map((l: any) => ({
          date: fmtDate(l.date),
          reference: l.reference,
          description: l.description,
          debit: l.debit == null ? "" : money(l.debit),
          credit: l.credit == null ? "" : money(l.credit),
          balance: money(l.balance),
        })),
        totals: {
          description: "Closing balance",
          debit: money(doc.debits),
          credit: money(doc.credits),
          balance: money(doc.closing),
        },
        ageing: [
          ...doc.ageing.map((a: any) => ({ label: a.label, value: money(a.value) })),
          { label: "Amount due", value: money(doc.amount_due), strong: true },
        ],
        note: head.terms
          || "Please quote the account number shown above on every remittance.",
      });
    } catch (e) {
      toast.error(errorText(e, "That statement could not be produced."));
    } finally {
      setPrinting(false);
    }
  };

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
              { label: "Creditors", to: "/payables" },
              { label: d?.name ?? "This supplier" }]}
      eyebrow="Supplier"
      title={d?.name ?? ""}
      subtitle={d && [d.contact_person, d.phone, d.email].filter(Boolean).join(" · ")}
      loading={!d && !error}
      error={error}
      actions={d && (
        <>
          {/* THE LINK THAT STOPS THE TELEPHONE CALL.
              "When is it coming" is the commonest call a pharmacy makes.
              This lets the wholesaler answer it once, in writing, on their
              own link, and the answer lands beside the order instead of on
              somebody's scrap of paper. */}
          <button className="btn secondary" onClick={portalLink}>
            <LinkSimple size={15} /> Their order link
          </button>
          <button className="btn secondary" onClick={printStatement} disabled={printing}>
            <Printer size={15} /> {printing ? "Preparing…" : "Statement"}
          </button>
        </>
      )}
      facts={d ? [
        { label: "Owed now", value: money(d.owed),
          hint: d.owed > 0 ? "unpaid invoices" : "nothing outstanding" },
        { label: "Orders", value: d.orders.length,
          hint: `${received} received` },
        // THE TWO FIGURES A BUYER RENEWING TERMS ACTUALLY ARGUES FROM.
        //
        // What arrived of what was asked for, and how long it took. Both
        // existed in the orders all along and neither had a screen, so the
        // conversation with a wholesaler was held on what somebody
        // remembered.
        { label: "Arrives",
          value: d.record.fill_rate === null ? "not known"
            : `${Math.round(d.record.fill_rate * 100)}%`,
          hint: d.record.fill_rate === null
            ? (d.record.units_outstanding
                ? `${d.record.units_outstanding} unit(s) still to come`
                : "nothing delivered yet")
            : d.record.short_orders
              ? `${d.record.short_orders} order(s) came up short`
              : "of what was ordered",
          tone: d.record.fill_rate === null ? undefined
            : d.record.delivers ? "ok" : "bad" },
        { label: "Takes",
          value: d.record.avg_days === null ? "not known"
            : `${d.record.avg_days} days`,
          hint: d.record.slowest_days !== null && d.record.quickest_days !== null
            && d.record.slowest_days > d.record.quickest_days
              ? `between ${d.record.quickest_days} and ${d.record.slowest_days}`
              : "from sending the order" },
        { label: "Spent with them", value: money(d.record.spend),
          hint: d.record.recent_spend
            ? `${money(d.record.recent_spend)} in the last 90 days`
            : "nothing in the last 90 days" },
      ] : undefined}
    >
      {d && (
        <>
          {/* Leads the page: a buyer opening a supplier is usually about to
              order from them or about to stop, and both are decided on this
              rather than on the invoice list. */}
          <Panel title="How they behave" count={d.record.findings.length}
                 empty="Nothing has been ordered from them yet, so there is
                        nothing to judge.">
            <ul className="sup-findings">
              {d.record.findings.map((f, i) => (
                <li key={i} className={`sup-finding is-${f.tone}`}>{f.says}</li>
              ))}
            </ul>
            {d.record.quoting.asked > 0 && (
              <div className="sup-quoting">
                <div>
                  <b>{d.record.quoting.answered} of {d.record.quoting.asked}</b>
                  <span className="muted small">Requests answered</span>
                </div>
                <div>
                  <b>{d.record.quoting.keenest_on} of {d.record.quoting.lines_quoted}</b>
                  <span className="muted small">Lines they were cheapest on</span>
                </div>
                <div>
                  <b>
                    {d.record.quoting.avg_reply_days === null
                      ? "not known"
                      : `${d.record.quoting.avg_reply_days} days`}
                  </b>
                  <span className="muted small">To reply on average</span>
                </div>
              </div>
            )}
          </Panel>

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
                    <td>{i.due_date ? fmtDate(i.due_date) : "no date"}</td>
                    <td className="num">{money(i.total)}</td>
                    <td className="num">
                      {i.outstanding > 0.005 ? money(i.outstanding)
                        : <span className="muted">Settled</span>}
                    </td>
                    <td><span className="badge">{sentence(i.status)}</span></td>
                    <td className="mono">
                      <EntityLink kind="order" id={i.order_id}>
                        {i.order_id ? `#${i.order_id}` : "none"}
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
                  <tr>
                    <th>Order</th><th>Status</th>
                    {/* What THEY said, beside what actually happened. Two
                        different facts and worth comparing: a wholesaler
                        who promises Tuesday and delivers Friday every time
                        is a different problem from one who never promises. */}
                    <th>They said</th><th>Received</th>
                    <th className="num">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {d.orders.map((o) => (
                    <tr key={o.id}>
                      <td className="mono">
                        <EntityLink kind="order" id={o.id}>{o.order_number}</EntityLink>
                      </td>
                      <td><span className="badge">{sentence(o.status)}</span></td>
                      <td className="small">
                        {o.acknowledged_at ? (
                          <>
                            {o.promised_date
                              ? <>due {fmtDate(o.promised_date)}</>
                              : "confirmed, no date given"}
                            {o.lines_short > 0 && (
                              <div className="muted small">
                                {o.lines_short} line(s) short
                              </div>
                            )}
                            {o.supplier_note && (
                              <div className="muted small wrap">{o.supplier_note}</div>
                            )}
                          </>
                        ) : o.status === "sent" ? (
                          <span className="muted">Not confirmed yet</span>
                        ) : (
                          <span className="muted">Not asked</span>
                        )}
                      </td>
                      <td>{o.received_at ? fmtDate(o.received_at)
                                         : <span className="muted">Not yet</span>}</td>
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
                      <td className="mono">{p.reference || "none"}</td>
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
