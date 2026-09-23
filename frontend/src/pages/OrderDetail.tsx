import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import RecordPage from "../components/RecordPage";
import { Link, useParams } from "react-router-dom";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { useToast } from "../components/Toast";
import DataTable, { Column } from "../components/DataTable";
import { EntityLink } from "../components/Filters";
import { Highlights, Path } from "../components/record";
import ReceiveByScan from "../components/ReceiveByScan";
import { POItem, PurchaseOrder } from "../types";
import { ArrowLeft } from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";

const PATH_STAGES = [
  { key: "draft", label: "Draft" },
  { key: "sent", label: "Sent to supplier" },
  { key: "received", label: "Received" },
];

export default function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState<PurchaseOrder | null>(null);
  const [error, setError] = useState("");
  /** The document, when somebody asks to see it before it goes. */
  const [preview_, setPreview] = useState<string | null>(null);
  const toast = useToast();

  /** Actually send it, and say where it went. */
  async function sendToSupplier() {
    try {
      const said = await api.post<{ message: string }>(`/api/orders/${id}/send`);
      toast.ok(said.message);
      load();
    } catch (e) {
      // The server refuses with the reason — no address on the supplier, no
      // lines, the mail server said no — and each of those is something a
      // person can act on. Passed through as written.
      toast.error(errorText(e, "That order could not be sent."));
    }
  }

  /** Sign it off. Refused by the server if you raised it yourself, which is
   *  the whole of the control. */
  async function approve() {
    try {
      const said = await api.post<{ message: string }>(`/api/orders/${id}/approve`);
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That order could not be approved."));
    }
  }

  async function preview() {
    try {
      const said = await api.get<{ document: string }>(`/api/orders/${id}/document`);
      setPreview(said.document);
    } catch (e) {
      toast.error(errorText(e, "That order could not be read."));
    }
  }

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
        trail={[{ label: "Dashboard", to: "/" }, { label: "Purchase orders", to: "/orders" }, { label: "Loading" }]}
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
        : <span className="muted">none</span>) },
    { key: "quantity_ordered", header: "Ordered", align: "right", sortable: true, total: (i) => i.quantity_ordered },
    // Between Ordered and Received on purpose: it is the middle fact in the
    // life of a line, and the person receiving a delivery wants to know what
    // was promised before they count what turned up.
    { key: "quantity_confirmed", header: "Coming", align: "right",
      value: (i) => i.quantity_confirmed ?? -1,
      render: (i) => {
        // Null is "they have not said", which is a different answer from
        // nought and must not be shown as one.
        if (i.quantity_confirmed == null) {
          return <span className="muted">not said</span>;
        }
        const short = i.quantity_confirmed < i.quantity_ordered;
        return short
          ? <span className="badge warn">{i.quantity_confirmed}</span>
          : <span>{i.quantity_confirmed}</span>;
      } },
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
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Purchase orders", to: "/orders" },
              { label: order.order_number }]}
      eyebrow="Purchase order"
      /* No avatar. An initial in a coloured circle is how this design shows
         a person; a purchase order is not one, and it broke the left edge
         the trail and the cards below it share. */
      title={<span className="mono">{order.order_number}</span>}
      meta={[
        { label: "Supplier",
          value: order.supplier
            ? <EntityLink kind="supplier" id={order.supplier_id}>
                {order.supplier.name}
              </EntityLink>
            : <span className="muted">none recorded</span> },
        { label: "Raised", value: fmtDateTime(order.created_at) },
        { label: "Lines", value: order.items.length },
      ]}
      actions={
        <Link to="/rfqs" className="btn secondary">Quotes</Link>
      }
    >

      <div className="card record-hero">
        <Path stages={PATH_STAGES} current={order.status} lostKey="cancelled" />
        <Highlights items={[
          { label: "Order value", value: money(value), hint: `${order.items.length} line(s)` },
          { label: "Received value", value: money(receivedValue),
            hint: value ? `${Math.round((receivedValue / value) * 100)}% of order` : "none" },
          { label: "Outstanding units", value: String(outstanding),
            hint: outstanding ? "still to be delivered" : "fully delivered" },
          // WHAT THE WHOLESALER SAID, ON THE ORDER ITSELF.
          //
          // It was only on the supplier's page, which meant somebody looking
          // at this order had to go via the supplier to find out whether it
          // had even been confirmed. This is the question they opened the
          // order to answer.
          { label: "They said",
            value: order.acknowledged_at
              ? (order.promised_date ? fmtDate(order.promised_date) : "confirmed")
              : order.status === "sent" ? "no answer yet" : "not asked",
            hint: order.acknowledged_at
              ? (order.promised_date
                  ? `confirmed ${fmtDate(order.acknowledged_at)}`
                  : "confirmed, no date given")
              : order.status === "sent"
                ? "send them their portal link"
                : "not sent to them yet",
            tone: order.acknowledged_at ? "ok" : undefined },
          { label: "Status", value: order.status, hint: order.notes || "none" },
        ]} />
        <div className="record-exit">
          {/* THIS NOW SENDS. It used to set a string to "sent" and the order
              never left the building, so an order a wholesaler had received
              and one somebody had clicked a button on looked identical. */}
          {order.status === "draft" && (
            <>
              {/* WHY IT CANNOT GO YET, SAID OUT LOUD.
                  A disabled button that does not explain itself is how a
                  person decides the software is broken and telephones the
                  order through instead — which defeats the control entirely.
                  So Send stays enabled and the server answers with the
                  reason, and the reason is shown as written. */}
              {order.approved_at && (
                <span className="badge ok">
                  Approved {fmtDateTime(order.approved_at)}
                </span>
              )}
              <BusyButton className="small" onClick={sendToSupplier}
                          busyLabel="Sending…">
                Send to supplier
              </BusyButton>
              {!order.approved_at && (
                <BusyButton className="secondary small" onClick={approve}
                            busyLabel="Approving…">
                  Approve it
                </BusyButton>
              )}
              <button type="button" className="btn-link small"
                      onClick={() => void preview()}>
                See what will be sent
              </button>
            </>
          )}
          {order.status === "sent" && (
            <span className="muted">
              {order.sent_at
                ? <>Sent {fmtDateTime(order.sent_at)}
                    {order.sent_to && <> to <b>{order.sent_to}</b></>}. Receive
                    stock from the Procurement list so batch numbers and expiry
                    dates can be captured.</>
                : <>Receive stock from the Procurement list so batch numbers and
                    expiry dates can be captured</>}
            </span>
          )}
          {order.status !== "received" && order.status !== "cancelled" && (
            <BusyButton className="secondary small" onClick={() => setStatus("cancelled")}>Cancel order</BusyButton>
          )}
        </div>
      </div>

      {/* WHAT WILL ACTUALLY BE SENT.
          Nobody should have to send a document to somebody else's order desk
          to find out what it says. It is also the copy a pharmacy that faxes
          or hands orders over can print. */}
      {preview_ !== null && (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal od-preview" onClick={(e) => e.stopPropagation()}>
            <h2>What the supplier will get</h2>
            <pre className="od-doc">{preview_}</pre>
            <div className="modal-foot">
              <button className="btn secondary" onClick={() => setPreview(null)}>
                Close
              </button>
              <button className="btn" onClick={() => window.print()}>Print it</button>
            </div>
          </div>
        </div>
      )}

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
    </RecordPage>
  );
}
