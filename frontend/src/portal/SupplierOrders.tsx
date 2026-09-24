/** A wholesaler's own view of the orders a pharmacy has sent them.
 *
 *  WHAT THIS REPLACES
 *
 *  A telephone call, in the other direction from the quoting portal. "When is
 *  it coming" is the commonest call a pharmacy makes, and the answer used to
 *  live on whatever scrap of paper the person who rang wrote it on.
 *
 *  WHAT A SUPPLIER CAN CHANGE HERE, AND WHAT THEY CANNOT
 *
 *  They can say when it will arrive and how much of each line they will
 *  actually send. They cannot touch a price or a quantity ordered. A portal
 *  where the other side of a transaction can edit the transaction is a shared
 *  document with no owner, and the first dispute about what was agreed ends
 *  it. What the pharmacy ordered sits beside what the supplier says, and the
 *  two are compared rather than merged.
 *
 *  CONFIRMING LESS IS NOT A FAILURE
 *
 *  A wholesaler who can only send sixty of the hundred is telling the
 *  pharmacy something worth knowing on Monday instead of on Thursday when the
 *  van arrives. So the short quantity is an ordinary thing to type here, not
 *  a warning, and a line left alone means they have not said, which is a
 *  different answer from nought.
 */
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiBase } from "../api";
import PortalShell, { PortalGone, PortalLoading, useBrand }
  from "./PortalShell";
import "./portal.css";

interface Line {
  item_id: number;
  product: string;
  code: string;
  pack: string;
  quantity_ordered: number;
  quantity_confirmed: number | null;
  unit_cost: number;
}

interface Order {
  id: number;
  order_number: string;
  status: string;
  sent_at: string | null;
  created_at: string;
  received_at: string | null;
  acknowledged_at: string | null;
  promised_date: string | null;
  supplier_note: string;
  notes: string;
  lines: Line[];
  value: number;
  needs_answer: boolean;
}

interface View {
  supplier: string;
  pharmacy: string;
  orders: Order[];
  waiting: number;
  note: string;
}

