/** One return to the wholesaler, and whether the credit ever arrived.
 *
 *  A return is a claim for money. The goods went back, and until a credit note
 *  comes the pharmacy has paid for stock it does not have — which is why the
 *  screen leads on what is owed rather than on what was sent.
 *
 *  The endpoint that returns one has existed since returns were built and
 *  nothing called it, so a return could be raised and listed and never opened.
 *  The line that matters most is the one naming the DELIVERY the goods came
 *  off: a credit claim that can quote the delivery note and the date is one a
 *  wholesaler settles, and one that cannot is one they argue about.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Figure, GhostRows } from "../components/Skeleton";
import { useAsk } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { useCan } from "../session";
import Th from "../components/Th";

/** The delivery a returned line came off.
 *
 *  An object, not a string: it carries the delivery note and the date as well
 *  as the number, which is exactly what a wholesaler wants quoted before they
 *  will settle a credit. Typed as a string first, and React refused to render
 *  it — which was the right failure, loudly, rather than printing
 *  "[object Object]" on a claim document.
 */
interface CameOff {
  id: number;
  grv_number: string;
  delivery_note: string;
  received_at: string;
}

interface Line {
  product_id: number;
  product: string;
  batch: string;
  grv: CameOff | null;
  expiry: string;
  quantity: number;
  unit_cost: number;
  line_total: number;
}

interface Return {
  id: number;
  reference: string;
  supplier_id: number | null;
  supplier: string;
  status: string;
  why: string;
  reason_code: string;
  notes: string;
  total: number;
  credit_note: string;
  credited_at: string;
  raised_by: string;
  approved_by: string;
  approved_at: string;
  created_at: string;
  lines: Line[];
}

