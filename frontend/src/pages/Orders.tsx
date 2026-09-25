import { useCallback, Fragment, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { api, fmtDateTime, money, errorText  } from "../api";
import NewOrder from "../components/NewOrder";
import { EntityLink, TableSearch, useSearch } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Product, PurchaseOrder } from "../types";
import Pagination, { Paged } from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import { Lightning, Plus } from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";
import ReceiveDelivery from "../components/ReceiveDelivery";
import PageHead from "../components/PageHead";

type Tab = "orders" | "low" | "approve";

interface Orphan { product_id: number; product: string; quantity: number }

interface Approvals {
  /** Below zero means this pharmacy has not asked for approvals at all. */
  threshold: number;
  count: number;
  orders: (PurchaseOrder & { value: number })[];
}

interface Suggested {
  orders: PurchaseOrder[];
  needs_a_supplier: Orphan[];
  message: string;
}

export default function Orders() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  /* A wholesaler rings about one order number, or somebody asks what is
     outstanding with one supplier. The status tabs answer neither. */
  const { q, setQ, shown } = useSearch(orders, (o) =>
    [o.order_number, o.supplier?.name, o.status]);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<Paged<PurchaseOrder> | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [lowStock, setLowStock] = useState<Product[]>([]);
  // A reorder sheet needs every shortfall to decide from; the DOM does not.
  const lowStockRows = useClientPage<Product>(lowStock, 25);
  const [expanded, setExpanded] = useState<number | null>(null);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  /** Low lines with nobody to buy them from, after the last sweep. */
  const [orphans, setOrphans] = useState<Orphan[]>([]);
  /** Orders over the pharmacy's threshold that nobody has signed off. */
  const [approvals, setApprovals] = useState<Approvals | null>(null);

  const loadApprovals = useCallback(() => {
    api.get<Approvals>("/api/orders/awaiting-approval")
      .then(setApprovals)
      .catch(() => {
        // Deliberately silent: where a pharmacy has not asked for approvals
        // this is simply empty, and the rest of the page is unaffected.
      });
  }, []);
  useEffect(loadApprovals, [loadApprovals]);

  /** Sign one off. The server refuses if you raised it yourself, which is
   *  the whole of the control, and says so. */
  async function approve(order: PurchaseOrder) {
    try {
      const said = await api.post<{ message: string }>(`/api/orders/${order.id}/approve`);
      toast.ok(said.message);
      loadApprovals();
      load();
    } catch (e) {
      toast.error(errorText(e, "That order could not be approved."));
    }
  }
  const [raising, setRaising] = useState(false);
  const [receiving, setReceiving] = useState<PurchaseOrder | null>(null);

  const TABS: TabDef<Tab>[] = [
    { key: "orders", label: "Purchase orders", count: orders.length },
    { key: "low", label: "Reorder needs", count: lowStock.length,
      hint: "Products at or below their reorder level" },
    /* THE QUEUE. Without one, approval is a thing somebody discovers at the
       moment they try to send — the worst time, and usually the wrong
       person. Hidden entirely where the pharmacy has not asked for
       approvals, because an empty tab that can never fill is clutter. */
    ...(approvals && approvals.threshold >= 0
      ? [{ key: "approve" as Tab, label: "Waiting for approval",
           count: approvals.count,
           hint: `Orders worth more than ${money(approvals.threshold)}` }]
      : []),
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "orders");

  function load() {
    setLoading(true);
    api
      .get<Paged<PurchaseOrder>>(`/api/orders/paged?page=${page}&per_page=${perPage}`)
      .then((r) => {
        setOrders(r.items);
        setMeta(r);
        if (r.page !== page) setPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    api.get<Product[]>("/api/products?low_stock=true").then(setLowStock);
  }

  useEffect(load, [page, perPage]);

  async function generate() {
    setBusy(true);
    try {
      const said = await api.post<Suggested>("/api/orders/suggest");
      toast.ok(said.message);
      // WHAT COULD NOT BE ORDERED, NAMED.
      //
      // A line that is low and has nobody on record used to be ordered from
      // whichever supplier the database returned first — a real order to a
      // real wholesaler who does not sell it. It is refused now, which is
      // right, and refusing silently would be its own kind of wrong: these
      // are exactly the lines somebody has to make a decision about.
      setOrphans(said.needs_a_supplier ?? []);
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  /** Send it for real. This used to set the status to "sent" and the order
   *  never left the building. */
  async function send(order: PurchaseOrder) {
    try {
      const said = await api.post<{ message: string }>(`/api/orders/${order.id}/send`);
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That order could not be sent."));
    }
  }

  async function setStatus(order: PurchaseOrder, status: string) {
    try {
      await api.post(`/api/orders/${order.id}/status?status=${status}`);
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  const badge = (s: string) =>
    s === "received" ? "ok" : s === "sent" ? "warn" : s === "cancelled" ? "danger" : "muted";

  return (
    <>
      <PageHead title="Procurement" sub="Purchase orders fully integrated with stock control">
        {/* The sweep covers the routine. This covers every reason a pharmacy
                      actually telephones a wholesaler, none of which is routine. */}
                  <button className="btn primary" onClick={() => setRaising(true)}>
                    <Plus size={15} weight="bold" /> New order
                  </button>
                  <button className="secondary" onClick={generate} disabled={busy}>{busy ? "Working…" : <><Lightning size={15} weight="fill" /> Generate from reorder levels</>}</button>
      </PageHead>

      {raising && (
        <NewOrder onClose={() => setRaising(false)} onCreated={load} />
      )}

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "orders" && (
        <div className="card">
          <Refreshable
            loading={loading}
            hasData={orders.length > 0}
            skeleton={<TableSkeleton cols={8} rows={8} rowHeight={55} widths={["3ch", "14ch", "20ch", "12ch", "16ch", "7ch", "12ch", "10ch"]} />}
          >
            <TableSearch value={q} onChange={setQ}
                         placeholder="Find an order or a supplier…"
                         shown={shown.length} total={orders.length} />
            <table>
              <thead>
                <tr><th></th><th>Order</th><th>Supplier</th><th>Status</th><th>Raised</th>
                  <th className="num">Lines</th><th className="num">Value</th><th className="actions" /></tr>
              </thead>
              <tbody>
                {shown.map((o) => {
                  const open = expanded === o.id;
                  const value = o.items.reduce((s, i) => s + i.unit_cost * i.quantity_ordered, 0);
                  return (
                    <Fragment key={o.id}>
                      <tr className="row-click" onClick={() => setExpanded(open ? null : o.id)}>
                        <td style={{ width: 22 }} className="muted">{open ? "▾" : "▸"}</td>
                        <td><EntityLink to={`/orders/${o.id}`}><span className="mono">{o.order_number}</span></EntityLink></td>
                        <td><EntityLink kind="supplier" id={o.supplier_id}>{o.supplier?.name}</EntityLink></td>
                        <td><span className={`badge ${badge(o.status)}`}>{o.status}</span></td>
                        <td className="muted">{fmtDateTime(o.created_at)}</td>
                        <td className="num">{o.items.length}</td>
                        <td className="num">{money(value)}</td>
                        <td className="actions" onClick={(e) => e.stopPropagation()}>
                          {o.status === "draft" && <BusyButton className="small" busyLabel="Sending…" onClick={() => send(o)}>Send</BusyButton>}
                          {o.status === "sent" && <button className="small" onClick={() => setReceiving(o)}>Receive</button>}
                          {o.status !== "received" && o.status !== "cancelled" && (
                            <BusyButton className="ghost small" onClick={() => setStatus(o, "cancelled")}>Cancel</BusyButton>
                          )}
                        </td>
                      </tr>
                      {open && (
                        <tr className="detail-row">
                          <td colSpan={8}>
                            {o.notes && <div className="muted" style={{ marginBottom: 8 }}>{o.notes}</div>}
                            <div className="line-list">
                              {o.items.map((i) => (
                                <div key={i.id}>
                                  <span>{i.product?.name} {i.product?.strength}</span>
                                  <span className="muted">{i.quantity_received}/{i.quantity_ordered} received</span>
                                  <span className="num">{money(i.unit_cost)} ea</span>
                                  <b className="num">{money(i.unit_cost * i.quantity_ordered)}</b>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {meta && (
            <Pagination
              meta={meta}
              noun="orders"
              onPage={setPage}
              onPerPage={(n) => { setPerPage(n); setPage(1); }}
            />
          )}
        </Refreshable>
          {!loading && orders.length === 0 && (
            <div className="empty">No purchase orders yet, generate them from reorder levels.</div>
          )}
        </div>
      )}

      {tab === "approve" && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>Waiting for a second signature</h3>
              <span className="muted small">
                This pharmacy asks somebody else to sign off an order worth
                more than {money(approvals?.threshold ?? 0)}. You cannot
                approve one you raised yourself.
              </span>
            </div>
          </div>
          {(approvals?.orders.length ?? 0) === 0 ? (
            <div className="empty">
              <b>Nothing is waiting.</b>
              <p>Orders under the threshold go straight out.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Order</th><th>Supplier</th><th>Raised</th>
                    <th className="num">Worth</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {approvals!.orders.map((o) => (
                    <tr key={o.id}>
                      <td>
                        <EntityLink to={`/orders/${o.id}`}>{o.order_number}</EntityLink>
                      </td>
                      <td>{o.supplier?.name ?? <span className="muted">None</span>}</td>
                      <td className="small">{fmtDateTime(o.created_at)}</td>
                      <td className="num"><b>{money(o.value)}</b></td>
                      <td className="actions">
                        <BusyButton className="small" busyLabel="Approving…"
                                    onClick={() => approve(o)}>
                          Approve
                        </BusyButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "low" && (
        <div className="card">
          {/* Named after a sweep, because these are the decisions it could
              not make. Shown here rather than in a toast that disappears:
              acting on them means finding a supplier for each line. */}
          {orphans.length > 0 && (
            <div className="alert warn">
              <b>{orphans.length} line(s) are low and have no supplier on
              record</b>, so nothing was ordered for them. Set a supplier on
              each, or raise an order by hand.
              <ul className="ord-orphans">
                {orphans.map((o) => (
                  <li key={o.product_id}>
                    <EntityLink to={`/products/${o.product_id}`}>{o.product}</EntityLink>
                    <span className="muted"> needs {o.quantity}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <table>
            <thead><tr><th>Product</th><th className="num">On hand</th><th className="num">Reorder level</th><th className="num">Suggested qty</th></tr></thead>
            <tbody>
              {lowStockRows.items.map((p: Product) => (
                <tr key={p.id}>
                  <td>{p.name} {p.strength}</td>
                  <td className="num"><span className="badge danger">{p.quantity_on_hand}</span></td>
                  <td className="num">{p.reorder_level}</td>
                  <td className="num">{Math.max(p.reorder_quantity, p.reorder_level - p.quantity_on_hand)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={lowStockRows.meta} onPage={lowStockRows.setPage} noun="products" />
          {lowStock.length === 0 && <div className="empty">Nothing is at or below its reorder level</div>}
        </div>
      )}

      {receiving && (
        <ReceiveDelivery
          order={receiving}
          onCancel={() => setReceiving(null)}
          onDone={(said) => { setReceiving(null); toast.ok(said); load(); }}
        />
      )}
    </>
  );
}
