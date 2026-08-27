import { Fragment, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { api, fmtDateTime, money, errorText  } from "../api";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { Product, PurchaseOrder } from "../types";
import Pagination, { Paged } from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import { Lightning } from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";

interface ReceiveLine {
  item_id: number;
  label: string;
  batch_number: string;
  expiry_date: string;
}

type Tab = "orders" | "low";

export default function Orders() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
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
  const [receiving, setReceiving] = useState<PurchaseOrder | null>(null);
  const [receiveLines, setReceiveLines] = useState<ReceiveLine[]>([]);

  const TABS: TabDef<Tab>[] = [
    { key: "orders", label: "Purchase orders", count: orders.length },
    { key: "low", label: "Reorder needs", count: lowStock.length,
      hint: "Products at or below their reorder level" },
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
      const created = await api.post<PurchaseOrder[]>("/api/orders/suggest");
      toast.ok(created.length ? `Created ${created.length} draft order(s) from reorder levels.` : "Nothing at reorder level, no orders needed.");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
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

  function openReceive(order: PurchaseOrder) {
    setReceiving(order);
    setReceiveLines(order.items.map((i) => ({
      item_id: i.id,
      label: `${i.product?.name ?? ""} ${i.product?.strength ?? ""} × ${i.quantity_ordered}`,
      batch_number: "",
      expiry_date: "",
    })));
  }

  async function submitReceive() {
    if (!receiving) return;
    try {
      await api.post(`/api/orders/${receiving.id}/status?status=received`, {
        lines: receiveLines.map((l) => ({
          item_id: l.item_id,
          batch_number: l.batch_number,
          expiry_date: l.expiry_date || null,
        })),
      });
      setReceiving(null);
      toast.ok("Stock received, batches created and quantities updated.");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  const badge = (s: string) =>
    s === "received" ? "ok" : s === "sent" ? "warn" : s === "cancelled" ? "danger" : "muted";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Procurement</h1>
          <div className="sub">Purchase orders fully integrated with stock control</div>
        </div>
        <button onClick={generate} disabled={busy}>{busy ? "Working…" : <><Lightning size={15} weight="fill" /> Generate from reorder levels</>}</button>
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "orders" && (
        <div className="card">
          <Refreshable
            loading={loading}
            hasData={orders.length > 0}
            skeleton={<TableSkeleton cols={8} rows={5} widths={["3ch", "14ch", "20ch", "12ch", "16ch", "7ch", "12ch", "10ch"]} />}
          >
            <table>
              <thead>
                <tr><th></th><th>Order</th><th>Supplier</th><th>Status</th><th>Raised</th>
                  <th className="num">Lines</th><th className="num">Value</th><th className="actions" /></tr>
              </thead>
              <tbody>
                {orders.map((o) => {
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
                          {o.status === "draft" && <BusyButton className="small" onClick={() => setStatus(o, "sent")}>Send</BusyButton>}
                          {o.status === "sent" && <button className="small" onClick={() => openReceive(o)}>Receive</button>}
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
          {orders.length === 0 && (
            <div className="empty">No purchase orders yet, generate them from reorder levels.</div>
          )}
        </div>
      )}

      {tab === "low" && (
        <div className="card">
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
        <div className="modal-backdrop" onClick={() => setReceiving(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Receive {receiving.order_number}</h2>
            <p className="muted">Capture the batch number and expiry date from each delivered pack. Left blank, a batch number is auto-generated and a 2-year shelf life assumed.</p>
            {receiveLines.map((l, idx) => (
              <div key={l.item_id} style={{ borderTop: "1px solid rgba(28,29,27,0.08)", paddingTop: 12, marginTop: 12 }}>
                <b>{l.label}</b>
                <div className="form-row" style={{ marginTop: 8 }}>
                  <div className="field">
                    <label>Batch number</label>
                    <input value={l.batch_number} placeholder="auto"
                      onChange={(e) => setReceiveLines(receiveLines.map((x, i) => i === idx ? { ...x, batch_number: e.target.value } : x))} />
                  </div>
                  <div className="field">
                    <label>Expiry date</label>
                    <input type="date" value={l.expiry_date}
                      onChange={(e) => setReceiveLines(receiveLines.map((x, i) => i === idx ? { ...x, expiry_date: e.target.value } : x))} />
                  </div>
                </div>
              </div>
            ))}
            <div className="modal-actions">
              <button className="secondary" onClick={() => setReceiving(null)}>Cancel</button>
              <button onClick={submitReceive}>Receive into stock</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
