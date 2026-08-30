/** One supplier invoice, and whether it agrees with what arrived.
 *
 *  The match already existed but only inside a panel on the supplier accounts
 *  screen, which meant an invoice could be reached from exactly one place. An
 *  invoice number is written on a delivery note, a remittance and a statement;
 *  it should open from all of them.
 */
import { useEffect, useState } from "react";
import { CheckCircle, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { useConfirm } from "../components/Confirm";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useToast } from "../components/Toast";
import { useParams } from "react-router-dom";

interface MatchLine {
  description: string; billed_quantity: number; received_quantity: number;
  billed_unit_cost: number; ordered_unit_cost: number; issues: string[];
}
interface MatchResult {
  depth: "lines" | "totals" | "none"; matched: boolean;
  ordered: number; received: number; billed: number; variance: number;
  lines: MatchLine[]; problems: string[];
}
interface Data {
  id: number; invoice_number: string; supplier: string; supplier_id: number;
  order_id: number | null; order_number: string;
  invoice_date: string; due_date: string | null;
  total: number; status: string; posted_reference: string;
  paid: number; outstanding: number; query_note: string;
  items: { id: number; product_id: number | null; description: string;
           quantity: number; unit_cost: number; line_total: number }[];
  match?: MatchResult;
}

const DEPTH_SAYS: Record<string, string> = {
  lines: "Matched line by line against what was received.",
  totals: "Only the total was keyed, so this compares totals. A short delivery and an overcharge of the same size would cancel out and pass.",
  none: "No order is linked, so there is nothing to check this against.",
};

export default function InvoiceDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const toast = useToast();
  const confirm = useConfirm();

  function load() {
    api.get<Data>(`/api/payables/invoices/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That invoice could not be opened.")));
  }
  useEffect(() => { setD(null); load(); }, [id]);

  async function approve() {
    if (!d) return;
    const m = d.match;
    const ok = await confirm({
      title: "Approve for payment?",
      body: (
        <>
          {m && !m.matched
            ? <>This invoice did not match cleanly. Approving it accepts the
                difference of <b>{money(m.variance)}</b> as correct.</>
            : <>This brings the creditor to what the supplier billed.</>}
          {" "}Only the difference against the goods receipt is posted, so
          approving twice does nothing.
        </>
      ),
      confirmLabel: "Approve it",
    });
    if (!ok) return;
    try {
      const r = await api.post<{ message: string }>(
        `/api/payables/invoices/${d.id}/approve`, {});
      toast.ok(r.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be approved."));
    }
  }

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Creditors", to: "/payables" },
              { label: d?.invoice_number ?? "This invoice" }]}
      eyebrow="Supplier invoice"
      title={d?.invoice_number ?? ""}
      subtitle={d && <EntityLink kind="supplier" id={d.supplier_id}>{d.supplier}</EntityLink>}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Billed", value: money(d.total) },
        { label: "Outstanding",
          value: d.outstanding > 0.005 ? money(d.outstanding) : "settled" },
        { label: "Due", value: d.due_date ? fmtDate(d.due_date) : "—" },
        { label: "Status", value: d.status },
      ] : undefined}
      actions={d && !d.posted_reference
        ? <BusyButton onClick={approve}>Approve for payment</BusyButton>
        : undefined}
    >
      {d && (
        <>
          {d.status === "queried" && d.query_note && (
            <div className="alert warn"><b>Queried</b> — {d.query_note}</div>
          )}

          {d.match && (
            <>
              <p className={d.match.matched ? "muted" : ""}>
                {d.match.matched
                  ? <><CheckCircle size={14} weight="fill" /> It matches what was received.</>
                  : <b>This invoice does not match what was received.</b>}
                {" "}{DEPTH_SAYS[d.match.depth]}
              </p>

              {d.match.problems.length > 0 && (
                <div className="alert warn">
                  <Warning size={16} weight="fill" />
                  <ul>{d.match.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
                </div>
              )}

              <Panel title="Ordered, received, billed">
                <dl className="kv">
                  <dt>Order</dt>
                  <dd className="mono">
                    <EntityLink kind="order" id={d.order_id}>
                      {d.order_number || "not linked"}
                    </EntityLink>
                  </dd>
                  <dt>Ordered</dt><dd className="num">{money(d.match.ordered)}</dd>
                  <dt>Received</dt><dd className="num">{money(d.match.received)}</dd>
                  <dt>Billed</dt><dd className="num">{money(d.match.billed)}</dd>
                  <dt>Difference</dt>
                  <dd className="num">
                    {d.match.variance >= 0 ? money(d.match.variance)
                      : `(${money(Math.abs(d.match.variance))})`}
                    <div className="muted small">
                      Approving posts this difference alone. The goods receipt
                      already raised the rest.
                    </div>
                  </dd>
                  <dt>Posted as</dt>
                  <dd className="mono">
                    {d.posted_reference || <span className="muted">not yet posted</span>}
                  </dd>
                </dl>
              </Panel>
            </>
          )}

          <Panel title="Lines billed" count={d.items.length}
                 empty="Only the invoice total was keyed, so there are no lines to show.">
            <table className="dt">
              <thead>
                <tr>
                  <th>Line</th><th className="num">Qty</th>
                  <th className="num">Unit</th><th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {d.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <EntityLink kind="product" id={i.product_id}>
                        {i.description || `#${i.product_id}`}
                      </EntityLink>
                    </td>
                    <td className="num">{i.quantity}</td>
                    <td className="num">{money(i.unit_cost)}</td>
                    <td className="num">{money(i.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
