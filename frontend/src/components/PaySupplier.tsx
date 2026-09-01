/** Pay a wholesaler, and say which invoices the money settled.
 *
 *  The whole creditor side existed except this. Goods were received, the
 *  invoice was matched line by line and approved, it aged into a bucket and
 *  turned red, and there was no way to pay it. Trade creditors could only
 *  ever grow, and the pharmacy's real position lived in somebody's bank app.
 *
 *  Allocation is the part worth building carefully. A payment nobody splits
 *  across invoices reduces the balance and leaves every invoice looking
 *  unpaid, so the ageing stays wrong and the next call from the wholesaler is
 *  an argument. Oldest-first is offered as one press because that is what
 *  almost everybody means, and it stays editable because sometimes it is not:
 *  a queried invoice gets skipped and the one behind it gets paid.
 *
 *  Paying on account is allowed on purpose. A pharmacy that sends a round two
 *  thousand and works out the split on Friday is doing something ordinary, and
 *  refusing to record it until the split is known is how payments end up
 *  existing only on the bank statement.
 */
import { useMemo, useState } from "react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { ZIM_BANKS } from "./Tenders";
import { WALLETS, walletForNumber } from "./MobileMoney";
import { useToast } from "./Toast";

export interface PayableInvoice {
  invoice_id: number; invoice_number: string; invoice_date: string;
  due_date: string; outstanding: number; days_overdue: number; status: string;
}

const METHODS = [
  { value: "bank", label: "Bank transfer" },
  { value: "cheque", label: "Cheque" },
  { value: "mobile_money", label: "Mobile money" },
  { value: "cash", label: "Cash" },
];

