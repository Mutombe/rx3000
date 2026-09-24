/** A wholesaler's own quotation form, opened from a link in an email.
 *
 *  WHY THERE IS NO SIGN-IN
 *
 *  Nobody at a wholesaler is going to create an account to quote a pharmacy
 *  for eight boxes of amoxicillin. Asking them to is how a supplier portal
 *  ends up unused and the prices go on being read down a telephone. The link
 *  is the credential: signed, scoped to this one request and this one
 *  supplier, and expiring.
 *
 *  WHAT IS DELIBERATELY NOT ON THIS PAGE
 *
 *  Not one other supplier's name, and not one other supplier's price. A
 *  quotation screen that shows a wholesaler what the others have bid is an
 *  auction the pharmacy did not mean to run.
 *
 *  THE TOTAL IS SHOWN AS THEY TYPE
 *
 *  A quote is a number somebody will be held to, and the line price is not the
 *  number they are agreeing to — the extended total is. Showing it as it is
 *  typed is how a misplaced decimal point gets caught by the person who can
 *  still fix it, rather than by a buyer two days later.
 *
 *  IT STAYS EDITABLE
 *
 *  Until the pharmacy decides. A supplier who spots a mistyped price an hour
 *  later can correct it here, and the alternative is a telephone call that
 *  puts the transcription step back in.
 */
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { apiBase } from "../api";
import PortalShell, { PortalGone, PortalLoading, useBrand }
  from "./PortalShell";
import "./portal.css";

interface QuoteLine {
  rfq_line_id: number;
  product: string;
  code: string;
  pack: string;
  quantity: number;
  available: boolean;
  unit_price: number | null;
  lead_days: number | null;
  note: string;
}

interface View {
  reference: string;
  pharmacy: string;
  supplier: string;
  notes: string;
  closes_at: string | null;
  lines: QuoteLine[];
  answered_at: string | null;
  declined: boolean;
  their_note: string;
  closed: boolean;
  closed_because: string;
}

/** What is being typed, as strings, because a half-typed "12." is not a
 *  number and a field that fights the person filling it in is a field they
 *  give up on and telephone instead. */
interface Draft { price: string; lead: string; out: boolean; note: string }

function money(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, {
    day: "numeric", month: "long", year: "numeric" });
}