export default function SupplierReturnDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Return | null>(null);
  const [error, setError] = useState("");
  const toast = useToast();
  const ask = useAsk();
  const mayApprove = useCan("stock.write_off");
  const mayRaise = useCan("stock.adjust");

  useEffect(() => {
    setRow(null);
    setError("");
    api.get<Return>(`/api/supplier-returns/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That return could not be loaded.")));
  }, [id]);

  const credited = Boolean(row?.credit_note);

  /* THE PAGE THAT NAMES THE PROBLEM IS THE PAGE THAT FIXES IT.
     This screen said "$423.60 has gone back and nothing has come for it" and
     offered no way to record the credit when it did: somebody had to read it
     here, go back to the list and find the row again. The same three
     decisions the list offers are offered here, on the record itself. */

  /** Move the badge before the server has agreed. The refusal is real and
   *  handled: approving re-checks the stock is still there, and it may not be. */
  function stand(status: string, extra: Partial<Return> = {}) {
    setRow((r) => r ? { ...r, status, ...extra } : r);
  }

  async function act(what: "approve" | "cancel", label: string) {
    if (!row) return;
    const was = row.status;
    stand(what === "approve" ? "approved" : "cancelled");
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${row.id}/${what}`, {});
      toast.ok(said.message);
      // Deliberately silent: the write has succeeded and `stand()` has already
      // put the right status on the screen. This only refreshes what the
      // server derived, and a failure here changes nothing the reader can see.
      api.get<Return>(`/api/supplier-returns/${row.id}`).then(setRow).catch(() => {});
    } catch (e) {
      stand(was);
      toast.error(errorText(e, `That return could not be ${label}.`));
    }
  }

  async function credit() {
    if (!row) return;
    const { ok, value } = await ask({
      title: `Credit note for ${row.reference}`,
      body: <>Enter the number {row.supplier || "the supplier"} put on the
            credit. {money(row.total)} stops being owed once this is
            recorded.</>,
      field: "Credit note number",
      placeholder: "as it appears on the supplier's document",
      required: true,
      maxLength: 40,
      confirmLabel: "Record the credit",
    });
    if (!ok || !value.trim()) return;

    const was = { status: row.status, credit_note: row.credit_note };
    stand("credited", { credit_note: value.trim() });
    try {
      const said = await api.post<{ message: string }>(
        `/api/supplier-returns/${row.id}/credit`, { credit_note: value.trim() });
      toast.ok(said.message);
      // Deliberately silent, for the same reason as the approval above: the
      // credit is recorded and shown, and this is the server's own view of it
      // arriving afterwards.
      api.get<Return>(`/api/supplier-returns/${row.id}`).then(setRow).catch(() => {});
    } catch (e) {
      stand(was.status, { credit_note: was.credit_note });
      toast.error(errorText(e, "That credit could not be recorded."));
    }
  }

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "Supplier returns", to: "/stock?tab=returns" },
              { label: row ? row.reference : "This return" }]}
      eyebrow="Return to supplier"
      title={row ? row.reference : "Return"}
      subtitle={row
        ? `${row.lines.length} line(s)`
          + (row.supplier ? ` back to ${row.supplier}` : "")
        : undefined}
      loading={!row && !error}
      error={error}
      actions={
        <>
          {/* Led by the decision this return is actually waiting on, so the
              one thing to do is the first thing in reach. */}
          {row?.status === "raised" && mayApprove && (
            <button type="button" className="btn primary"
                    onClick={() => void act("approve", "approved")}>
              Approve, the goods leave
            </button>
          )}
          {row?.status === "approved" && !credited && mayRaise && (
            <button type="button" className="btn primary" onClick={() => void credit()}>
              Credit received
            </button>
          )}
          {row?.status === "raised" && mayRaise && (
            <button type="button" className="btn secondary"
                    onClick={() => void act("cancel", "cancelled")}>
              Call it off
            </button>
          )}
          {/* The breadcrumb renders the back link from the trail. */}
          {row?.supplier_id ? (
            <Link to={`/suppliers/${row.supplier_id}`} className="btn secondary">
              The supplier
            </Link>
          ) : null}
        </>
      }
      facts={[
        /* What went back, whether it was credited, why and where it stands: the
           same four questions for every return, so the words come up with the
           page. The colour on the credit tile waits for the answer, because an
           unread return is neither settled nor owed. */
        { label: "Value",
          value: <Figure ready={!!row} w="9ch">{row && money(row.total)}</Figure>,
          hint: "at what it cost" },
        { label: "Credit",
          value: <Figure ready={!!row} w="12ch">
            {row && (credited ? row.credit_note : "Not received")}
          </Figure>,
          hint: <Figure ready={!!row} w="20ch">
            {row && (credited
              ? (row.credited_at ? fmtDate(row.credited_at) : "on file")
              : "the pharmacy is out of pocket")}
          </Figure>,
          tone: row ? (credited ? "ok" : "warn") : undefined },
        { label: "Why",
          value: <Figure ready={!!row} w="14ch">
            {row && (row.why || row.reason_code || "Not given")}
          </Figure> },
        { label: "Status",
          value: <Figure ready={!!row} w="10ch">{row?.status}</Figure> },
      ]}
    >
      {/* THE WHOLE POINT OF THE SCREEN.
          Goods have gone back and nothing has come for them, so the
          pharmacy has paid for stock it does not have. That is money
          somebody has to chase, and it was not said anywhere.

          It stays behind the fetch, because a page that has not been told
          anything cannot accuse a wholesaler of owing money. */}
      {row && !credited && (
        <div className="alert warn">
          <Warning size={15} weight="fill" /> No credit note against this
          return yet. {money(row.total)} of goods have gone back to{" "}
          {row.supplier || "the supplier"} and nothing has come for them.
        </div>
      )}

      {/* The two headings, the six labels of the claim and the seven column
          heads say what a credit claim is made of, which does not change from
          one return to the next. Gated, the page showed a reference and then
          nothing until the whole return arrived; now the claim form stands
          still and its answers fill in. */}
      <Panel title="The claim">
        <dl className="kv">
          <dt>Supplier</dt>
          <dd>
            <Figure ready={!!row} w="20ch">
              {row && (row.supplier_id
                ? <EntityLink to={`/suppliers/${row.supplier_id}`}>{row.supplier}</EntityLink>
                : <span className="muted">Not recorded</span>)}
            </Figure>
          </dd>

          <dt>Reason</dt>
          <dd>
            <Figure ready={!!row} w="16ch">
              {row && (row.why
                ? <span className="badge">{row.why}</span>
                : <span className="muted">None given</span>)}
            </Figure>
          </dd>

          <dt>Raised</dt>
          <dd>
            <Figure ready={!!row} w="22ch">
              {row && (
                <>
                  {row.created_at ? fmtDateTime(row.created_at)
                                  : <span className="muted">Not recorded</span>}
                  {row.raised_by && <span className="muted"> by {row.raised_by}</span>}
                </>
              )}
            </Figure>
          </dd>

          <dt>Approved</dt>
          <dd>
            <Figure ready={!!row} w="22ch">
              {row && (row.approved_by
                ? <>{row.approved_by}
                    {row.approved_at && <span className="muted"> · {fmtDateTime(row.approved_at)}</span>}</>
                : <span className="muted">Not approved yet</span>)}
            </Figure>
          </dd>

          <dt>Credit note</dt>
          <dd className="mono">
            <Figure ready={!!row} w="14ch">
              {row && (row.credit_note || <span className="muted">None received</span>)}
            </Figure>
          </dd>

          <dt>Note</dt>
          <dd>
            <Figure ready={!!row} w="30ch">
              {row && (row.notes || <span className="muted">None</span>)}
            </Figure>
          </dd>
        </dl>
      </Panel>

      <Panel
        title="What went back"
        count={row?.lines.length}
        /* Only sayable once the lines have been counted. */
        empty={row ? "Nothing is on this return." : undefined}
      >
        <div className="table-wrap">
          <table className="dt">
            <thead>
              <tr>
                <Th>Medicine</Th><Th>Batch</Th><Th>Expiry</Th>
                {/* The delivery it came off, which is what makes the
                    claim one a wholesaler settles rather than argues. */}
                <Th>Came off</Th>
                <Th className="num">Packs</Th>
                <Th className="num">Unit cost</Th>
                <Th className="num">Value</Th>
              </tr>
            </thead>
            {!row ? (
              <GhostRows cols={7} rows={3} secondLine={[3]}
                         widths={["80%", "55%", "50%", "60%", "30%", "40%", "40%"]} />
            ) : (
              <tbody>
                {row.lines.map((l, n) => (
                  <tr key={`${l.product_id}-${l.batch}-${n}`}>
                    <td>
                      <EntityLink to={`/products/${l.product_id}`}>
                        {l.product || "none"}
                      </EntityLink>
                    </td>
                    <td className="mono small">
                      {l.batch || <span className="muted">None</span>}
                    </td>
                    <td className="small">
                      {l.expiry ? fmtDate(l.expiry) : <span className="muted">No expiry</span>}
                    </td>
                    <td className="mono small">
                      {/* An absent delivery arrives as an empty object, not
                          as null, so a plain truth test passed and the link
                          rendered as /deliveries/undefined. It is the id
                          that decides whether there is one. */}
                      {l.grv?.id
                        ? <>
                            <EntityLink to={`/deliveries/${l.grv.id}`}>
                              {l.grv.grv_number}
                            </EntityLink>
                            {l.grv.delivery_note && (
                              <div className="muted">
                                note {l.grv.delivery_note}
                              </div>
                            )}
                          </>
                        : <span className="muted">Not linked</span>}
                    </td>
                    <td className="num">{l.quantity}</td>
                    <td className="num">{money(l.unit_cost)}</td>
                    <td className="num">{money(l.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            )}
          </table>
        </div>
      </Panel>
    </RecordPage>
  );
}