export default function PaySupplier({
  supplierId, supplier, invoices, owed, onClose, onPaid,
}: {
  supplierId: number;
  supplier: string;
  /** This supplier's open invoices, oldest first. */
  invoices: PayableInvoice[];
  owed: number;
  onClose: () => void;
  onPaid: (remittance: any) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [paidOn, setPaidOn] = useState(today);
  const [method, setMethod] = useState("bank");
  const [bank, setBank] = useState("");
  const [wallet, setWallet] = useState("");
  const [phone, setPhone] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [amount, setAmount] = useState("");
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const toast = useToast();

  const paying = Math.round((Number(amount) || 0) * 100) / 100;
  const allocated = useMemo(
    () => Math.round(Object.values(alloc)
      .reduce((n, v) => n + (Number(v) || 0), 0) * 100) / 100,
    [alloc]);
  const onAccount = Math.round((paying - allocated) * 100) / 100;
  const overAllocated = allocated - paying > 0.005;

  /** Oldest first, which is what almost everybody means by paying a supplier. */
  function spread() {
    let left = paying;
    const next: Record<number, string> = {};
    for (const i of invoices) {
      if (left <= 0.005) break;
      // A queried invoice is one somebody has an argument about. Paying it by
      // default settles that argument in the supplier's favour without asking.
      if (i.status === "queried") continue;
      const take = Math.min(left, i.outstanding);
      next[i.invoice_id] = take.toFixed(2);
      left = Math.round((left - take) * 100) / 100;
    }
    setAlloc(next);
  }

  const suggested = method === "mobile_money" ? walletForNumber(phone) : null;
  const needsBank = method === "bank" || method === "cheque";
  // Money that cannot be found on a statement later is money somebody has to
  // go looking for. Blocked here rather than discovered at the year end.
  const incomplete =
    (needsBank && !bank) || (method === "mobile_money" && !wallet);

  async function pay() {
    try {
      const instrument = method === "mobile_money"
        ? [WALLETS.find((w) => w.id === wallet)?.name, phone]
        : [bank, method === "cheque" ? "cheque" : ""];
      const r = await api.post<any>("/api/payables/payments", {
        supplier_id: supplierId,
        amount: paying,
        paid_on: paidOn,
        // The ledger only needs to tell cash from bank; everything else that
        // says where the money actually went rides on the reference.
        method: method === "cash" ? "cash" : "bank",
        reference: [...instrument, reference].filter(Boolean).join(" "),
        notes,
        allocations: Object.entries(alloc)
          .map(([id, v]) => ({ invoice_id: Number(id), amount: Number(v) || 0 }))
          .filter((a) => a.amount > 0),
      });
      toast.ok(
        onAccount > 0.005
          ? `${money(paying)} paid — ${money(onAccount)} of it sits on account.`
          : `${money(paying)} paid to ${supplier}.`);
      onPaid(r.remittance);
    } catch (e) {
      toast.error(errorText(e, "That payment could not be recorded."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <h2>Pay {supplier}</h2>
        <p className="muted">
          {money(owed)} is owed across {invoices.length}{" "}
          invoice{invoices.length === 1 ? "" : "s"}.
        </p>

        <div className="form-row">
          <div className="field">
            <label>Amount</label>
            <input type="number" min="0" step="0.01" autoFocus
                   value={amount} onChange={(e) => setAmount(e.target.value)}
                   placeholder="0.00" />
          </div>
          <div className="field">
            <label>Paid on</label>
            <input type="date" value={paidOn}
                   onChange={(e) => setPaidOn(e.target.value)} />
          </div>
          <div className="field">
            <label>How</label>
            <Select value={method}
                    onChange={(v) => { setMethod(v); setBank(""); setWallet(""); }}
                    options={METHODS} />
          </div>
        </div>

        <div className="form-row">
          {needsBank && (
            <div className="field">
              <label>From which bank</label>
              <Select value={bank} onChange={setBank}
                      options={[{ value: "", label: "Which account?" },
                                ...ZIM_BANKS.map((b) => ({ value: b, label: b }))]} />
            </div>
          )}
          {method === "mobile_money" && (
            <>
              <div className="field">
                <label>Which wallet</label>
                <Select value={wallet} onChange={setWallet}
                        options={[{ value: "", label: "Which wallet?" },
                                  ...WALLETS.map((w) => ({ value: w.id, label: w.name,
                                                           hint: w.network }))]} />
              </div>
              <div className="field">
                <label>Paid from</label>
                <input value={phone} onChange={(e) => setPhone(e.target.value)}
                       placeholder="07…" />
                {suggested && suggested.id !== wallet && (
                  <span className="field-hint">
                    That number looks like {suggested.name}.
                  </span>
                )}
              </div>
            </>
          )}
          <div className="field">
            <label>{method === "cheque" ? "Cheque number" : "Reference"}</label>
            <input value={reference} onChange={(e) => setReference(e.target.value)}
                   placeholder="what appears on the statement" />
            <span className="field-hint">
              The supplier quotes this back when they cannot find the money.
            </span>
          </div>
        </div>

        {incomplete && (
          <div className="alert warn">
            {needsBank
              ? "Say which bank it left. A payment naming no account cannot be found on any statement, and the statement is the only thing that catches a payment made twice."
              : "Say which wallet. EcoCash, Omari and InnBucks settle separately and on their own timetables."}
          </div>
        )}

        <div className="card-head" style={{ marginTop: 14 }}>
          <h3>What it settles</h3>
          <button className="btn ghost small" disabled={paying <= 0} onClick={spread}>
            Allocate oldest first
          </button>
        </div>
        <table className="dt">
          <thead>
            <tr>
              <th>Invoice</th><th>Due</th>
              <th className="num">Outstanding</th><th className="num">Paying</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((i) => (
              <tr key={i.invoice_id}>
                <td className="mono">
                  {i.invoice_number}
                  {i.status === "queried" && (
                    <div className="muted small">queried — left out of oldest-first</div>
                  )}
                </td>
                <td>
                  {fmtDate(i.due_date)}
                  {i.days_overdue > 0 && (
                    <div className="muted small">{i.days_overdue} days late</div>
                  )}
                </td>
                <td className="num">{money(i.outstanding)}</td>
                <td className="num">
                  <input type="number" min="0" step="0.01" className="tender-amount"
                         value={alloc[i.invoice_id] ?? ""}
                         onChange={(e) => setAlloc({ ...alloc, [i.invoice_id]: e.target.value })}
                         placeholder="0.00" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {invoices.length === 0 && (
          <div className="empty">
            No invoice is recorded against this supplier. The payment can still
            be made — it will sit on account until an invoice arrives to put it
            against.
          </div>
        )}

        {overAllocated ? (
          <div className="alert error">
            The allocations come to <b>{money(allocated)}</b>, which is more than
            the {money(paying)} being paid.
          </div>
        ) : paying > 0.005 && (
          <div className={`alert ${onAccount > 0.005 ? "warn" : "ok"}`}>
            {onAccount > 0.005
              ? <>{money(allocated)} settles invoices; <b>{money(onAccount)}</b> sits
                  on account until somebody says what it was for.</>
              : <>Every dollar of this is allocated.</>}
          </div>
        )}

        <div className="field">
          <label>Note (optional)</label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)}
                 placeholder="e.g. balance of the March statement" />
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton disabled={paying <= 0.005 || overAllocated || incomplete}
                      onClick={pay}>
            Pay {paying > 0 ? money(paying) : ""}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