export default function SupplierQuote() {
  const { token = "" } = useParams();
  const brand = useBrand("quote", token);
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState("");

  useEffect(() => {
    fetch(`${apiBase}/api/portal/quote/${token}`)
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail ?? "This link could not be opened.");
        setView(data);
        setNote(data.their_note ?? "");
        // Their previous answer comes back filled in, so correcting one price
        // does not mean retyping the other eleven.
        const next: Record<number, Draft> = {};
        for (const l of data.lines as QuoteLine[]) {
          next[l.rfq_line_id] = {
            price: l.unit_price === null ? "" : String(l.unit_price),
            lead: l.lead_days === null ? "" : String(l.lead_days),
            out: !l.available,
            note: l.note ?? "",
          };
        }
        setDrafts(next);
      })
      .catch((e) => setError(e.message));
  }, [token]);

  const lines = view?.lines ?? [];

  const total = useMemo(() => lines.reduce((sum, l) => {
    const d = drafts[l.rfq_line_id];
    if (!d || d.out) return sum;
    const price = Number(d.price);
    return sum + (Number.isFinite(price) ? price * l.quantity : 0);
  }, 0), [lines, drafts]);

  const priced = lines.filter((l) => {
    const d = drafts[l.rfq_line_id];
    return d && !d.out && d.price.trim() !== "" && Number(d.price) > 0;
  }).length;
  const unsupplied = lines.filter((l) => drafts[l.rfq_line_id]?.out).length;
  const untouched = lines.length - priced - unsupplied;

  function set(id: number, patch: Partial<Draft>) {
    setDrafts((all) => ({ ...all, [id]: { ...all[id], ...patch } }));
    setSent("");
  }

  async function submit(e: FormEvent, declined = false) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSent("");
    try {
      const r = await fetch(`${apiBase}/api/portal/quote/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          declined,
          note,
          answers: declined ? [] : lines
            // A line nobody typed anything against is left alone, rather than
            // sent as nought. Silence and a price of nought are different
            // facts, and the pharmacy's comparison keeps them apart.
            .filter((l) => {
              const d = drafts[l.rfq_line_id];
              return d && (d.out || d.price.trim() !== "");
            })
            .map((l) => {
              const d = drafts[l.rfq_line_id];
              return {
                rfq_line_id: l.rfq_line_id,
                available: !d.out,
                unit_price: d.out ? 0 : Number(d.price) || 0,
                lead_days: d.lead.trim() === "" ? null : Number(d.lead),
                note: d.note,
              };
            }),
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        const detail = data.detail;
        throw new Error(typeof detail === "string" ? detail
          : "Your prices were not saved. Please try again.");
      }
      setSent(data.message);
      setView((v) => (v ? { ...v, answered_at: data.answered_at, declined } : v));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !view) return <PortalGone brand={brand} said={error} />;
  if (!view) return <PortalLoading brand={brand} />;

  return (
    <PortalShell
      brand={brand}
      wide
      title={`Request for quotation ${view.reference}`}
      sub={`We have asked ${view.supplier} for prices on ${lines.length} `
        + `item${lines.length === 1 ? "" : "s"}.`
        + (view.closes_at ? ` Please reply by ${when(view.closes_at)}.` : "")}
      foot={`You are quoting ${view.pharmacy || "the pharmacy"} directly. `
        + "Nobody else can see what you have entered, and no other supplier's "
        + "prices are shown to you."}
    >

      {error && <p className="pp-error">{error}</p>}
      {sent && <p className="pp-ok">{sent}</p>}

      {view.closed ? (
        <div className="pp-alert pp-alert-warn">
          <b>This request has been decided</b>
          <span>{view.closed_because}</span>
        </div>
      ) : view.answered_at && !sent ? (
        <div className="pp-alert pp-alert-ok">
          <b>You answered this on {when(view.answered_at)}</b>
          <span>
            Your prices are below and can still be changed until the pharmacy
            decides.
          </span>
        </div>
      ) : null}

      {view.notes && (
        <div className="pp-card">
          <h2>Note from the pharmacy</h2>
          <p className="pp-muted">{view.notes}</p>
        </div>
      )}

      <form onSubmit={(e) => submit(e)}>
        <section className="pp-card">
          <h2>Your prices</h2>
          <p className="pp-fine sq-intro">
            Price is per {lines.some((l) => l.pack) ? "pack, as described" : "unit"}.
            Leave a line empty if you would rather not quote it. Tick cannot
            supply for anything you do not have, which is a different answer
            from leaving it blank and is more use to us.
          </p>

          {lines.map((l) => {
            const d = drafts[l.rfq_line_id] ?? { price: "", lead: "", out: false, note: "" };
            const extended = d.out ? 0 : (Number(d.price) || 0) * l.quantity;
            return (
              <div key={l.rfq_line_id}
                   className={`sq-line${d.out ? " is-out" : ""}`}>
                <div className="sq-what">
                  <b>{l.product}</b>
                  <span className="pp-muted">
                    {[l.code && `Code ${l.code}`, l.pack,
                      `${l.quantity} wanted`].filter(Boolean).join(" · ")}
                  </span>
                </div>

                <div className="sq-fields">
                  <label className="sq-price">
                    Unit price
                    <input inputMode="decimal" value={d.price} disabled={d.out || view.closed}
                           placeholder="0.00"
                           onChange={(e) => set(l.rfq_line_id, { price: e.target.value })} />
                  </label>
                  <label className="sq-lead">
                    Lead days
                    <input inputMode="numeric" value={d.lead} disabled={d.out || view.closed}
                           placeholder="days"
                           onChange={(e) => set(l.rfq_line_id, { lead: e.target.value })} />
                  </label>
                  {/* The extended total, beside the price that produced it.
                      This is the figure being agreed to, and a misplaced
                      decimal point shows up here first. */}
                  <div className="sq-total">
                    <span className="sq-total-label">Line total</span>
                    <b>{d.out ? "Not supplied" : money(extended)}</b>
                  </div>
                </div>

                <label className="sq-out">
                  <input type="checkbox" checked={d.out} disabled={view.closed}
                         onChange={(e) => set(l.rfq_line_id, { out: e.target.checked })} />
                  <span>Cannot supply this one</span>
                </label>
              </div>
            );
          })}
        </section>

        <section className="pp-card">
          <h2>Anything else we should know</h2>
          <label htmlFor="sq-note" className="sr-only-label">
            Note for the pharmacy
          </label>
          <textarea id="sq-note" rows={2} value={note} maxLength={400}
                    disabled={view.closed}
                    onChange={(e) => { setNote(e.target.value); setSent(""); }}
                    placeholder="Delivery terms, minimum order, part supply" />
        </section>

        {/* The running summary sits with the button, because it is the last
            thing read before committing to a price. */}
        {!view.closed && (
          <div className="pp-card sq-foot">
            <div className="sq-tally">
              <b className="pp-big">{money(total)}</b>
              <span className="pp-muted">
                {priced} line{priced === 1 ? "" : "s"} priced
                {unsupplied > 0 && `, ${unsupplied} cannot supply`}
                {untouched > 0 && `, ${untouched} left blank`}
              </span>
            </div>
            <button disabled={busy || (priced === 0 && unsupplied === 0)}>
              {busy ? "Sending…"
                : view.answered_at ? "Send the change" : "Send these prices"}
            </button>
            <button type="button" className="pp-ghost" disabled={busy}
                    onClick={(e) => submit(e, true)}>
              We cannot supply any of this
            </button>
          </div>
        )}
      </form>

    </PortalShell>
  );
}
