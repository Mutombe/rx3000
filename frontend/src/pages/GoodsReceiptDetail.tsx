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
import { Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import MatchToBill, { Candidate } from "../components/MatchToBill";
import { useAsk } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { useCan } from "../session";

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
  const [matching, setMatching] = useState(false);
  const toast = useToast();
  const ask = useAsk();
  const mayReceive = useCan("stock.receive");

  function reload(rid: number) {
    api.get<Receipt>(`/api/goods-receipts/${rid}`).then(setRow).catch(() => {});
  }

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Receipt>(`/api/goods-receipts/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That delivery could not be loaded.")));
  }, [id]);

  /* THE FACTS AT THE TOP NAME TWO PROBLEMS: "still open" and "unbilled
     goods". Until now the page stated both and did nothing about either, so
     the fix was always back on the list. Both are now decided here. */

  async function sign() {
    if (!row) return;
    const { ok, value } = await ask({
      title: `Sign for ${row.grv_number}`,
      body: <>
        {row.packs.toLocaleString()} pack{row.packs === 1 ? "" : "s"} from{" "}
        {row.supplier || "the supplier"}, {money(row.goods_total)} at cost. The
        goods are already on the shelf; this finishes the paperwork. Enter the
        number on the invoice if it came with the van.
      </>,
      field: "Invoice number",
      placeholder: "leave empty if it follows later",
      maxLength: 40,
      confirmLabel: "Sign for it",
    });
    if (!ok) return;

    const was = { status: row.status, invoice_number: row.invoice_number };
    setRow((r) => r ? { ...r, status: "received",
                        invoice_number: value.trim() || r.invoice_number } : r);
    try {
      const said = await api.post<{ message: string }>(
        `/api/goods-receipts/${row.id}/close`, { invoice_number: value.trim() });
      toast.ok(said.message);
      reload(row.id);
    } catch (e) {
      setRow((r) => r ? { ...r, ...was } : r);
      toast.error(errorText(e, "That delivery could not be signed for."));
    }
  }

  async function putOn(invoice: Candidate | null) {
    if (!row) return;
    const was = row.invoice_number;
    setRow((r) => r ? { ...r, invoice_number: invoice?.invoice_number ?? "" } : r);
    setMatching(false);
    try {
      const said = await api.post<{ message: string }>(
        `/api/goods-receipts/${row.id}/match`, { invoice_id: invoice?.id ?? null });
      toast.ok(said.message);
      reload(row.id);
    } catch (e) {
      setRow((r) => r ? { ...r, invoice_number: was } : r);
      toast.error(errorText(e, "That delivery could not be matched."));
    }
  }

  const damaged = row?.items.filter((i) => i.condition === "damaged") ?? [];
  const good = row?.items.filter((i) => i.condition !== "damaged") ?? [];

  const itemRows = (items: Item[]) => items.map((i, n) => (
    <tr key={`${i.product_id}-${i.batch}-${n}`}>
      <td>
        <EntityLink to={`/products/${i.product_id}`}>{i.product || "unnamed"}</EntityLink>
      </td>
      <td className="mono small">{i.batch || <span className="muted">None</span>}</td>
      <td className="small">
        {/* Said the way every other date in the product is said. It was
            printed straight from the database as 2027-01-10, which is the
            one date format nobody in the pharmacy writes. */}
        {i.expiry ? fmtDate(i.expiry) : <span className="muted">Not given</span>}
      </td>
      <td className="num">{i.quantity}</td>
      <td className="num">{money(i.unit_cost)}</td>
      <td className="num">{money(i.line_total)}</td>
    </tr>
  ));

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "Deliveries", to: "/stock?tab=deliveries" },
              { label: row ? row.grv_number : "This delivery" }]}
      eyebrow="Delivery"
      title={row ? row.grv_number : "Delivery"}
      subtitle={row
        ? `${row.packs} pack(s) over ${row.lines} line(s)`
          + (row.supplier ? ` from ${row.supplier}` : "")
        : undefined}
      loading={!row && !error}
      error={error}
      actions={
        <>
          {row?.status === "open" && mayReceive && (
            <button type="button" className="btn primary" onClick={() => void sign()}>
              Sign for it
            </button>
          )}
          {row?.status === "received" && mayReceive && (
            <button type="button"
                    className={row.invoice_number ? "btn secondary" : "btn primary"}
                    onClick={() => setMatching(true)}>
              {row.invoice_number ? "Change the bill" : "Put it on a bill"}
            </button>
          )}
          {row?.order_id ? (
            <Link to={`/orders/${row.order_id}`} className="btn secondary">
              The order
            </Link>
          ) : null}
          {/* No "back to Deliveries" button here. The breadcrumb already
              renders one from the last linked step in the trail, and with
              the tab now named in that trail it points at the right place.
              Two identical back links in one header is one too many. */}
          {row?.supplier_id ? (
            <Link to={`/suppliers/${row.supplier_id}`} className="btn secondary">
              The supplier
            </Link>
          ) : null}
        </>
      }
      facts={row ? [
        { label: "Goods", value: money(row.goods_total),
          hint: `${row.packs} pack(s)` },
        { label: "Damaged", value: row.damaged,
          hint: row.damaged ? "claim a credit for these" : "None reported",
          tone: row.damaged ? "warn" : undefined },
        { label: "On a bill", value: row.invoice_number || "Not yet",
          hint: row.invoice_number ? "matched" : "Unbilled goods",
          tone: row.invoice_number ? undefined : "warn" },
        { label: "Signed for by", value: row.received_by || "Not recorded",
          hint: row.received_at ? fmtDateTime(row.received_at) : "" },
      ] : []}
    >
      {row && matching && (
        <MatchToBill delivery={row} onClose={() => setMatching(false)}
                     onMatched={(inv) => void putOn(inv)} />
      )}
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
                  : <span className="muted">Not recorded</span>}
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
                {row.delivery_note || <span className="muted">None given</span>}
              </dd>

              <dt>Invoice</dt>
              <dd className="mono">
                {row.invoice_number || <span className="muted">Not billed yet</span>}
              </dd>

              <dt>Received</dt>
              <dd>{row.received_at ? fmtDateTime(row.received_at)
                                   : <span className="muted">Not recorded</span>}</dd>

              <dt>Note</dt>
              <dd>{row.notes || <span className="muted">None</span>}</dd>
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
