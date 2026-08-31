import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import Variants from "../components/Variants";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import Select from "../components/Select";
import { useToast } from "../components/Toast";
import DataTable, { Column } from "../components/DataTable";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Avatar, Highlights } from "../components/record";
import { ProductDetail as Detail, StockBatch, StockMovement } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";
import CounsellingPoints from "../components/CounsellingPoints";
import ProductBarcodes from "../components/ProductBarcodes";

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
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  const [filing, setFiling] = useState(false);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "batches", label: "Batches on hand", count: data?.batches.length },
    { key: "movements", label: "Movement history", count: data?.movements.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "batches");

  useEffect(() => {
    api.get<Detail>(`/api/products/${id}`).then(setData).catch((e) => setError(e.message));
  }, [id]);

  // The departments, for the control below. Fetched once rather than per
  // product: they change about as often as the shop is re-laid-out.
  //
  // `{items, untagged}`, not a bare list. It used to be a list; it grew a
  // count of unfiled lines when the departments screen needed one, and this
  // page kept asserting the old shape — `api.get<T>` tells the compiler what
  // came back, it does not ask the server. The whole page threw
  // `.map is not a function` and rendered white. `qa/response-shape.py` now
  // reads every such assertion against what the handler actually returns.
  useEffect(() => {
    api.get<{ items: { id: number; name: string }[] }>("/api/stock-categories")
      .then((d) => setDepartments(d.items ?? []))
      .catch(() => setDepartments([]));
  }, []);

  /** File this product under a department.
   *
   *  `category` on the product is free text for the therapeutic class;
   *  `category_id` is the department the shop is laid out by and that every
   *  stock report groups on. The endpoint to set it has existed since
   *  departments did, and no screen offered it — so a product created outside
   *  the department screen stayed unfiled, and "uncategorised" quietly became
   *  the largest department in the shop.
   */
  async function file(value: string) {
    if (!data) return;
    setFiling(true);
    try {
      await api.post(`/api/products/${data.product.id}/category`,
                     { category_id: value ? Number(value) : null });
      const fresh = await api.get<Detail>(`/api/products/${id}`);
      setData(fresh);
      toast.ok(value
        ? `Filed under ${departments.find((d) => String(d.id) === value)?.name}.`
        : "Removed from its department.");
    } catch (e) {
      toast.error(errorText(e, "That could not be filed."));
    } finally {
      setFiling(false);
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
            {/* The department, where it is set and not merely displayed. An
                unfiled product is the commonest reason a stock report shows a
                large "uncategorised" line nobody can explain. */}
            <div className="pd-department">
              <span className="muted small">Department</span>
              <Select
                value={p.category_id == null ? "" : String(p.category_id)}
                onChange={file}
                disabled={filing}
                ariaLabel="Department"
                options={[{ value: "", label: "Not filed" },
                          ...departments.map((d) => ({
                            value: String(d.id), label: d.name }))]}
              />
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

      {/* Every code that finds this product, and the way to take a wrong one
          off. A code learned against the wrong medicine is silent and, until
          now, permanent. */}
      <ProductBarcodes productId={p.id} />

      {/* What to say when this is handed over.
          The endpoint has written these since it was added and nothing could
          reach it, so the counselling half of dispensing lived entirely in
          whatever the pharmacist happened to remember. Read to the patient,
          not filed: how to take it, what to expect, what would worry you. */}
      {/* The same block the dispensing screen now shows on a selected line,
          so the two cannot drift into saying different things about the same
          medicine. Expanded here, because a product page is opened on purpose
          and has room; folded at the counter, where four of them would bury
          the fields being typed into. */}
      <CounsellingPoints productId={p.id}
        name={`${p.name} ${p.strength ?? ""}`.trim()} />

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
