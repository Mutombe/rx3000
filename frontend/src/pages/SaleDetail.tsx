import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, errorText, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Avatar, Highlights } from "../components/record";
import { printReceipt } from "../print";
import { Sale, SaleItem } from "../types";
import { usePharmacy } from "../hooks/usePharmacy";
import { ArrowLeft, ArrowUUpLeft, Receipt, UserCircle } from "@phosphor-icons/react";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";

/** What the tax authority holds against this sale. */
interface FiscalReceipt {
  id: number; receipt_type: string; global_counter: number; status: string;
  verification_url: string; reverses_receipt_id: number | null; total: number;
}

export default function SaleDetail() {
  const pharmacy = usePharmacy();
  const { id } = useParams();
  const [sale, setSale] = useState<Sale | null>(null);
  const [error, setError] = useState("");
  const [receipts, setReceipts] = useState<FiscalReceipt[]>([]);
  const { guarded, prompt } = useStepUp();
  const confirm = useConfirm();
  const toast = useToast();

  function load() {
    api.get<Sale>(`/api/pos/sales/${id}`).then(setSale).catch((e) => setError(e.message));
    // Whether this sale was filed decides how it can be reversed, so it is
    // read before anybody presses anything rather than discovered from a 400.
    api.get<FiscalReceipt[]>(`/api/fiscal/receipts?sale_id=${id}`)
      .then(setReceipts).catch(() => setReceipts([]));
  }
  useEffect(load, [id]);

  const filed = receipts.find((r) => r.receipt_type !== "credit_note");
  const creditNote = receipts.find((r) => r.receipt_type === "credit_note");
  const reversed = sale?.status === "void" || sale?.status === "credited";

  /** Undo a sale the right way round.
   *
   *  Two different operations, and which one is legal is not the cashier's
   *  judgement to make. A receipt already filed with ZIMRA can never be
   *  withdrawn — the record stands and a credit note is filed against it. One
   *  that was never filed is simply voided. The server enforces this; until
   *  now it enforced it by returning a 400 telling the caller to POST to a
   *  URL, which is a sentence written for somebody with curl.
   */
  async function reverse() {
    if (!sale) return;
    const ok = await confirm({
      title: filed ? "File a credit note?" : "Void this sale?",
      body: filed
        ? <>Fiscal receipt <b>{filed.global_counter}</b> has been filed with
            ZIMRA and cannot be withdrawn. A credit note will be filed against
            it, the stock returned to the batches it came from, and any claim
            reversed. Both documents stay on the record.</>
        : <>This sale was never filed with ZIMRA, so it can be voided outright.
            The stock returns to the batches it came from and any claim is
            reversed.</>,
      confirmLabel: filed ? "File the credit note" : "Void it",
      destructive: true,
    });
    if (!ok) return;
    try {
      const result = await guarded(
        "sale.void",
        (token) => filed
          ? api.post<any>(`/api/fiscal/credit-note/${sale.id}`, {}, token)
          : api.post<any>(`/api/pos/sales/${sale.id}/void`, {}, token),
        `${filed ? "Credit note against" : "Void"} ${sale.sale_number}`,
      );
      if (result === CANCELLED) return;
      toast.ok(filed
        ? "Credit note filed. The original receipt still stands."
        : `${sale.sale_number} voided and the stock returned.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That sale could not be reversed."));
    }
  }

  /** Move an unpaid sale onto the customer's account.
   *
   *  The third thing that can happen to a sale awaiting payment, after being
   *  paid and being voided: the goods have gone, the customer is not paying
   *  today, and the debt should move from "money expected at the door" to
   *  "money owed on an account" — where it can be aged, chased and provided
   *  against. The endpoint has been there since the till was written and no
   *  screen offered it, so in practice a pharmacy either voided a sale that had
   *  actually gone out, or left it pending forever.
   */
  async function toAccount() {
    // Captured, because the narrowing above does not survive into the JSX
    // closure below — TypeScript will not carry it across a callback.
    const it = sale;
    if (!it) return;
    const ok = await confirm({
      title: "Put this sale on the customer's account?",
      body: (
        <>
          <b>{money(it.total)}</b> moves off the till and onto{" "}
          {it.patient
            ? <b>{it.patient.first_name} {it.patient.last_name}</b>
            : "the customer"}'s account, where it will age with everything else
          they owe. The goods stay gone — this is not a reversal.
        </>
      ),
      confirmLabel: "Put it on account",
    });
    if (!ok) return;
    try {
      const r = await api.post<{ message?: string }>(
        `/api/pos/sales/${it.id}/transfer-to-account`, {});
      toast.ok(r.message || "On account, and ageing from today.");
      load();
    } catch (e) {
      // The server refuses a sale that is not pending and one with no customer
      // attached, and says which. Shown as written: "attach the customer first"
      // is the instruction, and rewording it here would lose it.
      toast.error(errorText(e, "That sale could not be transferred."));
    }
  }

  if (error)
    return (
      <div className="page">
        {/* A page that could not load says so in place. A toast over a
            blank screen tells nobody what they were looking at. */}
        <div className="alert error">{error}</div>
        <p className="muted pad">
          Nothing was loaded for this record. Check the connection and try again.
        </p>
      </div>
    );
  if (!sale) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Point of sale", to: "/pos" }, { label: "This record" }]}
        eyebrow="Sale"
        cards={1}
        table={4}
      />;

  const cols: Column<SaleItem>[] = [
    { key: "description", header: "Item", sortable: true,
      render: (i) => <EntityLink to={`/products/${i.product_id}`}>{i.description}</EntityLink> },
    { key: "quantity", header: "Qty", align: "right", sortable: true, total: (i) => i.quantity },
    { key: "unit_price", header: "Unit", align: "right", sortable: true, render: (i) => money(i.unit_price) },
    { key: "vat_rate", header: "VAT", align: "right", render: (i) => `${Math.round(i.vat_rate * 100)}%` },
    { key: "line_total", header: "Line total", align: "right", sortable: true,
      render: (i) => <b>{money(i.line_total)}</b>,
      total: (i) => i.line_total, totalRender: (n) => money(n) },
  ];

  const tender = sale.payment_method.replace("_", " ");

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Point of sale", to: "/pos" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={sale.sale_number} last="" size={44} />
          <div>
            <div className="eyebrow">Sale</div>
            <h1 className="mono">{sale.sale_number}</h1>
            <div className="sub">
              {fmtDateTime(sale.created_at)} · {tender}
              {sale.patient && <> · <EntityLink to={`/patients/${sale.patient_id}`}>
                {sale.patient.first_name} {sale.patient.last_name}</EntityLink></>}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button className="secondary" onClick={() => printReceipt(sale, pharmacy.name, pharmacy.regNo)}>🖨 Reprint</button>
          {sale.status === "pending" && !sale.transferred_at && (
            <button className="btn secondary" onClick={toAccount}>
              <UserCircle size={14} weight="bold" /> Put on account
            </button>
          )}
          {!reversed && (
            <button className="btn danger" onClick={reverse}>
              <ArrowUUpLeft size={13} weight="bold" />
              {filed ? " Credit note" : " Void this sale"}
            </button>
          )}
          <Link to="/pos" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Front Shop</Link>
        </div>
      </div>

      {sale.transferred_at && (
        // A transferred sale is still `pending`, because it is still unpaid.
        // Without this the record shows the same amber badge as a COD nobody
        // has chased, and the two need different action.
        <div className="alert ok">
          <UserCircle size={16} weight="fill" />
          <span>
            On {sale.patient
              ? `${sale.patient.first_name} ${sale.patient.last_name}'s`
              : "the customer's"} account since {fmtDateTime(sale.transferred_at)}.
            It ages with everything else they owe rather than sitting on the
            till as an unpaid sale.
          </span>
        </div>
      )}

      <div className="card record-hero">
        <Highlights items={[
          { label: "Total", value: money(sale.total), hint: `incl. VAT ${money(sale.vat_amount)}` },
          { label: "Tendered", value: money(sale.amount_tendered),
            hint: sale.change_due ? `change ${money(sale.change_due)}` : tender },
          { label: "Status", value: sale.status,
            hint: <span className={`badge ${sale.status === "paid" ? "ok" : sale.status === "void" ? "danger" : "warn"}`}>
              {sale.status}</span> },
          { label: "Loyalty", value: `${sale.loyalty_points_earned} pts`,
            hint: sale.loyalty_points_redeemed ? `${sale.loyalty_points_redeemed} redeemed` : "earned on this sale" },
        ]} />

        {sale.payment_method === "card" && (
          <dl className="detail-fields" style={{ marginTop: 14 }}>
            <div><dt>Auth code</dt>
              <dd>{sale.card_auth_code
                ? <span className="mono">{sale.card_auth_code}</span>
                : <span className="badge warn">not captured, cannot be reconciled</span>}</dd></div>
            <div><dt>Acquirer reference</dt><dd className="mono">{sale.card_reference || "—"}</dd></div>
            <div><dt>Card</dt><dd>{sale.card_last4 ? `${sale.card_scheme || "card"} **** ${sale.card_last4}` : "—"}</dd></div>
            <div><dt>Terminal</dt><dd>{sale.terminal_id || "—"}</dd></div>
            <div><dt>Settlement batch</dt><dd>{sale.card_batch || "—"}</dd></div>
          </dl>
        )}

        {sale.claim && (
          <div className={sale.claim.status === "approved" ? "success-banner" : "error-banner"} style={{ marginTop: 14 }}>
            Claim {sale.claim.claim_number}: <b>{sale.claim.status.toUpperCase()}</b>. {sale.claim.response_message}
            {sale.claim.patient_liable > 0 && <> Patient pays <b>{money(sale.claim.patient_liable)}</b>.</>}
          </div>
        )}
      </div>

      {/* What the revenue authority holds. Shown on the sale rather than only
          on the fiscal page, because this is where somebody stands when a
          customer is disputing a receipt. */}
      {receipts.length > 0 && (
        <div className="card">
          <h3><Receipt size={15} /> Filed with ZIMRA</h3>
          <table className="dt">
            <tbody>
              {receipts.map((r) => (
                <tr key={r.id}>
                  <td>
                    <b>{r.receipt_type === "credit_note" ? "Credit note" : "Fiscal receipt"}</b>
                    <div className="muted small mono">no. {r.global_counter}</div>
                  </td>
                  <td className="num">{money(r.total)}</td>
                  <td>
                    <span className={`badge ${r.status === "accepted" ? "ok"
                      : r.status === "rejected" ? "danger" : "warn"}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="actions">
                    {r.verification_url && (
                      <a className="btn small secondary" href={r.verification_url}
                         target="_blank" rel="noreferrer">Verify</a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {creditNote && (
            <p className="muted small">
              The original receipt still stands and is still reported. A
              fiscalised sale is credited, never withdrawn — reports have to be
              able to tell those apart.
            </p>
          )}
        </div>
      )}

      {reversed && !creditNote && (
        <div className="alert warn">
          This sale was voided. It was never filed with ZIMRA, so no credit note
          was needed.
        </div>
      )}

      <DataTable columns={cols} rows={sale.items} rowKey={(i) => i.id} totals
        empty="This sale has no lines" />
      {prompt}
    </>
  );
}
