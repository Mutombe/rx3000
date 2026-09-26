import { FormEvent, useEffect, useMemo, useState } from "react";
import { useScheduleCodes } from "../schedules";
import { useToast } from "../components/Toast";
import { useSession } from "../session";
import { useConfirm } from "../components/Confirm";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import StockUpload from "../components/StockUpload";
import StockReconcile from "../components/StockReconcile";
import StockWatch from "../components/StockWatch";
import Bins from "../components/Bins";
import Quarantine from "../components/Quarantine";
import SupplierReturns from "../components/SupplierReturns";
import GoodsReceipts from "../components/GoodsReceipts";
import DataTable, { Column } from "../components/DataTable";
import { applyFilters, emptyFilters, EntityLink, FilterBar, FilterState, FilterToggle } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import ExportButton from "../components/ExportButton";
import { Product, StockBatch, StockMovement, Supplier } from "../types";
import { Paged } from "../components/Pagination";
import { ScanBar, ScanResult } from "../components/Scanner";
import { useScanFeed } from "../components/ScannerHub";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import { Link, useNavigate } from "react-router-dom";
import { Clock, Plus, Prohibit, Warning } from "@phosphor-icons/react";
import IconButton from "../components/IconButton";
import BusyButton from "../components/BusyButton";
import Person from "../components/Person";
import PageHead from "../components/PageHead";

type Tab = "products" | "watch" | "bins" | "quarantine" | "deliveries" | "returns" | "batches" | "movements" | "reconcile" | "upload";

const CATEGORIES = ["medicine", "front_shop", "airtime", "consumable"];

/** What each kind of movement is called on a screen, and how loud it is.
 *
 *  The Type filter has carried these words since it was written while the
 *  column beside it printed the stored code, so one screen spelled the same
 *  thing two ways. Kept next to each other here so the next kind added gets
 *  both or neither.
 */
const MOVE_SAID: Record<string, string> = {
  receive: "Received", sale: "Sold", dispense: "Dispensed",
  adjustment: "Adjusted", return: "Returned", write_off: "Written off",
  transfer: "Transferred", count: "Counted",
};
const MOVE_TONE: Record<string, string> = {
  receive: "ok", return: "ok", sale: "warn", dispense: "warn",
  write_off: "danger", adjustment: "muted", transfer: "muted", count: "muted",
};

function expiryBadge(expiry: string | null) {
  if (!expiry) return <span className="badge muted">No expiry</span>;
  const days = Math.floor((new Date(expiry).getTime() - Date.now()) / 86400000);
  if (days < 0) return <span className="badge danger">EXPIRED</span>;
  if (days <= 90) return <span className="badge warn">{days}d left</span>;
  return <span className="badge ok">{fmtDate(expiry)}</span>;
}

const EMPTY = {
  name: "", nappi_code: "", barcode: "", category: "medicine", schedule: 0,
  dosage_form: "", strength: "", pack_size: "", unit_price: 0, cost_price: 0,
  vat_rate: 0.15, quantity_on_hand: 0, reorder_level: 10, max_level: 0,
  reorder_quantity: 20,
  supplier_id: "" as string | number,
  // The pharmacy's own department. It decides which stocktake sheet the line
  // is on, which margin it is judged against, and whether the dispensary
  // offers it while a patient waits — and no screen could set it.
  category_id: "" as string | number,
  // Where it sits on the shelf and who makes it. Both columns existed, both were
  // read by reports and by the stock-take sheet, and neither had a field on this
  // form, so they were NULL on all 545 products.
  bin_location: "", bin_location_2: "", bin_location_3: "", manufacturer: "",
};

/** The stock reports each tab's question actually leads to.
 *
 *  Keys are the registry's own, so a typo is a report that does not open
 *  rather than a wrong one that does. Every key here is registered in
 *  `services/reports/definitions.py`.
 */
