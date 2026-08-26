import { FormEvent, useEffect, useMemo, useState } from "react";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/Confirm";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { applyFilters, emptyFilters, FilterBar, FilterState } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Product, StockBatch, StockMovement, Supplier } from "../types";
import { Paged } from "../components/Pagination";
import { ScanBar, ScanResult } from "../components/Scanner";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import BusyButton from "../components/BusyButton";

type Tab = "products" | "batches" | "movements";

const CATEGORIES = ["medicine", "front_shop", "airtime", "consumable"];

function expiryBadge(expiry: string | null) {
  if (!expiry) return <span className="badge muted">no expiry</span>;
  const days = Math.floor((new Date(expiry).getTime() - Date.now()) / 86400000);
  if (days < 0) return <span className="badge danger">EXPIRED</span>;
  if (days <= 90) return <span className="badge warn">{days}d left</span>;
  return <span className="badge ok">{fmtDate(expiry)}</span>;
}

const EMPTY = {
  name: "", nappi_code: "", barcode: "", category: "medicine", schedule: 0,
  dosage_form: "", strength: "", pack_size: "", unit_price: 0, cost_price: 0,
  vat_rate: 0.15, quantity_on_hand: 0, reorder_level: 10, reorder_quantity: 20,
  supplier_id: "" as string | number,
  // Where it sits on the shelf and who makes it. Both columns existed, both were
  // read by reports and by the stock-take sheet, and neither had a field on this
  // form — so they were NULL on all 545 products.
  bin_location: "", manufacturer: "",
};

