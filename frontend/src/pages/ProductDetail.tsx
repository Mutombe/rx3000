import { useCallback, useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import { EntityLink } from "../components/Filters";
import ProductDispensings from "../components/ProductDispensings";
import RecordPage from "../components/RecordPage";
import { Link, useParams } from "react-router-dom";
import Variants from "../components/Variants";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import Select from "../components/Select";
import { useToast } from "../components/Toast";
import DataTable, { Column } from "../components/DataTable";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Highlights } from "../components/record";
import { PriceChange, Product, ProductDetail as Detail, PurchaseLine,
         StockBatch, StockMovement } from "../types";
import CounsellingPoints from "../components/CounsellingPoints";
import ProductBarcodes from "../components/ProductBarcodes";
import AdjustStock from "../components/AdjustStock";
import Usage from "../components/Usage";

type Tab = "batches" | "movements" | "usage" | "dispensings" | "pricing" | "buying";

function expiryBadge(expiry: string | null) {
  if (!expiry) return <span className="badge muted">No expiry</span>;
  const days = Math.floor((new Date(expiry).getTime() - Date.now()) / 86400000);
  if (days < 0) return <span className="badge danger">Expired</span>;
  if (days < 90) return <span className="badge warn">{days}d left</span>;
  return <span className="badge ok">{fmtDate(expiry)}</span>;
}

