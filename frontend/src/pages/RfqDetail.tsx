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
import { ArrowLeft, Check, PaperPlaneTilt, Plus, Prohibit } from "@phosphor-icons/react";

import { api, errorText, fmtDate, fmtDateTime, money , sentence} from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
import InviteSupplier from "./RfqInvite";
import SupplierCard from "./RfqSuppliers";
import { AwaitingApproval, AwardState, WhyNotCheapest, WhyRefused } from "./RfqAward";

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
  opened_at: string | null;
  responded_at: string | null;
  declined: boolean;
  note: string;
  /** True when the wholesaler typed it into their own link. See the note on
   *  provenance below: this is not the same as an empty `recorded_by`. */
  self_quoted: boolean;
  recorded_by: string;
}

/** The status, as a person would say it. The stored values stay as they are;
 *  these are only for reading. */
/** What each stored status is called on screen, in sentence case: these are
 *  read as words on a stat tile, not as the column's own spelling. */
const SAYS_STATUS: Record<string, string> = {
  draft: "Draft",
  sent: "Out for quotation",
  awaiting_approval: "Waiting to be signed off",
  closed: "Orders raised",
  cancelled: "Cancelled",
};

interface Detail {
  id: number;
  reference: string;
  status: string;
  notes: string;
  closes_at: string | null;
  lines: Line[];
  line_count: number;
  suppliers: Invited[];
  waiting_on: string[];
  saving: number;
  asked: number;
  answered: number;
  document: string;
  award: AwardState;
}

