import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDateTime, money } from "../api";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Avatar, Highlights, Path } from "../components/record";
import ReceiveByScan from "../components/ReceiveByScan";
import { POItem, PurchaseOrder } from "../types";

const PATH_STAGES = [
  { key: "draft", label: "Draft" },
  { key: "sent", label: "Sent to supplier" },
  { key: "received", label: "Received" },
];

export default function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [error, setError] = useState("");

  function load() {
    api.get<PurchaseOrder>(`/api/orders/${id}`).then(setOrder).catch((e) => setError(e.message));
  }
  useEffect(load, [id]);

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
  if (!order) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Purchase orders", to: "/orders" }, { label: "This record" }]}
        eyebrow="Purchase order"
        cards={1}
        table={5}
      />;

  const value = order.items.reduce((s, i) => s + i.unit_cost * i.quantity_ordered, 0);
  const receivedValue = order.items.reduce((s, i) => s + i.unit_cost * i.quantity_received, 0);
  const outstanding = order.items.reduce((s, i) => s + Math.max(0, i.quantity_ordered - i.quantity_received), 0);

  const cols: Column<POItem>[] = [
    { key: "product", header: "Product", sortable: true,
      value: (i) => i.product?.name ?? "",
      render: (i) => (i.product
        ? <EntityLink to={`/products/${i.product.id}`}>{i.product.name} {i.product.strength}</EntityLink>
        : <span className="muted">—</span>) },
    { key: "quantity_ordered", header: "Ordered", align: "right", sortable: true, total: (i) => i.quantity_ordered },
    { key: "quantity_received", header: "Received", align: "right", sortable: true, total: (i) => i.quantity_received },
    { key: "outstanding", header: "Outstanding", align: "right",
      value: (i) => i.quantity_ordered - i.quantity_received,
      render: (i) => {
        const n = i.quantity_ordered - i.quantity_received;
        return n > 0 ? <span className="badge warn">{n}</span> : <span className="muted">0</span>;
      } },
    { key: "unit_cost", header: "Unit cost", align: "right", sortable: true, render: (i) => money(i.unit_cost) },
    { key: "line_total", header: "Line total", align: "right",
      value: (i) => i.unit_cost * i.quantity_ordered,
      render: (i) => <b>{money(i.unit_cost * i.quantity_ordered)}</b>,
      total: (i) => i.unit_cost * i.quantity_ordered, totalRender: (n) => money(n) },
  ];

  async function setStatus(status: string) {
    try {
      await api.post(`/api/orders/${id}/status?status=${status}`);
      load();
    } catch (e: any) { setError(e.message); }
  }

  return (
    <>
      <Breadcrumbs trail={[{ label: "Dashboard", to: "/" }, { label: "Purchase orders", to: "/orders" }, { label: "This record" }]} />
      <div className="page-head">
        <div className="record-title">
          <Avatar first={order.supplier?.name ?? "PO"} last="" size={44} />
          <div>
            <div className="eyebrow">Purchase order</div>
            <h1 className="mono">{order.order_number}</h1>
            <div className="sub">
              {order.supplier?.name ?? "No supplier"} · raised {fmtDateTime(order.created_at)}
            </div>
          </div>
        </div>
        <Link to="/orders" className="btn secondary">← Procurement</Link>
      </div>

      <div className="card record-hero">
        <Path stages={PATH_STAGES} current={order.status} lostKey="cancelled" />
        <Highlights items={[
          { label: "Order value", value: money(value), hint: `${order.items.length} line(s)` },
          { label: "Received value", value: money(receivedValue),
            hint: value ? `${Math.round((receivedValue / value) * 100)}% of order` : "—" },
          { label: "Outstanding units", value: String(outstanding),
            hint: outstanding ? "still to be delivered" : "fully delivered" },
          { label: "Status", value: order.status, hint: order.notes || "—" },
        ]} />
        <div className="record-exit">
          {order.status === "draft" && <button className="small" onClick={() => setStatus("sent")}>Send to supplier</button>}
          {order.status === "sent" && (
            <span className="muted">Receive stock from the Procurement list so batch numbers and expiry dates can be captured</span>
          )}
          {order.status !== "received" && order.status !== "cancelled" && (
            <button className="secondary small" onClick={() => setStatus("cancelled")}>Cancel order</button>
          )}
        </div>
      </div>

      {order.status !== "received" && order.status !== "cancelled" && (
        <ReceiveByScan
          orderId={order.id}
          orderNumber={order.order_number}
          onReceived={load}
        />
      )}

      <DataTable
        columns={cols}
        rows={order.items}
        rowKey={(i) => i.id}
        totals
        empty="This order has no lines"
      />
    </>
  );
}