export default function ProductDetail() {
  const { id } = useParams();
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  const [filing, setFiling] = useState(false);
  /** The product whose count is being corrected, which is always this one. */
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const toast = useToast();

  const load = useCallback(() => {
    api.get<Detail>(`/api/products/${id}`).then(setData)
      .catch((e) => setError(errorText(e, "That product could not be opened.")));
  }, [id]);

  const TABS: TabDef<Tab>[] = [
    { key: "batches", label: "Batches on hand", count: data?.batches.length },
    { key: "movements", label: "Movement history", count: data?.movements.length },
    // What has gone out month by month. The page can say how much is on the
    // shelf; only this says whether that is a lot.
    { key: "usage", label: "Usage",
      hint: "What has left the shelf each month, and what came in" },
    // What this line has been priced at, and who moved it. The question
    // "why is this the price" is asked while looking at the price.
    // Who it went to. Asked in a recall, in a dispute about a repeat, and
    // whenever a prescriber rings about a patient.
    { key: "dispensings", label: "Dispensed to",
      hint: "Every time this medicine was handed over, and to whom" },
    { key: "pricing", label: "Price history",
      count: data?.price_history?.length,
      hint: "Every time the cost or the selling price moved, and who moved it" },
    // Where it comes from. Readable only from the supplier's side until now,
    // which answers a buyer's question rather than a pharmacist's.
    { key: "buying", label: "Buying",
      count: data?.buying?.length,
      hint: "Who this was last ordered from, what was paid, and whether it came" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "batches");

  useEffect(() => { load(); }, [load]);

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
   *  departments did, and no screen offered it, so a product created outside
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
        trail={[{ label: "Dashboard", to: "/" }, { label: "Stock", to: "/stock" }, { label: "Loading" }]}
        eyebrow="Product"
        tabs={["Batches on hand", "Movement history"]}
        cards={1}
      />;
  const p = data.product;
  // Absent from an older server, and the page still renders: the figures
  // below fall back to what the record itself holds.
  const shelf = data.shelf;

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

  const priceCols: Column<PriceChange>[] = [
    { key: "at", header: "When", sortable: true,
      value: (r) => r.at, render: (r) => fmtDateTime(r.at) },
    // Which figure moved. Cost and selling sit on one timeline and the
    // difference between them is the whole point, so the row has to say
    // which one it is before it says anything else.
    { key: "field", header: "What", sortable: true,
      render: (r) => (
        <span className={`badge ${r.field === "cost" ? "muted" : "ok"}`}>
          {r.field === "cost" ? "Cost" : "Selling"}
        </span>
      ) },
    { key: "was", header: "Was", align: "right", sortable: true,
      render: (r) => money(r.was) },
    { key: "now", header: "Now", align: "right", sortable: true,
      render: (r) => <b>{money(r.now)}</b> },
    { key: "percent", header: "Move", align: "right", sortable: true,
      render: (r) => (
        <span className={r.difference > 0 ? "cu-up" : r.difference < 0 ? "cu-diff" : "muted"}>
          {r.difference > 0 ? "+" : ""}{money(r.difference)}
          {r.was ? ` (${r.percent > 0 ? "+" : ""}${r.percent}%)` : ""}
        </span>
      ) },
    { key: "how", header: "How", truncate: 34 },
    { key: "by", header: "By", render: (r) => r.by || <span className="muted">Not recorded</span> },
    { key: "reason", header: "Reason", truncate: 34 },
  ];

  const buyCols: Column<PurchaseLine>[] = [
    { key: "at", header: "Ordered", sortable: true,
      value: (r) => r.at, render: (r) => fmtDate(r.at) },
    { key: "order_number", header: "Order",
      render: (r) => <EntityLink kind="order" id={r.order_id}>{r.order_number}</EntityLink> },
    { key: "supplier", header: "From",
      render: (r) => (r.supplier_id
        ? <EntityLink kind="supplier" id={r.supplier_id}>{r.supplier}</EntityLink>
        : <span className="muted">Not recorded</span>) },
    // "Units", not "Ordered": the date column is already called that, and
    // two columns of the same name in one table is a table nobody trusts.
    { key: "ordered", header: "Units", align: "right", sortable: true },
    { key: "unit_cost", header: "Cost each", align: "right", sortable: true,
      render: (r) => money(r.unit_cost) },
    // Said in words. "3 of 10" beside a status token is the finding, and the
    // token alone is not.
    { key: "standing", header: "Standing",
      render: (r) => (
        <span className={`badge ${r.received >= r.ordered && r.received
          ? "ok" : r.received ? "warn" : "muted"}`}>{r.standing}</span>
      ) },
  ];

  const moveCols: Column<StockMovement>[] = [
    { key: "created_at", header: "When", sortable: true,
      value: (m) => m.created_at ?? "",
      render: (m) => (m.created_at ? fmtDateTime(m.created_at)
                                   : <span className="muted">not recorded</span>) },
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
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: `${p.name}${p.strength ? ` ${p.strength}` : ""}` }]}
      eyebrow="Product"
      title={`${p.name}${p.strength ? ` ${p.strength}` : ""}`}
      /* NO AVATAR. It was an initial in a coloured circle beside the name of
         a box of tablets, which is the device this design uses for people.
         It also indented the title 58px further in than the breadcrumb above
         it and the card below it, so nothing on the page shared a left edge. */
      subtitle={
        <>
          {p.dosage_form || "form not recorded"} · {p.category.replace(/_/g, " ")}
          {p.schedule > 0 && <> · <span className="badge sched">S{p.schedule}</span></>}
        </>
      }
      /* The numbers somebody reads this header out loud from: a code down the
         telephone to a wholesaler, a barcode checked against a box. */
      meta={[
        ...(p.stock_code
          ? [{ label: "Stock code", value: p.stock_code, mono: true }] : []),
        ...(p.nappi_code
          ? [{ label: "AHFoZ code", value: p.nappi_code, mono: true }] : []),
        ...(p.barcode
          ? [{ label: "Barcode", value: p.barcode, mono: true }] : []),
        { label: "Pack size", value: p.pack_size || "not recorded" },
        { label: "Department",
          value: departments.find((d) => d.id === p.category_id)?.name
            ?? <span className="muted">not filed</span> },
      ]}
      /* THE DEPARTMENT DROPDOWN IS NOT HERE ANY MORE.
         A form control sitting inside the title block is the one thing a
         header should never hold: it made the header 142px tall against 93
         on every other record page, and put an editable field where the eye
         goes to read the name. It sets the department from the details card
         below, where the rest of the record is edited; the header states the
         department as a fact like the others. */
      actions={
        <>
          <Link to={`/stock-take?product=${p.id}`} className="btn secondary">
            Count it
          </Link>
          <Link to={`/stock?tab=movements&product=${p.id}`} className="btn secondary">
            Its movements
          </Link>
        </>
      }
    >

      <div className="card record-hero">
        {/* THE FIGURES A BUYER DECIDES ON.
            The record holds a quantity, a cost and a price. None of those
            answers the question this page is opened with, which is one of "have
            I got any", "what did it really cost me" and "when do I run out".
            The incumbent's stock screen is full of these for the same reason. */}
        <Highlights items={shelf ? [
          { label: "On this shelf", value: String(shelf.here),
            hint: shelf.here_undated > 0
              ? `${shelf.here_undated} more with no expiry recorded`
              : `${shelf.units} across every branch` },
          { label: "Packs", value: String(shelf.packs),
            hint: shelf.per_pack > 1 ? `${shelf.per_pack} units to a pack` : "one unit a pack" },
          { label: "Days of cover",
            value: shelf.days_cover === null ? "not known" : String(shelf.days_cover),
            hint: shelf.a_day > 0 ? `${shelf.a_day} a day over 90 days` : "nothing has gone out" },
          { label: "Average cost", value: money(shelf.avg_cost),
            hint: "weighted over the stock on the shelf" },
          { label: "Markup", value: shelf.markup_percent === null ? "—" : `${shelf.markup_percent}%`,
            hint: `${money(shelf.each)} each, ${shelf.margin_percent ?? "none"}% margin` },
          // What the line has actually EARNED, which the markup beside it does
          // not say: that is the same percentage whether four boxes went out
          // this year or four hundred. Profit where the sales carry a recorded
          // cost, takings where they do not, and the hint says which.
          { label: "Earned in a year",
            value: shelf.year.profit !== null ? money(shelf.year.profit)
                   : shelf.year.revenue > 0 ? money(shelf.year.revenue) : "none",
            hint: shelf.year.units === 0
              ? "nothing has sold in a year"
              : shelf.year.profit !== null
                ? `${shelf.year.units.toLocaleString()} sold for ${money(shelf.year.revenue)}, `
                  + `${shelf.year.margin}% margin`
                : `${shelf.year.units.toLocaleString()} sold. Takings, not profit: `
                  + "no cost was recorded against these sales" },
          { label: "On order", value: String(shelf.on_order),
            hint: shelf.on_order > 0 ? "not yet received" : "nothing outstanding" },
        ] : [
          { label: "On hand", value: String(p.quantity_on_hand),
            hint: p.quantity_on_hand <= p.reorder_level ? "at or below reorder level" : `reorder at ${p.reorder_level}` },
          { label: "Stock value", value: money(data.stock_value), hint: `${money(p.cost_price)} cost` },
          { label: "Selling price", value: money(p.unit_price), hint: `VAT ${Math.round(p.vat_rate * 100)}%` },
        ]} />

        {/* Correcting the count, from the screen it is read on. The same dialog
            the dispensary uses, so a correction made here and one made at the
            counter are the same act with the same record behind it. */}
        <div className="pd-shelf-act">
          <button type="button" className="btn secondary" onClick={() => setAdjusting(p)}>
            Adjust the count
          </button>
          {shelf && (shelf.here + shelf.here_undated) <= shelf.reorder_level && (
            <span className="pd-flag is-low">
              At or below the reorder level of {shelf.reorder_level}
              {shelf.reorder_quantity > 0 && <>, usually ordered {shelf.reorder_quantity} at a time</>}.
            </span>
          )}
          {shelf && shelf.max_level > 0 && shelf.units > shelf.max_level && (
            <span className="pd-flag is-over">
              {shelf.units} on hand against a maximum of {shelf.max_level}.
              That is {shelf.units - shelf.max_level} more than this line should carry
              {shelf.days_cover !== null && <>, about {shelf.days_cover} days of it</>}.
            </span>
          )}
          {shelf?.to_max !== null && shelf?.to_max !== undefined && shelf.to_max > 0
            && (shelf.here + shelf.here_undated) <= shelf.reorder_level && (
            <span className="muted small">
              {shelf.to_max} would take it to the maximum of {shelf.max_level}.
            </span>
          )}
          {/* An empty shelf and an uncounted one are different problems, and
              only one of them is fixed by ordering more. */}
          {shelf?.disagrees && (
            <span className="pd-flag is-off">
              The record says {shelf.units} and the batches behind it hold
              {" "}{shelf.here + shelf.here_undated} at this branch. Count it.
            </span>
          )}
          {shelf && (
            <span className="muted small">
              {money(shelf.at_cost)} at cost · {money(shelf.at_retail)} at retail
              {" · "}{data.units_dispensed} dispensed, {data.units_sold} sold
            </span>
          )}
        </div>
        {/* The codes that were here are in the header now, where somebody
            reading one down a telephone looks first. Repeating them would be
            two places to check and one to forget to update. */}
        <dl className="detail-fields" style={{ marginTop: 14 }}>
          {/* MOVED OUT OF THE PAGE HEADER.
              A dropdown inside the title block made that header 142px tall
              against 93 on every other record page, and put an editable
              field where the eye goes to read the name. It belongs with the
              rest of the record, which is edited here. An unfiled product is
              the commonest reason a stock report shows a large
              "uncategorised" line nobody can explain. */}
          <div>
            <dt>Department</dt>
            <dd>
              <Select
                value={p.category_id == null ? "" : String(p.category_id)}
                onChange={file}
                disabled={filing}
                ariaLabel="Department"
                options={[{ value: "", label: "Not filed" },
                          ...departments.map((d) => ({
                            value: String(d.id), label: d.name }))]}
              />
            </dd>
          </div>
          <div>
            <dt>Bin</dt>
            <dd>
              {p.bin_location
                ? <EntityLink to={`/bins/${p.bin_location}`}>{p.bin_location}</EntityLink>
                : <span className="muted">no shelf</span>}
              {/* Where else it is kept. The stock is valued at the first,
                  so the others are places to walk rather than piles to
                  price. */}
              {(p.bin_location_2 || p.bin_location_3) && (
                <span className="muted small">
                  {" also in "}
                  {[p.bin_location_2, p.bin_location_3].filter(Boolean).join(" and ")}
                </span>
              )}
              {/* The last move, next to the bin itself. "Why is this not on
                  the shelf the label says" is asked while looking at the
                  shelf, not on a history tab two clicks away. */}
              {data.bin_history && data.bin_history.length > 0 && (
                <div className="muted small pd-binmove">
                  {data.bin_history[0].says}
                  {data.bin_history[0].by ? ` by ${data.bin_history[0].by}` : ""}
                  {data.bin_history[0].at ? ` on ${fmtDate(data.bin_history[0].at)}` : ""}
                  {data.bin_history[0].reason ? `. ${data.bin_history[0].reason}` : ""}
                </div>
              )}
            </dd>
          </div>
          <div><dt>Ingredient</dt><dd>{p.active_ingredient
            || <span className="muted">not recorded</span>}</dd></div>
          <div><dt>Manufacturer</dt><dd>{p.manufacturer
            || <span className="muted">not recorded</span>}</dd></div>
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
          /* The lot record: what came in on it, what is left, and where it
             went. Named on this row and unreachable from it. */
          rowHref={(b) => `/batches/${b.id}`}
          totals
          initialSort={{ key: "expiry_date", dir: "asc" }}
          empty="No stock on hand, nothing has been received for this product"
        />
      )}

      {adjusting && (
        <AdjustStock
          product={adjusting}
          // Both known here, so the dialog can tell before it opens whether
          // this correction is the size that needs a second person.
          adjustThreshold={shelf?.adjust_threshold ?? 0}
          unitCost={shelf?.avg_cost ?? shelf?.unit_cost ?? 0}
          onClose={() => setAdjusting(null)}
          onAdjusted={(onHand, settled) => {
            // The figure on the page moves the moment the dialog closes, so
            // this screen is not the one place the correction looks like it
            // did not happen. The batch list and the movement history behind
            // it are a heavier read, so they wait for the server to settle.
            setData((d) => (d && d.shelf
              ? { ...d, shelf: { ...d.shelf, here: onHand } }
              : d));
            if (settled) load();
          }}
        />
      )}

      {tab === "usage" && <Usage productId={p.id} />}

      {tab === "dispensings" && <ProductDispensings productId={p.id} />}

      {tab === "pricing" && (
        <>
          <p className="muted small pd-note">
            Cost and selling on one timeline, because the margin between them
            can only be read that way. A figure that did not move leaves no
            row, so saving the product screen after correcting a spelling does
            not bury the decisions that matter.
          </p>
          <DataTable
            columns={priceCols}
            rows={data.price_history ?? []}
            rowKey={(r) => r.id}
            initialSort={{ key: "at", dir: "desc" }}
            empty="No price change has been recorded for this line yet"
          />
        </>
      )}

      {tab === "buying" && (
        <>
          {data.sourcing && data.sourcing.suppliers.length > 0 && (
            <section className="card pd-source">
              <h3>Where to buy it</h3>
              {/* The reason is stated so somebody can disagree with it. A
                  recommendation nobody can argue with is one nobody can
                  correct when it is wrong about their trade. */}
              <p className="pd-source-says">{data.sourcing.advice.says}</p>
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Supplier</th>
                      <th className="num">Last cost</th>
                      <th className="num">Best seen</th>
                      <th>Record</th>
                      <th className="num">Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sourcing.suppliers.map((sp) => (
                      <tr key={sp.supplier_id}
                          className={sp.supplier_id === data.sourcing!.advice.supplier_id
                            ? "row-flag" : undefined}>
                        <td className="pd-source-name">
                          <EntityLink kind="supplier" id={sp.supplier_id}>
                            {sp.supplier}
                          </EntityLink>
                          {sp.supplier_id === data.sourcing!.advice.supplier_id && (
                            <span className="badge ok">Buy here</span>
                          )}
                          {!sp.delivers && sp.fill_rate !== null && (
                            <span className="badge warn">Short deliveries</span>
                          )}
                        </td>
                        <td className="num">
                          {sp.last_cost !== null ? money(sp.last_cost) : "\u2014"}
                        </td>
                        <td className="num muted">
                          {sp.best_cost !== null ? money(sp.best_cost) : "\u2014"}
                        </td>
                        <td className="pd-source-record">{sp.record}</td>
                        <td className="num">
                          {sp.avg_days !== null ? sp.avg_days : "\u2014"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <p className="muted small pd-note">
            Ordered newest first rather than by arrival, because an order that
            has not arrived is the interesting one when a shelf is empty.
          </p>
          <DataTable
            columns={buyCols}
            rows={data.buying ?? []}
            rowKey={(r) => r.order_id}
            rowHref={(r) => `/orders/${r.order_id}`}
            initialSort={{ key: "at", dir: "desc" }}
            empty="This line has never been ordered through the system"
          />
        </>
      )}

      {tab === "movements" && (
        <DataTable
          columns={moveCols}
          rows={data.movements}
          rowKey={(m) => m.id}
          /* A movement listed here led nowhere, so the one question it
             raises, "what was that and who did it", had to be answered by
             going to Inventory and finding the same row again. */
          rowHref={(m) => `/movements/${m.id}`}
          initialSort={{ key: "created_at", dir: "desc" }}
          empty="No stock movements recorded"
        />
      )}
    </RecordPage>
  );
}