export default function RfqDetail() {
  const { id } = useParams();
  const [row, setRow] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  /** Which supplier is chosen for each line, keyed by line. */
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [showDoc, setShowDoc] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [asking, setAsking] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(() => {
    api.get<Detail>(`/api/rfqs/${id}`)
      .then((r) => {
        setRow(r);
        // What was already awarded, so somebody returning to an award that
        // was sent back sees their own choices rather than an empty grid and
        // has to reconstruct them from memory.
        const had = r.award?.chosen ?? {};
        if (Object.keys(had).length) {
          setPicks(Object.fromEntries(
            Object.entries(had).map(([line, who]) => [Number(line), who])));
        }
      })
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

  /** Say who won. The server refuses without a reason when the cheapest
   *  lost, and the dialog below collects it rather than letting the refusal
   *  arrive as an error the buyer has to decode. */
  async function award(reason = "") {
    const chosen = Object.entries(picks).map(([line, supplier]) => ({
      rfq_line_id: Number(line), rfq_supplier_id: supplier,
    }));
    try {
      const said = await api.post<{ message: string }>(
        `/api/rfqs/${id}/award`, { picks: chosen, reason });
      toast.ok(said.message);
      setAsking(false);
      load();
    } catch (e) {
      toast.error(errorText(e, "Those choices could not be awarded."));
    }
  }

  /** Ask for the reason FIRST where one will be needed, rather than letting
   *  the server's refusal be how somebody finds out. */
  function proposeAward() {
    const dearer = dearerLines();
    if (dearer.length > 0) { setAsking(true); return; }
    void award();
  }

  /** Which lines have a chosen supplier that is not the cheapest quoted.
   *  Worked out here as well as on the server so the dialog can be filled in
   *  before anything is posted; the server is still the one that refuses. */
  function dearerLines() {
    if (!row) return [];
    const out = [];
    for (const line of row.lines) {
      const who = picks[line.rfq_line_id];
      if (!who) continue;
      const mine = line.answers.find((a) => a.rfq_supplier_id === who);
      const best = line.answers.find((a) => a.cheapest);
      if (!mine || !best || mine.unit_price === null || best.unit_price === null) continue;
      if (best.rfq_supplier_id === who) continue;
      const extra = Number(((mine.unit_price - best.unit_price) * line.quantity).toFixed(2));
      if (extra <= 0) continue;
      out.push({
        rfq_line_id: line.rfq_line_id, product: line.product,
        chosen: mine.supplier, chosen_price: mine.unit_price,
        chosen_lead_days: mine.lead_days,
        cheapest: best.supplier, cheapest_price: best.unit_price,
        cheapest_lead_days: best.lead_days, extra,
      });
    }
    return out;
  }

  async function approve() {
    try {
      const said = await api.post<{ message: string }>(`/api/rfqs/${id}/approve`);
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That award could not be approved."));
    }
  }

  async function sendBack(reason: string) {
    try {
      const said = await api.post<{ message: string }>(
        `/api/rfqs/${id}/send-back`, { reason });
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That award could not be sent back."));
    }
  }

  async function convert() {
    try {
      const said = await api.post<{ message: string }>(`/api/rfqs/${id}/to-orders`);
      toast.ok(said.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "Those choices could not be turned into orders."));
    }
  }

  /** Abandon the request. Needs confirming because the wholesalers who were
   *  asked are not told, and somebody will ring about it next week. */
  async function cancel() {
    const sure = await confirm({
      title: `Cancel ${row?.reference}?`,
      body: "The suppliers who were asked are not told. Anyone who opens their "
        + "link afterwards finds it closed, so ring the ones whose goodwill "
        + "you want to keep.",
      confirmLabel: "Cancel the request",
      destructive: true,
    });
    if (!sure) return;
    try {
      const done = await api.post<{ message: string }>(`/api/rfqs/${id}/cancel`);
      toast.ok(done.message);
      load();
    } catch (e) {
      toast.error(errorText(e, "That request could not be cancelled."));
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
        <>
          {/* Abandoning is an action on the whole request, so it belongs
              here rather than buried among the per-supplier buttons. */}
          {row && row.status !== "closed" && row.status !== "cancelled" && (
            <button type="button" className="btn secondary" onClick={cancel}>
              <Prohibit size={13} /> Cancel this request
            </button>
          )}
          <Link to="/rfqs" className="btn secondary">
            <ArrowLeft size={13} weight="bold" /> Quotes
          </Link>
        </>
      }
      facts={row ? [
        // READ OFF THE FACTS, NOT OFF THE STATUS.
        //
        // Twice now this line has said something untrue by reasoning from
        // the wrong thing. First "everybody has replied" when nobody had
        // been asked, because `waiting_on` counts suppliers who were SENT
        // and is empty on a draft for the opposite reason. Then "nobody has
        // been asked yet" beside "1 of 1", because a draft can carry an
        // answer: a wholesaler with a link can fill it in, and staff can
        // write down a telephone call, both before the request is sent.
        //
        // So the order below is answered, then outstanding, then nobody
        // invited, then not sent — each one checked against the count it
        // actually describes.
        { label: "Answered", value: `${row.answered} of ${row.asked}`,
          hint: row.asked === 0 ? "nobody has been invited yet"
            : row.waiting_on.length ? `waiting on ${row.waiting_on.join(", ")}`
            : row.answered === row.asked ? "everybody has replied"
            : row.answered ? `${row.asked - row.answered} still to reply`
            : row.status === "draft" ? "nobody has been asked yet"
            : "nobody has replied yet" },
        // In words, not in the database's spelling. "awaiting_approval" on
        // a screen is the software showing somebody its own internals.
        { label: "Status", value: SAYS_STATUS[row.status] ?? sentence(row.status) },
        { label: "Closes", value: row.closes_at ? fmtDate(row.closes_at) : "No date",
          hint: row.closes_at ? "" : "a request with no closing date is never compared" },
        // What asking around was actually worth, which is the case for doing it.
        { label: "Spread", value: money(row.saving),
          hint: "between the dearest and cheapest quoted",
          tone: row.saving > 0 ? "ok" : undefined },
      ] : []}
    >
      {row && (
        <>
          {/* A draft that already carries an answer has plainly been asked
              about, by telephone or by a link sent by hand, so it does not
              get told that nothing has been asked. Same rule as the fact
              above it: read the counts, not the status. */}
          {row.status === "draft" && (
            <div className="alert">
              {row.answered
                ? `Nothing has been emailed yet, though ${row.answered} of `
                  + `${row.asked} have already answered. `
                : "Nothing has been asked yet. "}
              <button type="button" className="btn-link"
                      onClick={() => setShowDoc(true)}>
                See what will be sent
              </button>
            </div>
          )}

          {/* WHO HAS ANSWERED, AND HOW TO CHASE THEM.
              Above the grid rather than in its column headings, because
              chasing a wholesaler is a different job from comparing prices
              and wants room for the two things it needs: their own link, and
              somewhere to type what they said on the telephone. */}
          <Panel title="Who was asked" count={row.suppliers.length}
                 empty="Nobody has been invited to quote."
                 aside={row.status !== "closed" && row.status !== "cancelled" ? (
                   <button type="button" className="btn secondary small"
                           onClick={() => setInviting(true)}>
                     <Plus size={13} weight="bold" /> Ask another supplier
                   </button>
                 ) : undefined}>
            <div className="rfq-who">
              {row.suppliers.map((s) => (
                <SupplierCard key={s.rfq_supplier_id} rfqId={id!} invited={s}
                              lines={row.lines} closed={row.status === "closed"}
                              onRecorded={load} />
              ))}
            </div>
          </Panel>

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
                          {s.declined ? "Cannot supply"
                            : s.responded_at ? `replied ${fmtDate(s.responded_at)}`
                            : s.sent_at ? "asked, no reply yet"
                            : "Not asked"}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {row.lines.map((line) => (
                    <tr key={line.rfq_line_id}>
                      <td title={line.quoted_by > 1 && line.spread > 0
                        ? `${money(line.saving)} between the dearest and the cheapest`
                        : undefined}>
                        <EntityLink to={`/products/${line.product_id}`}>
                          {line.product}
                        </EntityLink>
                        {/* The spread is on the hover rather than under the
                            name. It is the dearest quote less the cheapest,
                            both of which are in the row beside it with the
                            cheapest already marked, and printed on its own
                            line it doubled the height of every row in a table
                            read by comparing across. */}
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
                              <span className="muted">None</span>
                            ) : !a.available ? (
                              <span className="muted small">Cannot supply</span>
                            ) : (
                              <button type="button" className="rfq-pick"
                                      title={`${money(a.line_total ?? 0)} for `
                                             + `${line.quantity}`}
                                      onClick={() => setPicks((p) => ({
                                        ...p, [line.rfq_line_id]: a.rfq_supplier_id }))}
                                      disabled={!buyable || row.status === "closed"}>
                                <b>{money(a.unit_price ?? 0)}</b>
                                {a.lead_days !== null && (
                                  <span className="muted small">{a.lead_days}d</span>
                                )}
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

          {/* WHY THE AWARD IS ITS OWN STEP.
              Asking three wholesalers commits the pharmacy to nothing;
              choosing which one wins commits it to the money. So that is the
              act that carries a name and, over a value the pharmacy sets, a
              second one. */}
          {/* Shown when somebody has ANSWERED, not when the request has been
              sent. A draft carries answers routinely: the nightly job raises
              one, a wholesaler with a link fills it in, or staff write down a
              telephone call. Keying this off the status hid the only button
              that acts on those answers, so a request that had been priced
              could not be awarded at all. Third time reasoning from the
              status rather than the facts has broken this screen. */}
          {row.status !== "closed" && row.status !== "cancelled"
            && row.answered > 0 && (
            <>
              <WhyRefused award={row.award} />

              {row.status === "awaiting_approval" ? (
                <AwaitingApproval award={row.award} onApprove={approve}
                                  onSendBack={sendBack} />
              ) : (
                <div className="card rfq-foot">
                  <div>
                    <b>{chosenCount} of {row.lines.length} line(s) chosen</b>
                    {chosenCount > 0 && (
                      <span className="muted"> · {money(chosenValue)}</span>
                    )}
                    <div className="muted small">
                      {/* Said before the click, not after it. A person who
                          discovers the approval step at the moment they try
                          to raise the orders is the wrong person to discover
                          it and it is the worst time. */}
                      {row.award.approved
                        ? "Approved. This raises draft orders, grouped by "
                          + "supplier. Nothing is sent until you send it."
                        : row.award.approval_used
                          ? `Awards over ${money(row.award.threshold)} need a `
                            + "second person to sign them off. Whoever chooses "
                            + "cannot approve their own choice."
                          : "This raises draft orders, grouped by supplier. "
                            + "Nothing is sent until you send it."}
                    </div>
                  </div>
                  {row.award.approved || !row.award.approval_used ? (
                    <div className="rfq-foot-acts">
                      {/* Re-awarding stays available so a choice can be
                          changed before the orders are raised. */}
                      <button type="button" className="btn secondary"
                              onClick={proposeAward} disabled={chosenCount === 0}>
                        Change the award
                      </button>
                      <BusyButton className="btn primary" onClick={convert}
                                  disabled={chosenCount === 0} busyLabel="Raising…">
                        Raise the orders
                      </BusyButton>
                    </div>
                  ) : (
                    <BusyButton className="btn primary" onClick={proposeAward}
                                disabled={chosenCount === 0} busyLabel="Awarding…">
                      Award these suppliers
                    </BusyButton>
                  )}
                </div>
              )}
            </>
          )}

          {asking && (
            <WhyNotCheapest dearer={dearerLines()}
                            onClose={() => setAsking(false)}
                            onSaid={award} />
          )}

          {inviting && (
            <InviteSupplier rfqId={id!} already={row.suppliers.map((s) => s.supplier_id)}
                            onClose={() => setInviting(false)}
                            onInvited={() => { setInviting(false); load(); }} />
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