function money(n: number): string {
  // With the currency on it. It printed "1,542.80" before, which is a number
  // and not a price, and a wholesaler quoting in two currencies had to guess.
  return n.toLocaleString(undefined, {
    style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, {
    day: "numeric", month: "long", year: "numeric" });
}

export default function SupplierOrders() {
  const { token = "" } = useParams();
  const brand = useBrand("supplier", token);
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(() => {
    fetch(`${apiBase}/api/portal/supplier/${token}`)
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail ?? "This link could not be opened.");
        setView(data);
        // The one that is waiting on them opens itself, because that is what
        // they came for and a list of closed panels is a list nobody opens.
        const first = (data.orders as Order[]).find((o) => o.needs_answer);
        setOpen((was) => was ?? first?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, [token]);
  useEffect(load, [load]);

  if (error && !view) return <PortalGone brand={brand} said={error} />;
  if (!view) return <PortalLoading brand={brand} />;

  return (
    <PortalShell
      brand={brand}
      wide
      title="Your orders"
      sub={`${view.supplier}. ` + (view.waiting
        ? `${view.waiting} order${view.waiting === 1 ? "" : "s"} waiting on you.`
        : "Nothing is waiting on you.")}
      foot={view.note}
    >

      {error && <p className="pp-error">{error}</p>}

      {view.orders.length === 0 ? (
        <div className="pp-card pp-centre">
          <b>No orders yet</b>
          <p className="pp-muted">
            Anything {view.pharmacy || "the pharmacy"} sends you will appear
            here.
          </p>
        </div>
      ) : (
        view.orders.map((order) => (
          <OrderCard key={order.id} token={token} order={order}
                     open={open === order.id}
                     onToggle={() => setOpen(open === order.id ? null : order.id)}
                     onSaved={load} />
        ))
      )}

    </PortalShell>
  );
}

function OrderCard({ token, order, open, onToggle, onSaved }: {
  token: string;
  order: Order;
  open: boolean;
  onToggle: () => void;
  onSaved: () => void;
}) {
  const [promised, setPromised] = useState(order.promised_date ?? "");
  const [note, setNote] = useState(order.supplier_note ?? "");
  const [counts, setCounts] = useState<Record<number, string>>(
    () => Object.fromEntries(order.lines.map((l) => [
      l.item_id,
      // Their previous answer comes back; a line they have not answered
      // stays empty rather than being filled in with what was ordered,
      // because a prefilled number is one nobody checks.
      l.quantity_confirmed === null ? "" : String(l.quantity_confirmed),
    ])));
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [oops, setOops] = useState("");

  const closed = order.status === "received" || order.status === "cancelled";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setOops("");
    setSaid("");
    try {
      const r = await fetch(
        `${apiBase}/api/portal/supplier/${token}/orders/${order.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            promised_date: promised,
            note,
            lines: order.lines
              .filter((l) => (counts[l.item_id] ?? "").trim() !== "")
              .map((l) => ({
                item_id: l.item_id,
                quantity_confirmed: Number(counts[l.item_id]),
              })),
          }),
        });
      const data = await r.json();
      if (!r.ok) {
        const d = data.detail;
        throw new Error(typeof d === "string" ? d
          : "That could not be saved. Please try again.");
      }
      setSaid(data.message);
      onSaved();
    } catch (e: any) {
      setOops(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`pp-card so-order${order.needs_answer ? " is-waiting" : ""}`}>
      <button type="button" className="so-head" onClick={onToggle}
              aria-expanded={open}>
        <span className="so-head-main">
          <b>{order.order_number}</b>
          <span className="pp-muted">
            {order.lines.length} line{order.lines.length === 1 ? "" : "s"} ·{" "}
            {money(order.value)}
            {order.sent_at && ` · Sent ${when(order.sent_at)}`}
          </span>
        </span>
        <span className={`pp-pill ${
          order.status === "received" ? "pp-pill-ok"
            : order.needs_answer ? "pp-pill-warn" : ""}`}>
          {order.status === "received" ? "Received"
            : order.status === "cancelled" ? "Cancelled"
            : order.acknowledged_at
              ? (order.promised_date
                  ? `Due ${when(order.promised_date)}`
                  : "Confirmed")
              : "Please confirm"}
        </span>
      </button>

      {open && (
        <>
          {order.notes && <p className="pp-muted so-note">{order.notes}</p>}
          {oops && <p className="pp-error">{oops}</p>}
          {said && <p className="pp-ok">{said}</p>}

          <form onSubmit={submit}>
            <div className="so-lines">
              {order.lines.map((l) => {
                const typed = counts[l.item_id] ?? "";
                const short = typed !== "" && Number(typed) < l.quantity_ordered;
                return (
                  <div key={l.item_id} className="so-line">
                    <div className="so-what">
                      <b>{l.product}</b>
                      <span className="pp-muted">
                        {[l.code && `Code ${l.code}`, l.pack,
                          `${money(l.unit_cost)} each`].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                    <div className="so-counts">
                      <div className="so-ordered">
                        <span className="so-cap">Ordered</span>
                        <b>{l.quantity_ordered}</b>
                      </div>
                      <label className="so-sending">
                        <span className="so-cap">Sending</span>
                        {/* NO PLACEHOLDER SHOWING THE ORDERED QUANTITY.
                            A grey 20 in the box beside a black 20 reads as
                            a number already confirmed, and a supplier who
                            thinks they have answered does not answer. The
                            quantity ordered is immediately to the left; an
                            empty box means they have not said, which is
                            exactly what an empty box should mean. */}
                        <input inputMode="numeric" value={typed}
                               disabled={closed}
                               aria-label={`Sending, of ${l.quantity_ordered} ordered`}
                               onChange={(e) => {
                                 setCounts((c) => ({ ...c, [l.item_id]: e.target.value }));
                                 setSaid("");
                               }} />
                      </label>
                    </div>
                    {/* Said plainly and without alarm. A short line is an
                        ordinary fact and the pharmacy would far rather know
                        it now than on delivery day. */}
                    {short && (
                      <span className="so-short">
                        {l.quantity_ordered - Number(typed)} short of what was
                        ordered
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            {!closed && (
              <div className="so-foot">
                <label>
                  When will it arrive
                  <input type="date" value={promised}
                         onChange={(e) => { setPromised(e.target.value); setSaid(""); }} />
                </label>
                <label>
                  Anything we should know
                  <input value={note} maxLength={500}
                         onChange={(e) => { setNote(e.target.value); setSaid(""); }}
                         placeholder="part delivery, a substitution, a query" />
                </label>
                <button disabled={busy}>
                  {busy ? "Saving…"
                    : order.acknowledged_at ? "Update what you told them"
                    : "Confirm this order"}
                </button>
              </div>
            )}
          </form>
        </>
      )}
    </section>
  );
}
