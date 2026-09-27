/** Requests for quotation: ask around before you buy.
 *
 *  A purchase order names one supplier and a price somebody typed in. Where
 *  that price came from was a telephone call, remembered. This is the record
 *  of having asked three wholesalers, what each said, and why the one that
 *  was chosen won — which is what an owner asks about afterwards.
 *
 *  The list leads on who has not answered yet, because that is the only thing
 *  on this screen anybody can act on: a request nobody has replied to needs
 *  chasing, and one everybody has replied to needs deciding.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Robot } from "@phosphor-icons/react";

import { api, errorText, fmtDate, money , sentence} from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Product } from "../types";
import RfqAuto from "./RfqAuto";
import PageHead from "../components/PageHead";
import Th from "../components/Th";

interface RfqRow {
  id: number;
  reference: string;
  status: string;
  notes: string;
  closes_at: string | null;
  created_at: string;
  line_count: number;
  asked: number;
  answered: number;
  waiting_on: number;
  /** Raised by the nightly job rather than by a person. Shown, because a
   *  draft nobody remembers creating is a draft nobody trusts. */
  raised_automatically: boolean;
}

/** The status in words rather than in the database's spelling. */
/** What each stored status is called on screen. Sentence case, because these
 *  are read as words in a badge rather than as the column's own spelling. */
const SAYS_STATUS: Record<string, string> = {
  draft: "Draft",
  sent: "Out for quotation",
  awaiting_approval: "Waiting to be signed off",
  closed: "Orders raised",
  cancelled: "Cancelled",
};

interface Awaiting {
  id: number;
  reference: string;
  value: number;
  awarded_by: string;
  awarded_at: string;
  award_reason: string;
  dearer_lines: number;
}

interface SupplierLite { id: number; name: string; email: string }