const REPORTS_FOR: Record<string, { value: string; label: string }[]> = {
  products: [
    { value: "stock_valuation", label: "What the shelves are worth" },
    { value: "reorder_suggestions", label: "What to reorder" },
    { value: "dead_stock", label: "Stock that is not moving" },
    { value: "negative_stock", label: "Stock exceptions" },
    { value: "uncosted_products", label: "Lines with no cost" },
    { value: "markup", label: "Markup by line" },
  ],
  batches: [
    { value: "expiring_stock", label: "What is about to expire" },
    { value: "expired_stock", label: "What has already expired" },
    { value: "stock_valuation", label: "What the shelves are worth" },
  ],
  movements: [
    { value: "stock_movements", label: "Every movement" },
    { value: "stock_write_offs", label: "What was written off" },
    { value: "write_off_reasons", label: "Why it was written off" },
    { value: "fast_movers", label: "Fast movers" },
    { value: "slow_movers", label: "Slow movers" },
  ],
  bins: [
    { value: "bin_locations", label: "Where everything is kept" },
    { value: "stock_take_variance", label: "What the last counts found" },
  ],
  deliveries: [
    { value: "stock_on_order", label: "What is on order" },
    { value: "goods_received_not_invoiced", label: "Delivered and not billed" },
    { value: "purchases_by_supplier", label: "Purchases by supplier" },
  ],
  returns: [
    { value: "stock_write_offs", label: "What was written off" },
    { value: "supplier_price_variance", label: "Supplier price variance" },
  ],
};

