/** One request for quotation: what was asked, who answered, and what to buy.
 *
 *  THE GRID IS THE POINT
 *
 *  Lines down, wholesalers across. A buyer comparing three quotes on paper
 *  draws exactly this, and the reason is that the interesting comparison is
 *  across a row — one medicine, three prices — while the interesting decision
 *  is per row too, because the cheapest supplier for one line is routinely
 *  not the cheapest for the next.
 *
 *  THREE STATES, NOT TWO
 *
 *  A supplier who has not answered, one who answered "we cannot supply it",
 *  and one quoting a price are three different facts. Flattening the first
 *  two into a blank makes silence look like a refusal and a refusal look like
 *  an oversight, and either way the grid recommends the wrong wholesaler.
 *
 *  NOTHING IS CHOSEN FOR YOU
 *
 *  The cheapest price on each line is marked and that is all. A quote three
 *  weeks out is no use for a line that is out of stock today, and a supplier
 *  who short-delivers every order is not a bargain at any price. The lead
 *  time sits beside the price so the person deciding can see both.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, PaperPlaneTilt } from "@phosphor-icons/react";

import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useToast } from "../components/Toast";

interface Answer {
  rfq_supplier_id: number;
  supplier: string;
  answered: boolean;
  available: boolean | null;
  unit_price: number | null;
  line_total: number | null;
  lead_days: number | null;
  note: string;
  cheapest: boolean;
}

interface Line {
  rfq_line_id: number;
  product_id: number;
  product: string;
  quantity: number;
  answers: Answer[];
  quoted_by: number;
  spread: number;
  saving: number;
}

interface Invited {
  rfq_supplier_id: number;
  supplier_id: number;
  supplier: string;
  sent_at: string | null;
  responded_at: string | null;
  declined: boolean;
  note: string;
}

interface Detail {
  id: number;
  reference: string;
  status: string;
  notes: string;
  closes_at: string | null;
  lines: Line[];
  suppliers: Invited[];
  waiting_on: string[];
  saving: number;
  asked: number;
  answered: number;
  document: string;
}

export default function RfqDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  /** Which supplier is chosen for each line, keyed by line. */
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [showDoc, setShowDoc] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    api.get<Detail>(`/api/rfqs/${id}`)
      .then(setRow)
      .catch((e) => setError(errorText(e, "That request could not be loaded.")));
  }, [id]);
  useEffect(load, [load]);

  async function send() {
    try {
      const said = await api.post<{ message: string }>(`/api/rfqs/${id}/send`);
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That request could not be sent."));
    }
  }

  async function convert() {
    const chosen = Object.entries(picks).map(([line, supplier]) => ({
      rfq_line_id: Number(line), rfq_supplier_id: supplier,
    }));
    try {
      const said = await api.post<{ message: string }>(
        `/api/rfqs/${id}/to-orders`, { picks: chosen });
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "Those choices could not be turned into orders."));
    }
  }

  /** Take the cheapest on every line that was quoted. A starting point, not
   *  a decision: every pick stays changeable afterwards. */
  function takeCheapest() {
    if (!row) return;
    const next: Record<number, number> = {};
    for (const line of row.lines) {
      const best = line.answers.find((a) => a.cheapest);
      if (best) next[line.rfq_line_id] = best.rfq_supplier_id;
    }
    setPicks(next);
  }

  const chosenCount = Object.keys(picks).length;
  const chosenValue = row
    ? row.lines.reduce((sum, line) => {
        const who = picks[line.rfq_line_id];
        const ans = line.answers.find((a) => a.rfq_supplier_id === who);
        return sum + (ans?.line_total ?? 0);
      }, 0)
    : 0;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Quotes", to: "/rfqs" },
              { label: "This request" }]}
      eyebrow="Request for quotation"
      title={row ? row.reference : "Request"}
      subtitle={row
        ? `${row.lines.length} line(s) asked of ${row.asked} supplier(s)`
        : undefined}
      loading={!row && !error}
      error={error}
      actions={
        <Link to="/rfqs" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Quotes
        </Link>
      }
      facts={row ? [
        // "Everybody has replied" was said when nobody had been asked:
        // `waiting_on` counts suppliers who were SENT and have not answered,
        // and on a draft that list is empty for the opposite reason.
        { label: "Answered", value: `${row.answered} of ${row.asked}`,
          hint: row.status === "draft" ? "nobody has been asked yet"
            : row.waiting_on.length ? `waiting on ${row.waiting_on.join(", ")}`
            : row.answered ? "everybody has replied"
            : "nobody has replied yet" },
        { label: "Status", value: row.status },
        { label: "Closes", value: row.closes_at ? fmtDate(row.closes_at) : "no date",
          hint: row.closes_at ? "" : "a request with no closing date is never compared" },
        // What asking around was actually worth, which is the case for doing it.
        { label: "Spread", value: money(row.saving),
          hint: "between the dearest and cheapest quoted",
          tone: row.saving > 0 ? "ok" : undefined },
      ] : []}
    >
      {row && (
        <>
          {row.status === "draft" && (
            <div className="alert">
              Nothing has been asked yet.{" "}
              <button type="button" className="btn-link"
                      onClick={() => setShowDoc(true)}>
                See what will be sent
              </button>
            </div>
          )}

          <Panel
            title="What each wholesaler said"
            count={row.lines.length}
            empty="Nothing is on this request."
            aside={
              row.status === "draft"
                ? <BusyButton className="btn small" onClick={send} busyLabel="Sending…">
                    <PaperPlaneTilt size={14} /> Send the request
                  </BusyButton>
                : <button type="button" className="btn secondary small"
                          onClick={takeCheapest}>
                    Take the cheapest of each
                  </button>
            }
          >
            <div className="table-wrap">
              <table className="dt rfq-grid">
                <thead>
                  <tr>
                    <th>Medicine</th>
                    <th className="num">Wanted</th>
                    {row.suppliers.map((s) => (
                      <th key={s.rfq_supplier_id} className="num">
                        {s.supplier}
                        <div className="muted small">
                          {s.declined ? "cannot supply"
                            : s.responded_at ? `replied ${fmtDate(s.responded_at)}`
                            : s.sent_at ? "asked, no reply yet"
                            : "not asked"}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {row.lines.map((line) => (
                    <tr key={line.rfq_line_id}>
                      <td>
                        <EntityLink to={`/products/${line.product_id}`}>
                          {line.product}
                        </EntityLink>
                        {line.quoted_by > 1 && line.spread > 0 && (
                          <div className="muted small">
                            {money(line.saving)} between dearest and cheapest
                          </div>
                        )}
                      </td>
                      <td className="num">{line.quantity}</td>
                      {line.answers.map((a) => {
                        const picked = picks[line.rfq_line_id] === a.rfq_supplier_id;
                        const buyable = a.answered && a.available && a.unit_price !== null;
                        return (
                          <td key={a.rfq_supplier_id}
                              className={"num rfq-cell"
                                + (a.cheapest ? " is-cheapest" : "")
                                + (picked ? " is-picked" : "")}>
                            {/* Three states kept apart. See the note at the
                                top of this file. */}
                            {!a.answered ? (
                              <span className="muted">—</span>
                            ) : !a.available ? (
                              <span className="muted small">cannot supply</span>
                            ) : (
                              <button type="button" className="rfq-pick"
                                      onClick={() => setPicks((p) => ({
                                        ...p, [line.rfq_line_id]: a.rfq_supplier_id }))}
                                      disabled={!buyable || row.status === "closed"}>
                                <b>{money(a.unit_price ?? 0)}</b>
                                <span className="muted small">
                                  {money(a.line_total ?? 0)}
                                  {a.lead_days !== null && ` · ${a.lead_days}d`}
                                </span>
                                {picked && <Check size={13} weight="bold" />}
                              </button>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* Draft orders, never sent. Choosing a quote is a buying decision;
              sending the order is a separate one, and may need a second
              signature first. */}
          {row.status !== "closed" && row.status !== "draft" && (
            <div className="card rfq-foot">
              <div>
                <b>{chosenCount} of {row.lines.length} line(s) chosen</b>
                {chosenCount > 0 && (
                  <span className="muted"> · {money(chosenValue)}</span>
                )}
                <div className="muted small">
                  This raises draft orders, grouped by supplier. Nothing is
                  sent until you send it.
                </div>
              </div>
              <BusyButton className="btn primary" onClick={convert}
                          disabled={chosenCount === 0} busyLabel="Raising…">
                Raise the orders
              </BusyButton>
            </div>
          )}

          {showDoc && (
            <div className="modal-backdrop" onClick={() => setShowDoc(false)}>
              <div className="modal od-preview" onClick={(e) => e.stopPropagation()}>
                <h2>What each wholesaler will get</h2>
                <pre className="od-doc">{row.document}</pre>
                <div className="modal-foot">
                  <button className="btn secondary" onClick={() => setShowDoc(false)}>
                    Close
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </RecordPage>
  );
}
