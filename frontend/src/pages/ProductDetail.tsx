import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import Variants from "../components/Variants";
import { api, fmtDate, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Avatar, Highlights } from "../components/record";
import { ProductDetail as Detail, StockBatch, StockMovement } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";

type Tab = "batches" | "movements";

function expiryBadge(expiry: string | null) {
  if (!expiry) return <span className="badge muted">no expiry</span>;
  const days = Math.floor((new Date(expiry).getTime() - Date.now()) / 86400000);
  if (days < 0) return <span className="badge danger">expired</span>;
  if (days < 90) return <span className="badge warn">{days}d left</span>;
  return <span className="badge ok">{fmtDate(expiry)}</span>;
}

export default function ProductDetail() {
  const { id } = useParams();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  const TABS: TabDef<Tab>[] = [
    { key: "batches", label: "Batches on hand", count: data?.batches.length },
    { key: "movements", label: "Movement history", count: data?.movements.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "batches");

  useEffect(() => {
    api.get<Detail>(`/api/products/${id}`).then(setData).catch((e) => setError(e.message));
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
  if (!data) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Stock", to: "/stock" }, { label: "This record" }]}
        eyebrow="Product"
        tabs={["Batches on hand", "Movement history"]}
        cards={1}
      />;
  const p = data.product;

  const batchCols: Column<StockBatch>[] = [
    { key: "batch_number", header: "Batch", sortable: true, render: (b) => <b className="mono">{b.batch_number}</b> },
    { key: "expiry_date", header: "Expiry", sortable: true, render: (b) => expiryBadge(b.expiry_date) },
    { key: "quantity_remaining", header: "Remaining", align: "right", sortable: true,
      total: (b) => b.quantity_remaining },
    { key: "quantity_received", header: "Received", align: "right", sortable: true },
    { key: "unit_cost", header: "Unit cost", align: "right", sortable: true, render: (b) => money(b.unit_cost) },
    { key: "reference", header: "Reference", truncate: 26 },
    { key: "received_at", header: "Booked in", sortable: true,
      value: (b) => b.received_at, render: (b) => <span className="muted">{fmtDate(b.received_at)}</span> },
  ];

  const moveCols: Column<StockMovement>[] = [
    { key: "created_at", header: "When", sortable: true,
      value: (m) => m.created_at, render: (m) => fmtDateTime(m.created_at) },
    { key: "movement_type", header: "Type", sortable: true,
      render: (m) => <span className="badge muted">{m.movement_type}</span> },
    { key: "quantity_delta", header: "Change", align: "right", sortable: true,
      render: (m) => <b className={m.quantity_delta < 0 ? "" : "muted"}>
        {m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta}</b> },
    { key: "balance_after", header: "Balance", align: "right", sortable: true },
    { key: "reference", header: "Reference", truncate: 30 },
    { key: "notes", header: "Notes", truncate: 40 },
  ];

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Stock", to: "/stock" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={p.name} last="" size={44} />
          <div>
            <div className="eyebrow">Product</div>
            <h1>{p.name} {p.strength}</h1>
            <div className="sub">
              {p.dosage_form || "—"} · {p.category}
              {p.schedule > 0 && <> · <span className="badge sched">S{p.schedule}</span></>}
            </div>
          </div>
        </div>
        <Link to="/stock" className="btn secondary"><ArrowLeft size={13} weight="bold" /> Inventory</Link>
      </div>

      <div className="card record-hero">
        <Highlights items={[
          { label: "On hand", value: String(p.quantity_on_hand),
            hint: p.quantity_on_hand <= p.reorder_level ? "at or below reorder level" : `reorder at ${p.reorder_level}` },
          { label: "Stock value", value: money(data.stock_value), hint: `${money(p.cost_price)} cost` },
          { label: "Selling price", value: money(p.unit_price), hint: `VAT ${Math.round(p.vat_rate * 100)}%` },
          { label: "Dispensed", value: String(data.units_dispensed), hint: "units on prescription" },
          { label: "Sold", value: String(data.units_sold), hint: "units over the counter" },
        ]} />
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          <div><dt>NAPPI</dt><dd className="mono">{p.nappi_code || "—"}</dd></div>
          <div><dt>Barcode</dt><dd className="mono">{p.barcode || "—"}</dd></div>
          <div><dt>Pack size</dt><dd>{p.pack_size || "—"}</dd></div>
          <div><dt>Bin</dt><dd>{p.bin_location || "—"}</dd></div>
          <div><dt>Ingredient</dt><dd>{p.active_ingredient || "—"}</dd></div>
          <div><dt>Manufacturer</dt><dd>{p.manufacturer || "—"}</dd></div>
          <div><dt>Reorder quantity</dt><dd>{p.reorder_quantity}</dd></div>
        </dl>
        {/* The rest of the family: other products holding the same molecule. */}
        <Variants productId={p.id} />
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "batches" && (
        <DataTable
          columns={batchCols}
          rows={data.batches}
          rowKey={(b) => b.id}
          totals
          initialSort={{ key: "expiry_date", dir: "asc" }}
          empty="No stock on hand, nothing has been received for this product"
        />
      )}

      {tab === "movements" && (
        <DataTable
          columns={moveCols}
          rows={data.movements}
          rowKey={(m) => m.id}
          initialSort={{ key: "created_at", dir: "desc" }}
          empty="No stock movements recorded"
        />
      )}
    </>
  );
}