export default function Rfqs() {
  const toast = useToast();
  const [rows, setRows] = useState<RfqRow[] | null>(null);
  const [raising, setRaising] = useState(false);
  const [auto, setAuto] = useState(false);
  const [queue, setQueue] = useState<Awaiting[]>([]);
  const [queueUnknown, setQueueUnknown] = useState(false);

  const load = useCallback(() => {
    api.get<{ rfqs: RfqRow[] }>("/api/rfqs")
      .then((r) => setRows(r.rfqs))
      .catch((e) => toast.error(errorText(e, "Requests could not be loaded.")));
  }, [toast]);
  useEffect(load, [load]);

  // WHY THIS IS A QUEUE AND NOT A BADGE ON A ROW.
  //
  // Without somewhere to look, an approval step is a thing that happens to
  // somebody at the moment they try to raise the orders: the worst time to
  // discover it and the wrong person to discover it. The manager who can
  // sign it off is not the person standing at that screen.
  useEffect(() => {
    api.get<{ rfqs: Awaiting[] }>("/api/rfqs/awaiting-approval")
      .then((r) => setQueue(r.rfqs))
      // Still no toast: a screen somebody opened for something else should not
      // shout. But the banner cannot simply vanish, because its absence is how
      // this screen says "nothing is waiting", and that was a lie.
      .catch(() => { setQueue([]); setQueueUnknown(true); });
  }, []);

  /** Send the request, which is also how it is chased.
   *
   *  The endpoint emails everybody invited who has an address, and says how
   *  many went and who was skipped for want of one. That second half matters
   *  on this screen: a wholesaler with no email address is one somebody has to
   *  telephone, and a chase that quietly reached four of five suppliers is a
   *  chase that looks done and is not.
   */
  async function sendOut(r: RfqRow) {
    try {
      const said = await api.post<{ message?: string; sent?: number }>(
        `/api/rfqs/${r.id}/send`, {});
      toast.ok(said.message
               ?? `${r.reference} sent to ${said.sent ?? 0} supplier(s).`);
      load();
    } catch (e) {
      toast.error(errorText(e, `${r.reference} could not be sent.`));
    }
  }

  return (
    <>
      <PageHead
        title="Quotes"
        sub="Ask several wholesalers, compare, then buy"
        also={
          <button className="btn secondary" onClick={() => setAuto(true)}>
            <Robot size={14} /> Asking by itself
          </button>
        }
        primary={
          <button className="btn primary" onClick={() => setRaising(true)}>
            <Plus size={14} weight="bold" /> Ask for prices
          </button>
        }
      />

      {queueUnknown && (
        <div className="card rfq-queue">
          <div className="rfq-queue-head">
            <b>Whether anything is waiting to be signed off could not be read</b>
            <span className="muted small">
              An award sitting here unsigned is an order nobody placed, so this
              is worth a reload rather than a shrug.
            </span>
          </div>
        </div>
      )}

      {queue.length > 0 && (
        <div className="card rfq-queue">
          <div className="rfq-queue-head">
            <b>
              {queue.length} award{queue.length === 1 ? "" : "s"} waiting to be
              signed off
            </b>
            <span className="muted small">
              Whoever chose the suppliers cannot approve their own choice.
            </span>
          </div>
          <ul className="rfq-queue-list">
            {queue.map((q) => (
              <li key={q.id}>
                <EntityLink to={`/rfqs/${q.id}`}>{q.reference}</EntityLink>
                <span className="rfq-queue-worth">{money(q.value)}</span>
                <span className="muted small">
                  {[q.awarded_by ? `chosen by ${q.awarded_by}` : "",
                    q.awarded_at ? fmtDate(q.awarded_at) : "",
                    q.dearer_lines
                      ? `${q.dearer_lines} line(s) where the cheapest lost`
                      : "cheapest on every line"].filter(Boolean).join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <Refreshable loading={rows === null} hasData={(rows?.length ?? 0) > 0}
                     skeleton={<TableSkeleton cols={5} rows={5} />}>
          {(rows?.length ?? 0) === 0 ? (
            <div className="empty">
              <b>No requests yet.</b>
              <p>
                Asking three wholesalers for a price takes a minute and is the
                difference between buying well and buying from whoever answered
                the telephone.
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="dt">
                <thead>
                  <tr>
                    <Th>Reference</Th><Th>Status</Th><Th>Raised</Th>
                    <Th className="num">Lines</Th>
                    <Th>Replies</Th><Th>Closes</Th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {rows!.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <EntityLink to={`/rfqs/${r.id}`}>{r.reference}</EntityLink>
                        {r.raised_automatically && (
                          <span className="badge muted" title={
                            "Raised by the nightly job because these lines had "
                            + "run out. Nothing was sent to any supplier."}>
                            raised for you
                          </span>
                        )}
                        {r.notes && <div className="muted small wrap">{r.notes}</div>}
                      </td>
                      <td><span className="badge muted">{SAYS_STATUS[r.status] ?? sentence(r.status)}</span></td>
                      <td className="small">{fmtDate(r.created_at)}</td>
                      <td className="num">{r.line_count}</td>
                      {/* The only actionable thing here: who still owes an
                          answer. A request nobody has replied to needs
                          chasing; one everybody has replied to needs
                          deciding. */}
                      <td>
                        {r.answered} of {r.asked}
                        {r.waiting_on > 0 && (
                          <span className="badge warn">
                            {r.waiting_on} to reply
                          </span>
                        )}
                      </td>
                      <td className="small">
                        {r.closes_at
                          ? fmtDate(r.closes_at)
                          : <span className="muted">No date</span>}
                      </td>
                      {/* THE ONE THING THIS SCREEN SAYS IS ACTIONABLE.
                          Its own docstring: "a request nobody has replied to
                          needs chasing, and one everybody has replied to needs
                          deciding". The table had no actions column at all, so
                          the answer to both was to open the request and come
                          back. Sending is the chase — the endpoint emails
                          everybody invited who has an address — and it is the
                          same act whether it has gone out once or three
                          times. */}
                      <td className="actions">
                        {r.status === "draft" && (
                          <BusyButton className="btn sm primary"
                                      busyLabel="Sending…"
                                      onClick={() => sendOut(r)}>
                            Send it
                          </BusyButton>
                        )}
                        {r.status === "sent" && r.waiting_on > 0 && (
                          <BusyButton className="btn sm"
                                      busyLabel="Chasing…"
                                      onClick={() => sendOut(r)}>
                            Chase {r.waiting_on}
                          </BusyButton>
                        )}
                        {r.status === "sent" && r.answered > 0
                          && r.waiting_on === 0 && (
                          <Link className="btn sm primary" to={`/rfqs/${r.id}`}>
                            Compare and award
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Refreshable>
      </div>

      {raising && (
        <NewRfq onClose={() => setRaising(false)}
                onRaised={() => { setRaising(false); load(); }} />
      )}

      {auto && (
        <RfqAuto onClose={() => setAuto(false)}
                 onRaised={() => { setAuto(false); load(); }} />
      )}
    </>
  );
}

/** Raise a request: what to ask about, and who to ask. */
function NewRfq({ onClose, onRaised }: { onClose: () => void; onRaised: () => void }) {
  const toast = useToast();
  const [low, setLow] = useState<Product[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierLite[]>([]);
  const [lowUnknown, setLowUnknown] = useState(false);
  const [suppliersUnknown, setSuppliersUnknown] = useState(false);
  const [wanted, setWanted] = useState<Record<number, number>>({});
  const [asking, setAsking] = useState<Set<number>>(new Set());
  const [notes, setNotes] = useState("");
  const [closes, setCloses] = useState("");

  useEffect(() => {
    // Everything at or below its reorder level: the lines somebody is about
    // to buy anyway, which is when asking around is worth doing.
    api.get<Product[]>("/api/products?low_stock=true")
      .then((r) => {
        setLow(r);
        setWanted(Object.fromEntries(r.map((p) => [
          p.id, Math.max(p.reorder_quantity || 0,
                         (p.reorder_level || 0) - (p.quantity_on_hand || 0)),
        ])));
      })
      // It was silent, and the empty state below said "Nothing is at its
      // reorder level" — a cause asserted from a failure. On this screen that
      // sentence is the reason somebody closes the modal and does not order.
      .catch(() => setLowUnknown(true));
    api.get<SupplierLite[]>("/api/suppliers")
      .then(setSuppliers)
      .catch(() => setSuppliersUnknown(true));
  }, []);

  const chosen = useMemo(
    () => low.filter((p) => (wanted[p.id] || 0) > 0), [low, wanted]);

  async function raise() {
    try {
      const said = await api.post<{ message: string }>("/api/rfqs", {
        notes: notes.trim(),
        closes_at: closes ? `${closes}T17:00:00` : null,
        lines: chosen.map((p) => ({ product_id: p.id, quantity: wanted[p.id] })),
        supplier_ids: [...asking],
      });
      toast.ok(said.message);
      onRaised();
    } catch (e) {
      toast.error(errorText(e, "That request could not be raised."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal rfq-new" onClick={(e) => e.stopPropagation()}>
        <h2>Ask for prices</h2>
        <p className="muted">
          Everything at or below its reorder level is here. Change a quantity
          to nought to leave it out.
        </p>

        <div className="rfq-new-grid">
          <div>
            <label className="field-label">What to ask about</label>
            <div className="rfq-new-list">
              {lowUnknown && (
                <p className="hint is-warn">
                  What is low could not be read, so this is not an answer about
                  your shelves. Reload the page before deciding not to order.
                </p>
              )}
              {!lowUnknown && low.length === 0 && (
                <p className="muted small">Nothing is at its reorder level.</p>
              )}
              {low.map((p) => (
                <label key={p.id} className="rfq-new-line">
                  <span>{p.name} {p.strength}</span>
                  <input type="number" min={0} value={wanted[p.id] ?? 0}
                         onChange={(e) => setWanted((w) => ({
                           ...w, [p.id]: Number(e.target.value) || 0 }))} />
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="field-label">Who to ask</label>
            <div className="rfq-new-list">
              {suppliersUnknown && (
                <p className="hint is-warn">
                  The suppliers could not be read. This is not the list of who
                  you deal with. Reload the page.
                </p>
              )}
              {!suppliersUnknown && suppliers.length === 0 && (
                <p className="muted small">
                  No suppliers are on file yet. Add them under Suppliers and
                  they appear here to tick.
                </p>
              )}
              {suppliers.map((s) => (
                <label key={s.id} className="rfq-new-line">
                  <span>
                    {s.name}
                    {!s.email && (
                      <span className="muted small"> · no email, ask them yourself</span>
                    )}
                  </span>
                  <input type="checkbox" checked={asking.has(s.id)}
                         onChange={(e) => setAsking((a) => {
                           const next = new Set(a);
                           e.target.checked ? next.add(s.id) : next.delete(s.id);
                           return next;
                         })} />
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="form-row">
          <div className="field span-7">
            <label htmlFor="rfq-notes">Note <span className="muted">optional</span></label>
            <input id="rfq-notes" value={notes} maxLength={300}
                   onChange={(e) => setNotes(e.target.value)}
                   placeholder="anything the wholesaler should know" />
          </div>
          <div className="field span-5">
            <label htmlFor="rfq-closes">Reply by</label>
            <input id="rfq-closes" type="date" value={closes}
                   onChange={(e) => setCloses(e.target.value)} />
            <span className="hint">
              A request with no closing date is one nobody ever compares.
            </span>
          </div>
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={raise}
                      disabled={chosen.length === 0 || asking.size === 0}
                      busyLabel="Raising…">
            Ask {asking.size || "no"} supplier(s) about {chosen.length} line(s)
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
