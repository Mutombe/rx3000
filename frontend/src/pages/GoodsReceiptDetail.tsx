/** One delivery, as a document.
 *
 *  The goods receipt is what was missing between the order and the invoice.
 *  Stock used to arrive stamped with the ORDER number, so two vans a week
 *  apart against one order were indistinguishable afterwards: no delivery
 *  note, no date, nobody's name on it.
 *
 *  The endpoint that returns one has existed since the document was built and
 *  nothing called it. The Deliveries tab listed them and there was nowhere to
 *  go — which means the one question a delivery is ever asked, "what actually
 *  came off that van and who signed for it", had no answer on a screen.
 *
 *  Damaged lines lead, because they are the reason anybody opens this in a
 *  hurry: they are what a credit claim is built from, and a wholesaler will
 *  refuse one that cannot quote the delivery note and the date.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";

interface Item {
  product_id: number;
  product: string;
  batch_id: number | null;
  batch: string;
  expiry: string;
  quantity: number;
  unit_cost: number;
  line_total: number;
  condition: string;
}

interface Receipt {
  id: number;
  grv_number: string;
  status: string;
  supplier_id: number | null;
  supplier: string;
  order_id: number | null;
  order_number: string;
  delivery_note: string;
  invoice_number: string;
  invoice_id: number | null;
  goods_total: number;
  notes: string;
  received_by: string;
  received_at: string;
  lines: number;
  packs: number;
  damaged: number;
  items: Item[];
}

export default function GoodsReceiptDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Receipt | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Receipt>(`/api/goods-receipts/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That delivery could not be loaded.")));
  }, [id]);

  const damaged = row?.items.filter((i) => i.condition === "damaged") ?? [];
  const good = row?.items.filter((i) => i.condition !== "damaged") ?? [];

  const itemRows = (items: Item[]) => items.map((i, n) => (
    <tr key={`${i.product_id}-${i.batch}-${n}`}>
      <td>
        <EntityLink to={`/products/${i.product_id}`}>{i.product || "—"}</EntityLink>
      </td>
      <td className="mono small">{i.batch || <span className="muted">none</span>}</td>
      <td className="small">{i.expiry || <span className="muted">not given</span>}</td>
      <td className="num">{i.quantity}</td>
      <td className="num">{money(i.unit_cost)}</td>
      <td className="num">{money(i.line_total)}</td>
    </tr>
  ));

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "This delivery" }]}
      eyebrow="Delivery"
      title={row ? row.grv_number : "Delivery"}
      subtitle={row
        ? `${row.packs} pack(s) over ${row.lines} line(s)`
          + (row.supplier ? ` from ${row.supplier}` : "")
        : undefined}
      loading={!row && !error}
      error={error}
      actions={
        <Link to="/stock" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Deliveries
        </Link>
      }
      facts={row ? [
        { label: "Goods", value: money(row.goods_total),
          hint: `${row.packs} pack(s)` },
        { label: "Damaged", value: row.damaged,
          hint: row.damaged ? "claim a credit for these" : "none reported",
          tone: row.damaged ? "warn" : undefined },
        { label: "On a bill", value: row.invoice_number || "not yet",
          hint: row.invoice_number ? "matched" : "unbilled goods",
          tone: row.invoice_number ? undefined : "warn" },
        { label: "Signed for by", value: row.received_by || "not recorded",
          hint: row.received_at ? fmtDateTime(row.received_at) : "" },
      ] : []}
    >
      {row && (
        <>
          {row.status === "open" && (
            <div className="alert warn">
              <Warning size={15} weight="fill" /> This delivery is still open.
              Somebody is scanning it, or it was never signed for.
            </div>
          )}

          <Panel title="The paperwork">
            <dl className="kv">
              <dt>Supplier</dt>
              <dd>
                {row.supplier_id
                  ? <EntityLink to={`/suppliers/${row.supplier_id}`}>{row.supplier}</EntityLink>
                  : <span className="muted">not recorded</span>}
              </dd>

              <dt>Against order</dt>
              <dd>
                {row.order_id
                  ? <EntityLink to={`/orders/${row.order_id}`}>
                      {row.order_number || `#${row.order_id}`}
                    </EntityLink>
                  : <span className="muted">none, booked in without an order</span>}
              </dd>

              <dt>Delivery note</dt>
              <dd className="mono">
                {row.delivery_note || <span className="muted">none given</span>}
              </dd>

              <dt>Invoice</dt>
              <dd className="mono">
                {row.invoice_number || <span className="muted">not billed yet</span>}
              </dd>

              <dt>Received</dt>
              <dd>{row.received_at ? fmtDateTime(row.received_at)
                                   : <span className="muted">not recorded</span>}</dd>

              <dt>Note</dt>
              <dd>{row.notes || <span className="muted">none</span>}</dd>
            </dl>
          </Panel>

          {/* Damaged first: it is what a credit claim is built from, and the
              reason anybody opens a delivery in a hurry. */}
          {damaged.length > 0 && (
            <Panel title="Arrived damaged" count={damaged.length}>
              <div className="table-wrap">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Medicine</th><th>Batch</th><th>Expiry</th>
                      <th className="num">Packs</th>
                      <th className="num">Unit cost</th>
                      <th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>{itemRows(damaged)}</tbody>
                </table>
              </div>
            </Panel>
          )}

          <Panel
            title="What came off the van"
            count={good.length}
            empty="Nothing was booked in against this delivery."
          >
            <div className="table-wrap">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Medicine</th><th>Batch</th><th>Expiry</th>
                    <th className="num">Packs</th>
                    <th className="num">Unit cost</th>
                    <th className="num">Value</th>
                  </tr>
                </thead>
                <tbody>{itemRows(good)}</tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