export default function Stock() {
  const sched = useScheduleCodes();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [departments, setDepartments] = useState<{ id: number; name: string; dispensable: boolean }[]>([]);
  const [movements, setMovements] = useState<StockMovement[]>([]);
  // How many findings are standing, for the tab. Asked once when the page
  // opens rather than kept live: the sweep runs each morning, so a number
  // changing while somebody reads the catalogue would be a surprise rather
  // than news.
  const [watching, setWatching] = useState(0);
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
    // First after the catalogue, because it is the only tab that says
    // something nobody asked for. The rest answer a question somebody came
    // with; this one tells them what they did not know to ask.
    { key: "watch", label: "Needs attention", count: watching || undefined,
      hint: "Expired and short dated stock, empty shelves and reorder levels, "
            + "swept each morning" },
    // Next to the catalogue rather than beside the reports, because it is
    // how somebody walks the shop: bin by bin, not product by product.
    { key: "bins", label: "Bins",
      hint: "Which shelf each line lives on, and the stock that is on no shelf" },
    // Next to the bins, because both answer "where is it": one says which
    // shelf, the other says why it may not come off one.
    { key: "quarantine", label: "Held stock",
      hint: "Stock the pharmacy owns that may not be dispensed, sold or transferred" },
    // Straight after Held stock, because that is where a return starts: the
    // goods are already being held and this is what happens to them next.
    { key: "deliveries", label: "Deliveries",
      hint: "Each van as its own document: the driver's note, the invoice "
            + "number, the lots and who signed for them" },
    { key: "returns", label: "Supplier returns",
      hint: "Goods going back to the wholesaler, and the credit owed for them" },
    { key: "batches", label: "Batches & expiry", count: batches.length },
    { key: "movements", label: "Movement history", count: movements.length },
    // Beside the movements, because that is what explains a difference: the
    // two counts disagree and the history is where the reason is.
    { key: "reconcile", label: "Reconciliation",
      hint: "Whether each product's own count agrees with the batches behind it" },
    { key: "upload", label: "Upload",
      hint: "Load a catalogue or a delivery note from a spreadsheet" },
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
  /** A pack scanned on a phone, resolved the way the box on this page
   *  resolves one so the adjust dialog opens identically. */
  async function fromPhone(code: string) {
    if (adjusting) return;          // the dialog owns the flow once it is up
    try {
      onScanned(await api.post<ScanResult>(
        "/api/scan", { code, context: "stock" }));
    } catch (e) {
      toast.error(errorText(e, "That pack could not be read."));
    }
  }

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

  /** Retire a line: out of every picker, history kept.
   *
   *  Deactivated rather than deleted, because a sale line, a batch, a movement
   *  and a controlled-register entry all point at it, and an auditor asking
   *  what was dispensed last March is entitled to a name rather than a
   *  dangling id. The server says so too; this only has to ask.
   */
  async function retire(p: Product) {
    const onHand = p.quantity_on_hand || 0;
    const ok = await confirm({
      title: `Retire ${p.name}?`,
      body: "It comes out of every picker and every reorder list. Everything "
          + "already dispensed against it stays readable, because it has to be."
          + (onHand
              ? ` There are still ${onHand} unit(s) on hand — write them off or `
                + "transfer them, or the next count will find them."
              : ""),
      confirmLabel: "Retire it",
    });
    if (!ok) return;
    try {
      const said = await api.delete<{ message: string; warning?: string }>(
        `/api/products/${p.id}`);
      toast.ok(said.message);
      // The server says what is still on the shelf. Passed on rather than
      // swallowed: it is the one thing that turns into a variance later.
      if (said.warning) toast.error(said.warning);
      load();
    } catch (e) {
      toast.error(errorText(e, "That line could not be retired."));
    }
  }
  /* The reason list, from the endpoint that publishes it, so the chips a
     person filters by and the codes the server stores cannot drift apart. */
  const [reasons, setReasons] = useState<{ code: string; label: string }[]>([]);
  useEffect(() => {
    api.get<{ reasons: { code: string; label: string }[] }>("/api/stock/reasons")
      .then((r) => setReasons(r.reasons))
      .catch(() => {
        // Deliberately silent: without it the Why filter simply offers
        // nothing, and every other filter on the bar still works.
      });
  }, []);
  useScanFeed("Inventory", (code) => void fromPhone(code), !adjusting);
  const navigate = useNavigate();
  const confirm = useConfirm();
  const session = useSession();
  const mayRetire = session.can("stock.deactivate");
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

  /* THE FILTERS GO TO THE SERVER, WHICH IS THE ONLY PLACE THEY MEAN ANYTHING.
     They used to run over `movements`, which is the page that has already
     been fetched: typing a medicine's name searched twenty five rows of five
     thousand and answered "no matches" with total confidence. A filter that
     narrows to what is already on screen does not fail loudly, it gives a
     wrong answer that looks right. */
  const moveQuery = useMemo(() => {
    const p = new URLSearchParams();
    if (moveFilters.q.trim()) p.set("q", moveFilters.q.trim());
    if (moveFilters.from) p.set("date_from", moveFilters.from);
    if (moveFilters.to) p.set("date_to", moveFilters.to);
    const kind = moveFilters.dims.movement_type;
    if (kind) p.set("movement_type", kind);
    const why = moveFilters.dims.reason_code;
    if (why) p.set("reason_code", why);
    const s = p.toString();
    return s ? `&${s}` : "";
  }, [moveFilters]);

  /* Back to page one whenever what is being asked for changes: staying on
     page nine of a filter that now matches four rows shows an empty table. */
  useEffect(() => { setMvPage(1); }, [moveQuery]);

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
        ? <span className={`badge ${p.schedule >= 5 ? "sched" : "muted"}`}>{sched(p.schedule)}</span>
        : <span className="muted">None</span>) },
    /* Barcode folded into the product cell rather than given a column of its
       own. It is a lookup key, not something anyone reads down a list — the
       search box above already matches on it, and as a column it took 130px
       from a table that did not have 130px to spare, pushing "On hand" off the
       screen entirely on a 1280px till. */
    { key: "unit_price", width: 104, header: "Price", align: "right", sortable: true, render: (p) => money(p.unit_price) },
    { key: "cost_price", width: 104, header: "Cost", align: "right", sortable: true, render: (p) => money(p.cost_price) },
    /* ONE NUMBER, AND IT MEANS WHAT YOU CAN REACH.
       This showed the group total, and a `here` was added beside it so both
       were on the row. That is the abstraction leaking: two numbers with two
       meanings and one label, leaving the reader to work out which one answers
       their question. It answers it for them instead.
       When this shelf is empty and another branch is not, the row says so and
       says what to do about it, because "0" on its own sends somebody to the
       reorder list for stock the pharmacy already owns. */
    { key: "quantity_on_hand", width: 128, header: "On hand", align: "right", sortable: true,
      value: (p) => p.here ?? p.quantity_on_hand,
      render: (p) => {
        const here = p.here ?? p.quantity_on_hand;
        const elsewhere = (p.quantity_on_hand ?? 0) - here;
        return (
          <>
            <span className={`badge ${p.category === "airtime" ? "muted"
              : here <= p.reorder_level ? "danger" : "ok"}`}>
              {here}
            </span>
            {here <= 0 && elsewhere > 0 && (
              <div className="muted small">{elsewhere} at another branch</div>
            )}
          </>
        );
      } },
    /* Valued on the same units the column beside it counts. Left on the group
       total it read "0 on hand" and "$412" on one row, which is true of two
       different shelves and reads as a bug on either. */
    { key: "stock_value", width: 128, header: "Stock value", align: "right",
      value: (p) => (p.here ?? p.quantity_on_hand) * p.cost_price,
      render: (p) => money((p.here ?? p.quantity_on_hand) * p.cost_price),
      total: (p) => (p.here ?? p.quantity_on_hand) * p.cost_price,
      totalRender: (n) => money(n) },
    { key: "actions", header: "", align: "right",
      render: (p) => (
        <span style={{ whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
          <IconButton action="edit" onClick={() => openEdit(p)} />
          <IconButton action="adjust" onClick={() => setAdjusting(p)} />
          {/* RETIRING A LINE, WHICH HAD NO CONTROL AT ALL.
              The endpoint has required `stock.deactivate` since the catalogue
              gates were added and no screen ever called it, so a discontinued
              medicine stayed in every picker and every reorder list for ever.
              Offered only to somebody who may actually do it, because a
              disabled button that never explains itself is worse than no
              button. */}
          {mayRetire && p.active !== false && (
            <IconButton action="delete" title="Retire this line"
                        onClick={() => void retire(p)} />
          )}
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
      render: (b) => <span className="mono">{b.reference || "none"}</span> },
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
    { key: "created_at", header: "When", sortable: true, width: 160,
      value: (m) => m.created_at ?? "",
      render: (m) => (m.created_at ? fmtDateTime(m.created_at)
                                   : <span className="muted">Not recorded</span>) },
    /* The medicine, followable. It was the plain name of the one thing on the
       row somebody might want to look at, on a screen whose whole subject is
       what happened to that medicine. */
    { key: "product", header: "Product", sortable: true, width: 136,
      value: (m) => m.product?.name ?? "",
      render: (m) => (m.product?.name
        ? <EntityLink kind="product" id={m.product_id}>{m.product.name}</EntityLink>
        : <span className="muted">Not named</span>) },
    { key: "movement_type", header: "Type", sortable: true, width: 96,
      /* Said in words. The filter beside it offered "Write-off" and the column
         printed "write_off", which is one thing spelled two ways on one
         screen, and the raw form is the database's spelling rather than
         anybody's. */
      render: (m) => (
        <span className={`badge ${MOVE_TONE[m.movement_type] ?? "muted"}`}>
          {MOVE_SAID[m.movement_type] ?? m.movement_type.replace(/_/g, " ")}
        </span>
      ) },
    /* IN OR OUT, WHICH IS THE WHOLE POINT OF A MOVEMENT.
       The header was "Δ Qty": a Greek letter on a pharmacy screen, and the
       only cue to direction was a minus sign three characters wide in a
       right-aligned column. Direction is what the reader is scanning for. */
    { key: "quantity_delta", header: "In or out", align: "right", sortable: true, width: 100,
      render: (m) => (
        <span className={m.quantity_delta < 0 ? "mv-out" : "mv-in"}>
          {m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta}
          <span className="mv-way">{m.quantity_delta < 0 ? "out" : "in"}</span>
        </span>
      ) },
    { key: "balance_after", header: "Balance", align: "right", sortable: true, width: 84 },
    /* WHY AND WHO, WHICH WERE RECORDED FROM THE START AND SHOWN NOWHERE.
       Every adjustment has asked for a reason from a list since the dialog
       was written, and stamped the staff member who did it. Neither reached
       this table, so the two questions a stock movement is ever asked could
       not be answered from the screen that exists to answer them. */
    /* Blank, not a dash. A sale has no reason code and never will: the reason
       it happened is that it was sold, and the column exists for adjustments.
       A dash on every one of twenty-five rows reads as missing data. */
    { key: "reason", header: "Why", sortable: true, width: 90, value: (m) => m.reason ?? "",
      render: (m) => (m.reason ? <span className="badge">{m.reason}</span> : null) },
    /* Followable. "Who moved this stock" is one of the two questions a
       movement is ever asked, and the answer was a name nobody could open. */
    { key: "user_name", header: "Who", sortable: true, width: 155,
      value: (m) => m.user_name ?? "",
      render: (m) => (m.user_name
        ? <EntityLink kind="staff" id={m.user_id ?? 0}><Person name={m.user_name} /></EntityLink>
        : <span className="muted">Not recorded</span>) },
    /* THE RECORD THAT CAUSED THE MOVEMENT.
       A movement never happens by itself: something dispensed it, sold it or
       booked it in, and the reference is the name of that something. It was
       printed as monospace text, truncated at 34 characters, and led nowhere,
       so the causing record was named on screen and unreachable from it. */
    { key: "reference", header: "Reference", wrap: true,
      render: (m) => (
        <>
          {m.prescription_id
            ? <EntityLink to={`/prescriptions/${m.prescription_id}`}>
                {m.reference || `Script ${m.prescription_id}`}
              </EntityLink>
            : <span className="mono">{m.reference}</span>}
          {m.notes && <div className="muted small">{m.notes}</div>}
        </>
      ) },
  ];

  function load() {
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(q)}${lowOnly ? "&low_stock=true" : ""}`).then(setProducts).catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, [q, lowOnly]);
  useEffect(() => { api.get<Supplier[]>("/api/suppliers").then(setSuppliers); }, []);
  // Only the count. The list itself is the Needs attention tab's own business.
  useEffect(() => {
    api.get<{ items: unknown[] }>("/api/stock/alerts")
      .then((r) => setWatching(r.items.length))
      .catch(() => setWatching(0));
  }, []);
  useEffect(() => {
    api.get<{ items: { id: number; name: string; dispensable: boolean }[] }>("/api/stock-categories")
      .then((d) => setDepartments(d.items ?? []))
      .catch(() => setDepartments([]));
  }, []);
  useEffect(() => {
    if (tab === "movements")
      api
        .get<Paged<StockMovement>>(
          `/api/stock/movements/paged?page=${mvPage}&per_page=${mvSize}` + moveQuery)
        .then((r) => {
          setMovements(r.items);
          setMvMeta(r);
          if (r.page !== mvPage) setMvPage(r.page);
        })
        .catch((e) => toast.error(errorText(e)));
    if (tab === "batches") loadBatches();
  }, [tab, expiringOnly, mvPage, mvSize, bPage, bSize, moveQuery]);
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
    setForm({ ...p, supplier_id: p.supplier_id ?? "", category_id: p.category_id ?? "" });
    setShowForm(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { ...form,
                   supplier_id: form.supplier_id === "" ? null : Number(form.supplier_id),
                   category_id: form.category_id === "" ? null : Number(form.category_id) };
    delete body.id; delete body.active; delete body.medical_aid;
    try {
      // Closed before the write, not after it. A record being created
      // or edited costs a click if it fails, and the list is what
      // confirms it either way.
      setShowForm(false);
      if (editing) {
        delete body.quantity_on_hand;
        await api.put(`/api/products/${editing.id}`, body);
      } else {
        await api.post("/api/products", body);
      }
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
      <PageHead
        title="Inventory"
        sub="Products, quantities, movements and reorder levels"
        /* Which dataset leaves follows the tab, so the button is never a guess.
           The format is asked for rather than assumed: the counter machine has
           Excel open, and something else has to swallow a CSV. */
        take={<ExportButton dataset={tab === "batches" ? "batches" : "products"} />}
        /* THE REPORTS, FROM WHERE THE QUESTION IS ASKED.

           There are twenty six stock reports and every one of them was
           reachable only through a nav item labelled "Analytics", gated on a
           money capability, with no link from this page at all. So they existed
           and could not be found, which for a user is the same as not existing.

           Offered per tab, because the report that answers "what is about to
           expire" is not the one that answers "where did this go", and a list
           of twenty six is its own kind of hiding.

           THIS WAS A NATIVE SELECT, AND WHY IT IS NOT ANY MORE

           The app's own combobox rendered here as a 208 by 224 empty panel, and
           the note that replaced it blamed "something in this header's cascade"
           and said no other screen put one in a page head. Both were wrong.
           Five other screens do, and every one of them works.

           208 pixels is 13rem, which was the width on `.stock-reports-pick` — a
           class written for a native select, with a fixed width and a fixed
           height, put on a control that sizes itself. The panel was clipped to
           the box the class gave it, so the options were rendered and could not
           be seen. The same shape as the `.lbl` bug: a class written for one
           control worn by another. */
        also={
          <Select
            value=""
            placeholder="Reports…"
            onChange={(key) => { if (key) navigate(`/reports?report=${key}`); }}
            options={(REPORTS_FOR[tab] ?? REPORTS_FOR.products)
              .map((r) => ({ value: r.value, label: r.label }))}
          />
        }
        primary={
          <button className="btn primary" onClick={openNew}>
            <Plus size={14} weight="bold" /> New product
          </button>
        }
      />

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
            /* WHAT TO LOOK AT, AND WHAT TO DO ABOUT IT.
               A lone tick box saying "expiring within 90 days only" is a
               filter and not a screen: somebody looking at short-dated
               stock wants to narrow it, then act on it, and every way of
               acting was one row at a time or on another screen entirely.

               The two states are named rather than left as on and off,
               because "not ticked" does not say "everything on hand" to
               anybody reading it quickly. */
            <div className="batch-tools">
              <div className="seg" role="group" aria-label="Which batches">
                <button type="button"
                        className={expiringOnly ? "" : "on"}
                        onClick={() => setExpiringOnly(false)}>
                  Everything on hand
                </button>
                <button type="button"
                        className={expiringOnly ? "on" : ""}
                        onClick={() => setExpiringOnly(true)}>
                  Short dated, 90 days
                </button>
              </div>
              <div className="batch-acts">
                {/* Both of these existed and neither could be reached from
                    the screen they belong to. */}
                <Link className="btn secondary small"
                      to="/reports?report=expiring_stock">
                  <Clock size={13} /> What is about to expire
                </Link>
                <Link className="btn secondary small"
                      to="/reports?report=expired_stock">
                  <Warning size={13} /> What has already expired
                </Link>
                <Link className="btn secondary small" to="/stock?tab=quarantine">
                  <Prohibit size={13} /> Held stock
                </Link>
              </div>
            </div>
          }
        />
      )}

      {tab === "products" && (
        <div className="stock-scan-row" style={{ marginBottom: "var(--s3)" }}>
          <ScanBar
            context="stock"
            onResolved={onScanned}
            placeholder="Scan a pack to adjust it, or type a code…"
            enabled={!adjusting}
          />
          {/* Checking a shelf is done at the shelf. The counter scanner is on
              a cable at the till, so without this the only way to look
              something up while standing in front of it was to carry the box
              back to the machine. */}
        </div>
      )}

      {tab === "products" && (
        <DataTable
          loading={loading}
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
                placeholder="Search name / AHFoZ code / barcode…"
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
                    options: [0, 1, 2, 3, 4, 5, 6].map((n) => [String(n), sched(n)] as [string, string]) },
                ]}
                // So Clear clears this too. It used to leave it on, and a
                // screen still filtered to the low-stock lines after
                // somebody had pressed the button that says it clears the
                // filters is a screen that has lied to them.
                extras={{ active: lowOnly, clear: () => setLowOnly(false) }}
              >
                <FilterToggle checked={lowOnly} onChange={setLowOnly}
                              hint="Only lines at or below their reorder level">
                  Low stock only
                </FilterToggle>
              </FilterBar>
            </>
          }
        />
      )}

      {tab === "watch" && <StockWatch />}
      {tab === "bins" && <Bins />}
      {tab === "quarantine" && <Quarantine />}
      {tab === "deliveries" && <GoodsReceipts />}
    {tab === "returns" && <SupplierReturns />}
      {tab === "reconcile" && <StockReconcile />}

      {tab === "upload" && <StockUpload onDone={load} />}

      {tab === "movements" && (
        <DataTable
          columns={movementCols}
          rows={movements}
          rowKey={(m) => m.id}
          // The movement, not the product. Clicking a row used to go to the
          // medicine, which is the thing the reader was already looking at, so
          // the click cost them their place and told them nothing new.
          rowHref={(m) => `/movements/${m.id}`}
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
              }, {
                /* Read from the server rather than listed here. The screen
                   that WRITES these reasons kept its own copy of the list;
                   a second copy on the screen that reads them is how the
                   two drift until a filter silently matches nothing. */
                key: "reason_code", label: "Why",
                options: reasons.map((r) => [r.code, r.label] as [string, string]),
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
                      label: sched(n),
                      // The register requirement belongs beside the schedule, not
                      // in the head of whoever is filling the form in.
                      hint: n >= 5 ? "controlled, register entry required" : undefined,
                    }))}
                  />
                </div>
                <div className="field">
                  <label>Department</label>
                  <Select
                    value={String(form.category_id ?? "")}
                    onChange={(v) => set("category_id")({ target: { value: v } } as any)}
                    placeholder="None"
                    clearable
                    searchable
                    options={departments.map((d) => ({
                      value: String(d.id),
                      label: d.name,
                      // Said here, where the filing decision is made: this is
                      // what puts a line in front of a dispenser, or keeps it
                      // in the shop.
                      hint: d.dispensable ? "dispensed here" : "shop only",
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
                <div className="field"><label>AHFoZ code</label><input value={form.nappi_code} onChange={set("nappi_code")} /></div>
                <div className="field"><label>Barcode</label><input value={form.barcode} onChange={set("barcode")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Bin location</label>
                  <input value={form.bin_location} onChange={set("bin_location")} placeholder="e.g. A3-04" />
                </div>
                {/* The other two places it is kept, if it is. Left blank on
                    almost every line: a product normally lives in one bin,
                    and these are for the one that is also in the back store
                    or the fridge. Stock is valued at the first. */}
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>Also in</label>
                  <input value={form.bin_location_2} onChange={set("bin_location_2")}
                         placeholder="optional" />
                </div>
                <div className="field" style={{ maxWidth: 140 }}>
                  <label>And in</label>
                  <input value={form.bin_location_3} onChange={set("bin_location_3")}
                         placeholder="optional" />
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
                {/* The floor and the ceiling. A floor alone answers "order
                    now" and never catches the opposite mistake: a line nobody
                    is selling, reordered to the same level every month until
                    there is a year of it on the shelf. */}
                <div className="field"><label>Min level</label>
                  <input type="number" min={0} value={form.reorder_level}
                         onChange={set("reorder_level")} />
                  <span className="hint">At or below this it is on the reorder list.</span>
                </div>
                <div className="field"><label>Max level</label>
                  <input type="number" min={0} value={form.max_level ?? 0}
                         onChange={set("max_level")} />
                  <span className="hint">Leave at zero for no ceiling.</span>
                </div>
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
            {/* The shelf this adjustment will actually move. An adjustment is
                drawn from one branch, so the group total was the wrong figure
                to put in front of somebody about to correct a count. */}
            <p className="muted">
              Currently {adjusting.here ?? adjusting.quantity_on_hand} on hand
              {adjusting.schedule >= 5
                && ` · ${sched(adjusting.schedule)} register entry will be recorded`}
            </p>
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