export default function Stock() {
  const [products, setProducts] = useState<Product[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [mvMeta, setMvMeta] = useState<Paged<StockMovement> | null>(null);
  const [mvPage, setMvPage] = useState(1);
  const [mvSize, setMvSize] = useState(25);
  const [batches, setBatches] = useState<StockBatch[]>([]);
  const [bMeta, setBMeta] = useState<Paged<StockBatch> | null>(null);
  const [bPage, setBPage] = useState(1);
  const [bSize, setBSize] = useState(25);

  const [lowOnly, setLowOnly] = useState(false);
  const [expiringOnly, setExpiringOnly] = useState(false);
  const TABS: TabDef<Tab>[] = [
    { key: "products", label: "Products", count: products.length },
    { key: "batches", label: "Batches & expiry", count: batches.length },
    { key: "movements", label: "Movement history", count: movements.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "products");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [form, setForm] = useState<any>({ ...EMPTY });
  const [adjusting, setAdjusting] = useState<Product | null>(null);

  /** A scanned pack opens the adjustment it is almost certainly about to need,
   *  with the batch and expiry already read off it where the code carried them.
   *  Scanning to *find* a product and then hunting for its Adjust button would
   *  be scanning in name only. */
  function onScanned(r: ScanResult) {
    if (!r.found || !r.product) return;
    setAdjusting(r.product as unknown as Product);
    setAdjQty(String(r.quantity_multiplier || 1));
    setAdjBatch(r.batch_number || "");
    setAdjExpiry(r.expiry_date || "");
    setAdjNotes("");
  }
  const [adjQty, setAdjQty] = useState("0");
  const [adjType, setAdjType] = useState("receive");
  const [adjNotes, setAdjNotes] = useState("");
  const [adjBatch, setAdjBatch] = useState("");
  const [adjExpiry, setAdjExpiry] = useState("");
  const toast = useToast();
  const confirm = useConfirm();
  const [filters, setFilters] = useState<FilterState>(emptyFilters);
  const [moveFilters, setMoveFilters] = useState<FilterState>(emptyFilters);

  // The catalogue search hits the API (it can match NAPPI codes the client
  // never loaded); category and schedule narrow what came back.
  const q = filters.q;
  const shownProducts = useMemo(() => applyFilters(products, { ...filters, q: "" }, {
    dims: {
      category: (p) => p.category,
      schedule: (p) => String(p.schedule),
    },
  }), [products, filters]);

  const shownMovements = useMemo(() => applyFilters(movements, moveFilters, {
    search: (m) => [m.product?.name, m.reference, m.notes],
    date: (m) => m.created_at,
    dims: { movement_type: (m) => m.movement_type },
  }), [movements, moveFilters]);

  const productCols: Column<Product>[] = [
    { key: "name", header: "Product", sortable: true, value: (p) => p.name,
      render: (p) => (
        <>
          <b>{p.name}</b> {p.strength}
          <div className="muted" style={{ fontSize: 11.5 }}>
            {[p.dosage_form, p.pack_size, p.category.replace(/_/g, " "), p.barcode]
              .filter(Boolean).join(" · ")}
          </div>
        </>
      ) },
    /* Explicit widths from here on. Left to share the table by weight these six
       columns wanted 1054px in a 956px box, so the rightmost one was always
       behind the pinned actions — first "On hand", then "Stock value". A money
       column does not need 136px to show $20.00, and the product name can give
       back what it does not use. Sized so the whole table fits without scrolling
       at 1280px, which is the width of the tills this runs on. */
    { key: "schedule", header: "Sched.", sortable: true, width: 84,
      render: (p) => (p.schedule > 0
        ? <span className={`badge ${p.schedule >= 5 ? "sched" : "muted"}`}>S{p.schedule}</span>
        : <span className="muted">—</span>) },
    /* Barcode folded into the product cell rather than given a column of its
       own. It is a lookup key, not something anyone reads down a list — the
       search box above already matches on it — and as a column it took 130px
       from a table that did not have 130px to spare, pushing "On hand" off the
       screen entirely on a 1280px till. */
    { key: "unit_price", width: 104, header: "Price", align: "right", sortable: true, render: (p) => money(p.unit_price) },
    { key: "cost_price", width: 104, header: "Cost", align: "right", sortable: true, render: (p) => money(p.cost_price) },
    { key: "quantity_on_hand", width: 104, header: "On hand", align: "right", sortable: true,
      render: (p) => (
        <span className={`badge ${p.category === "airtime" ? "muted"
          : p.quantity_on_hand <= p.reorder_level ? "danger" : "ok"}`}>
          {p.quantity_on_hand}
        </span>
      ) },
    { key: "stock_value", width: 128, header: "Stock value", align: "right",
      value: (p) => p.quantity_on_hand * p.cost_price,
      render: (p) => money(p.quantity_on_hand * p.cost_price),
      total: (p) => p.quantity_on_hand * p.cost_price, totalRender: (n) => money(n) },
    { key: "actions", header: "", align: "right",
      render: (p) => (
        <span style={{ whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
          <IconButton action="edit" onClick={() => openEdit(p)} />
          <IconButton action="adjust" onClick={() => setAdjusting(p)} />
        </span>
      ) },
  ];

  const batchCols: Column<StockBatch>[] = [
    { key: "product", header: "Product", sortable: true, value: (b) => b.product?.name ?? "",
      render: (b) => <><b>{b.product?.name}</b> {b.product?.strength}</> },
    { key: "batch_number", header: "Batch", sortable: true,
      render: (b) => <span className="mono">{b.batch_number}</span> },
    { key: "expiry_date", header: "Expiry", sortable: true, render: (b) => expiryBadge(b.expiry_date) },
    { key: "quantity_received", header: "Received", align: "right", sortable: true },
    { key: "quantity_remaining", header: "Remaining", align: "right", sortable: true,
      render: (b) => <b>{b.quantity_remaining}</b>, total: (b) => b.quantity_remaining },
    { key: "unit_cost", header: "Unit cost", align: "right", sortable: true, render: (b) => money(b.unit_cost) },
    { key: "reference", header: "Reference", truncate: 22,
      render: (b) => <span className="mono">{b.reference || "—"}</span> },
    { key: "actions", header: "", align: "right",
      render: (b) => {
        const expired = b.expiry_date && new Date(b.expiry_date).getTime() < Date.now();
        return expired && b.quantity_remaining > 0
          ? <span onClick={(e) => e.stopPropagation()}>
              <BusyButton className="small danger" onClick={() => writeOff(b)}>Write off</BusyButton>
            </span>
          : null;
      } },
  ];

  const movementCols: Column<StockMovement>[] = [
    { key: "created_at", header: "When", sortable: true, value: (m) => m.created_at,
      render: (m) => fmtDateTime(m.created_at) },
    { key: "product", header: "Product", sortable: true, value: (m) => m.product?.name ?? "",
      render: (m) => m.product?.name ?? "—" },
    { key: "movement_type", header: "Type", sortable: true,
      render: (m) => (
        <span className={`badge ${m.movement_type === "sale" ? "warn"
          : m.movement_type === "receive" ? "ok" : "muted"}`}>{m.movement_type}</span>
      ) },
    { key: "quantity_delta", header: "Δ Qty", align: "right", sortable: true,
      render: (m) => (m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta) },
    { key: "balance_after", header: "Balance", align: "right", sortable: true },
    { key: "reference", header: "Reference", truncate: 34,
      render: (m) => <span className="mono">{m.reference}{m.notes && <span className="muted">, {m.notes}</span>}</span> },
  ];

  function load() {
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(q)}${lowOnly ? "&low_stock=true" : ""}`).then(setProducts).catch((e) => toast.error(errorText(e)));
  }

  useEffect(load, [q, lowOnly]);
  useEffect(() => { api.get<Supplier[]>("/api/suppliers").then(setSuppliers); }, []);
  useEffect(() => {
    if (tab === "movements")
      api
        .get<Paged<StockMovement>>(`/api/stock/movements/paged?page=${mvPage}&per_page=${mvSize}`)
        .then((r) => {
          setMovements(r.items);
          setMvMeta(r);
          if (r.page !== mvPage) setMvPage(r.page);
        })
        .catch((e) => toast.error(errorText(e)));
    if (tab === "batches") loadBatches();
  }, [tab, expiringOnly, mvPage, mvSize, bPage, bSize]);
  useEffect(() => setBPage(1), [expiringOnly]);

  function loadBatches() {
    const params = new URLSearchParams({ page: String(bPage), per_page: String(bSize) });
    if (expiringOnly) params.set("expiring_within_days", "90");
    api
      .get<Paged<StockBatch>>(`/api/stock/batches/paged?${params}`)
      .then((r) => {
        setBatches(r.items);
        setBMeta(r);
        if (r.page !== bPage) setBPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)));
  }

  async function writeOff(b: StockBatch) {
    const ok = await confirm({
      title: "Write off this batch?",
      body: (
        <>
          <b>{b.quantity_remaining} unit(s)</b> of {b.product?.name} in batch{" "}
          {b.batch_number} will be removed from stock. This cannot be undone, and
          the movement is recorded against your name.
        </>
      ),
      confirmLabel: "Write off",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.post(`/api/stock/batches/${b.id}/write-off`);
      loadBatches();
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  function openNew() { setEditing(null); setForm({ ...EMPTY }); setShowForm(true); }
  function openEdit(p: Product) {
    setEditing(p);
    setForm({ ...p, supplier_id: p.supplier_id ?? "" });
    setShowForm(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { ...form, supplier_id: form.supplier_id === "" ? null : Number(form.supplier_id) };
    delete body.id; delete body.active; delete body.medical_aid;
    try {
      if (editing) {
        delete body.quantity_on_hand;
        await api.put(`/api/products/${editing.id}`, body);
      } else {
        await api.post("/api/products", body);
      }
      setShowForm(false);
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  async function applyAdjust(e: FormEvent) {
    e.preventDefault();
    if (!adjusting) return;
    const delta = Number(adjQty);
    const receiving = adjType === "receive" || adjType === "return" || delta > 0;
    try {
      await api.post("/api/stock/adjust", {
        product_id: adjusting.id,
        quantity_delta: adjType === "receive" || adjType === "return" ? Math.abs(delta) : delta,
        movement_type: adjType,
        notes: adjNotes,
        batch_number: receiving ? adjBatch : "",
        expiry_date: receiving && adjExpiry ? adjExpiry : null,
      });
      setAdjusting(null); setAdjQty("0"); setAdjNotes(""); setAdjBatch(""); setAdjExpiry("");
      load();
    } catch (err: any) { toast.error(errorText(err)); }
  }

  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inventory</h1>
          <div className="sub">Products, quantities, movements and reorder levels</div>
        </div>
        <button onClick={openNew}>+ New Product</button>
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "batches" && (
        <DataTable
          columns={batchCols}
          rows={batches}
          rowKey={(b) => b.id}
          rowHref={(b) => (b.product ? `/products/${b.product.id}` : "")}
          totals
          initialSort={{ key: "expiry_date", dir: "asc" }}
          empty={`No batches on hand${expiringOnly ? " expiring within 90 days" : ""}`}
          server={
            bMeta
              ? { ...bMeta, onPage: setBPage, onPerPage: (n: number) => { setBSize(n); setBPage(1); } }
              : undefined
          }
          toolbar={
            <Checkbox checked={expiringOnly} onChange={setExpiringOnly}>Expiring within 90 days only</Checkbox>
          }
        />
      )}

      {tab === "products" && (
        <div style={{ marginBottom: "var(--s3)" }}>
          <ScanBar
            context="stock"
            onResolved={onScanned}
            placeholder="Scan a pack to adjust it, or type a code…"
            enabled={!adjusting}
          />
        </div>
      )}

      {tab === "products" && (
        <DataTable
          columns={productCols}
          rows={shownProducts}
          rowKey={(p) => p.id}
          rowHref={(p) => `/products/${p.id}`}
          totals
          empty="No products match these filters"
          toolbar={
            <>
              <FilterBar
                value={filters}
                onChange={setFilters}
                placeholder="Search name / NAPPI / barcode…"
                dimensions={[
                  // Titled, not the raw column value. `front_shop` became
                  // "front shop" in the filter while the form beside it offered
                  // "Front shop" — the same choice spelled two ways on one page.
                  { key: "category", label: "Category",
                    options: CATEGORIES.map((c) => [
                      c,
                      c.replace(/_/g, " ").replace(/^./, (ch) => ch.toUpperCase()),
                    ] as [string, string]) },
                  { key: "schedule", label: "Schedule",
                    options: [0, 1, 2, 3, 4, 5, 6].map((n) => [String(n), `S${n}`] as [string, string]) },
                ]}
              />
              <Checkbox checked={lowOnly} onChange={setLowOnly}>Low stock only</Checkbox>
            </>
          }
        />
      )}

      {tab === "movements" && (
        <DataTable
          columns={movementCols}
          rows={shownMovements}
          rowKey={(m) => m.id}
          rowHref={(m) => (m.product ? `/products/${m.product.id}` : "")}
          initialSort={{ key: "created_at", dir: "desc" }}
          empty="No stock movements recorded"
          server={
            mvMeta
              ? {
                  ...mvMeta,
                  onPage: setMvPage,
                  onPerPage: (n) => { setMvSize(n); setMvPage(1); },
                }
              : undefined
          }
          toolbar={
            <FilterBar
              value={moveFilters}
              onChange={setMoveFilters}
              placeholder="Search product or reference…"
              showDates
              dimensions={[{
                key: "movement_type", label: "Type",
                options: [["receive", "Receive"], ["sale", "Sale"], ["dispense", "Dispense"],
                          ["adjustment", "Adjustment"], ["return", "Return"], ["write_off", "Write-off"]],
              }]}
            />
          }
        />
      )}

      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing ? "Edit Product" : "New Product"}</h2>
            <form onSubmit={save}>
              <div className="field"><label>Name</label><input required value={form.name} onChange={set("name")} /></div>
              <div className="form-row">
                <div className="field"><label>Strength</label><input value={form.strength} onChange={set("strength")} /></div>
                <div className="field"><label>Dosage form</label><input value={form.dosage_form} onChange={set("dosage_form")} /></div>
                <div className="field"><label>Pack size</label><input value={form.pack_size} onChange={set("pack_size")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Category</label>
                  <Select
                    value={form.category}
                    onChange={(v) => set("category")({ target: { value: v } } as any)}
                    options={[
                      { value: "medicine", label: "Medicine" },
                      { value: "front_shop", label: "Front shop" },
                      { value: "airtime", label: "Airtime" },
                    ]}
                  />
                </div>
                <div className="field">
                  <label>Schedule</label>
                  <Select
                    value={String(form.schedule)}
                    onChange={(v) => setForm({ ...form, schedule: Number(v) })}
                    options={[0, 1, 2, 3, 4, 5, 6].map((n) => ({
                      value: String(n),
                      label: `S${n}`,
                      // The register requirement belongs beside the schedule, not
                      // in the head of whoever is filling the form in.
                      hint: n >= 5 ? "controlled, register entry required" : undefined,
                    }))}
                  />
                </div>
                <div className="field">
                  <label>Supplier</label>
                  <Select
                    value={String(form.supplier_id ?? "")}
                    onChange={(v) => set("supplier_id")({ target: { value: v } } as any)}
                    placeholder="None"
                    clearable
                    searchable
                    options={suppliers.map((sup) => ({ value: String(sup.id), label: sup.name }))}
                  />
                </div>
              </div>
              <div className="form-row">
                <div className="field"><label>NAPPI code</label><input value={form.nappi_code} onChange={set("nappi_code")} /></div>
                <div className="field"><label>Barcode</label><input value={form.barcode} onChange={set("barcode")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Bin location</label>
                  <input value={form.bin_location} onChange={set("bin_location")} placeholder="e.g. A3-04" />
                </div>
                <div className="field">
                  <label>Manufacturer</label>
                  <input value={form.manufacturer} onChange={set("manufacturer")} />
                </div>
              </div>
              <div className="form-row">
                <div className="field"><label>Selling price (incl. VAT)</label><input type="number" step="0.01" value={form.unit_price} onChange={set("unit_price")} /></div>
                <div className="field"><label>Cost price</label><input type="number" step="0.01" value={form.cost_price} onChange={set("cost_price")} /></div>
              </div>
              <div className="form-row">
                {!editing && <div className="field"><label>Opening stock</label><input type="number" value={form.quantity_on_hand} onChange={set("quantity_on_hand")} /></div>}
                <div className="field"><label>Reorder level</label><input type="number" value={form.reorder_level} onChange={set("reorder_level")} /></div>
                <div className="field"><label>Reorder qty</label><input type="number" value={form.reorder_quantity} onChange={set("reorder_quantity")} /></div>
              </div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowForm(false)}>Cancel</button>
                <button type="submit">Save product</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {adjusting && (
        <div className="modal-backdrop" onClick={() => setAdjusting(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
            <h2>Adjust stock for {adjusting.name}</h2>
            <p className="muted">Currently {adjusting.quantity_on_hand} on hand{adjusting.schedule >= 5 && " · S-register entry will be recorded"}</p>
            <form onSubmit={applyAdjust}>
              <div className="field">
                <label>Type</label>
                <Select
                  value={adjType}
                  onChange={setAdjType}
                  options={[
                    { value: "receive", label: "Receive stock (+)" },
                    { value: "adjustment", label: "Adjustment (+/−)" },
                    { value: "return", label: "Customer return (+)" },
                  ]}
                />
              </div>
              <div className="field">
                <label>Quantity {adjType === "adjustment" ? "(use negative to write off)" : ""}</label>
                <input type="number" value={adjQty} onChange={(e) => setAdjQty(e.target.value)} />
              </div>
              {(adjType === "receive" || adjType === "return") && adjusting.category !== "airtime" && (
                <div className="form-row">
                  <div className="field"><label>Batch number</label><input value={adjBatch} onChange={(e) => setAdjBatch(e.target.value)} placeholder="auto if blank" /></div>
                  <div className="field"><label>Expiry date</label><input type="date" value={adjExpiry} onChange={(e) => setAdjExpiry(e.target.value)} /></div>
                </div>
              )}
              <div className="field"><label>Notes</label><input value={adjNotes} onChange={(e) => setAdjNotes(e.target.value)} placeholder="e.g. Breakage, stocktake variance" /></div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setAdjusting(null)}>Cancel</button>
                <button type="submit">Apply</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
