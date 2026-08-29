/** The remittance advice: what to send the supplier so they can find the money.
 *
 *  A wholesaler receiving four thousand dollars with no note has to guess which
 *  of your eleven open invoices it was for, and guesses wrong. Then their
 *  statement disagrees with yours, somebody spends an afternoon on it, and the
 *  account gets put on stop over money that was already paid.
 *
 *  The server has built this since the payment endpoint was written. Nothing
 *  had ever shown it.
 */
import { fmtDate, money } from "../api";

export interface RemittanceData {
  payment_id: number; supplier: string; paid_on: string; amount: number;
  method: string; reference: string; allocated: number; on_account: number;
  lines: { invoice_number: string; invoice_date: string; invoice_total: number;
           allocated: number }[];
}

export default function Remittance({ data, onClose }: {
  data: RemittanceData; onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide print-area" onClick={(e) => e.stopPropagation()}>
        <h2>Remittance advice</h2>
        <p className="muted">
          Paid to <b>{data.supplier}</b> on {fmtDate(data.paid_on)}
          {data.reference ? <> · {data.reference}</> : null}
        </p>

        <div className="wc-bands">
          <div className="wl-stat"><b>{money(data.amount)}</b><span>paid</span></div>
          <div className="wl-stat"><b>{money(data.allocated)}</b><span>against invoices</span></div>
          <div className={`wl-stat${data.on_account > 0.005 ? " wc-stale" : ""}`}>
            <b>{money(data.on_account)}</b><span>on account</span>
          </div>
        </div>

        <table className="dt">
          <thead>
            <tr>
              <th>Invoice</th><th>Dated</th>
              <th className="num">Invoice total</th><th className="num">Paid</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((l, i) => (
              <tr key={i}>
                <td className="mono">{l.invoice_number}</td>
                <td>{fmtDate(l.invoice_date)}</td>
                <td className="num">{money(l.invoice_total)}</td>
                <td className="num"><b>{money(l.allocated)}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.lines.length === 0 && (
          <div className="empty">
            Nothing was allocated, so this payment sits on the supplier&rsquo;s
            account in full. Send it anyway — a payment they can see is a
            payment they will not chase.
          </div>
        )}

        <div className="modal-actions no-print">
          <button className="btn ghost" onClick={onClose}>Close</button>
          <button className="btn" onClick={() => window.print()}>Print it</button>
        </div>
      </div>
    </div>
  );
}
