import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Avatar, Highlights } from "../components/record";
import { printReceipt } from "../print";
import { Sale, SaleItem } from "../types";

export default function SaleDetail() {
  const { id } = useParams();
  const [sale, setSale] = useState<Sale | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Sale>(`/api/pos/sales/${id}`).then(setSale).catch((e) => setError(e.message));
  }, [id]);

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
          <button className="secondary" onClick={() => printReceipt(sale, "RX3000 Pharmacy")}>🖨 Reprint</button>
          <Link to="/pos" className="btn secondary">← Front Shop</Link>
        </div>
      </div>

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
                : <span className="badge warn">not captured — cannot be reconciled</span>}</dd></div>
            <div><dt>Acquirer reference</dt><dd className="mono">{sale.card_reference || "—"}</dd></div>
            <div><dt>Card</dt><dd>{sale.card_last4 ? `${sale.card_scheme || "card"} **** ${sale.card_last4}` : "—"}</dd></div>
            <div><dt>Terminal</dt><dd>{sale.terminal_id || "—"}</dd></div>
            <div><dt>Settlement batch</dt><dd>{sale.card_batch || "—"}</dd></div>
          </dl>
        )}

        {sale.claim && (
          <div className={sale.claim.status === "approved" ? "success-banner" : "error-banner"} style={{ marginTop: 14 }}>
            Claim {sale.claim.claim_number}: <b>{sale.claim.status.toUpperCase()}</b> — {sale.claim.response_message}
            {sale.claim.patient_liable > 0 && <> Patient pays <b>{money(sale.claim.patient_liable)}</b>.</>}
          </div>
        )}
      </div>

      <DataTable columns={cols} rows={sale.items} rowKey={(i) => i.id} totals
        empty="This sale has no lines" />
    </>
  );
}
