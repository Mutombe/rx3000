/** What a patient sees when they open the link the pharmacy sent them.
 *
 *  Built as its own page, outside the staff application, and that is not a
 *  detail. A patient must never load the pharmacy's sidebar, its bundle or its
 *  session handling — none of it is theirs, and shipping it would mean somebody
 *  checking whether their tablets are ready downloads a point-of-sale system to
 *  find out.
 *
 *  It assumes a phone, outdoors, on a slow connection, held by somebody who has
 *  never seen it before and will use it for ninety seconds. One column, large
 *  type, thumb-sized targets, and the answer to the question they opened it for
 *  above the fold.
 *
 *  THE ORDER OF THE PAGE IS THE DESIGN
 *
 *  What is ready now, then what is due next, then everything else. A patient
 *  opening this has one of two questions — "is it ready" or "when do I need
 *  more", and both are answered before anything is scrolled. The prescription
 *  history is underneath, where somebody looking for it will go and nobody else
 *  has to wade through it.
 *
 *  A four-digit code, not a date of birth. A forwarded message usually reaches
 *  somebody who already knows the birthday, and telling a patient their own
 *  date of birth is wrong is close to the rudest thing software can say.
 */
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiBase, sentence } from "../api";
import PinInput from "../components/PinInput";
import PortalShell, { PortalGate, PortalGone, PortalLoading, useBrand }
  from "./PortalShell";
import "./portal.css";

interface Teaser {
  greeting: string; waiting: number; has_code: boolean; note: string;
}
interface Item {
  product: string; instructions: string; quantity: number;
  repeats_left: number; repeats_allowed: number; next_repeat: string | null;
}
interface Script {
  rx_number: string; date: string; status: string; doctor: string;
  items: Item[];
}
interface Record {
  patient: string; first_name: string;
  allergies: string; conditions: string;
  loyalty_points: number; medical_aid: string; member_number: string;
  owed: number;
  waiting: { product: string; quantity: number; since: string;
             days: number | null }[];
  due: { product: string; on: string; days: number; overdue: boolean;
         left: number }[];
  scripts: Script[];
  history: { product: string; quantity: number; on: string;
             collected: string | null; is_repeat: boolean;
             /** The four facts that follow a dispensing everywhere. */
             how: string; paid: string; signed: boolean; rating: number }[];
  /** The last handover they have not rated, or nothing. */
  to_review: { on: string; ids: number[]; what: string[]; how: string } | null;
  deliveries: { number: string; status: string; address: string;
                when: string; to_collect: number }[];
}

const money = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD" });
const day = (s: string | null) =>
  s ? new Date(s).toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" }) : "";

export default function PatientPortal() {
  const { token = "" } = useParams();
  const brand = useBrand("patient", token);
  const [teaser, setTeaser] = useState<Teaser | null>(null);
  const [record, setRecord] = useState<Record | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"now" | "scripts" | "history">("now");
  // Hidden for the rest of the visit once they have answered, rather than
  // waiting for a reload: a prompt that reappears after you answered it is a
  // prompt people learn to ignore.
  const [rated, setRated] = useState(false);

  useEffect(() => {
    fetch(`${apiBase}/api/portal/patient/${token}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? "");
        setTeaser(await r.json());
      })
      .catch((e) => setError(e.message
        || "This link is no longer valid. Please ask the pharmacy for a new one."));
  }, [token]);

  // PinInput puts the caret in the first box itself and submits on the last
  // digit, so the common case is four keystrokes and nothing else.
  async function confirm(e?: FormEvent, typed?: string) {
    e?.preventDefault();
    const digits = typed ?? code;
    if (digits.length < 4) return;
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/portal/patient/${token}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: digits }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "That did not work.");
      setRecord(body);
    } catch (e: any) {
      // The server counts the tries and says how many are left. Shown as
      // written — "3 more tries" is the only thing that stops somebody
      // guessing blindly and then ringing to complain the link is broken.
      setError(e.message);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  // One expired card and one spinner for every portal, from the shell. There
  // were three of each and they had already drifted: two drew the mark as
  // "RX" and one as the prescription sign.
  if (error && !teaser) return <PortalGone brand={brand} said={error} />;
  if (!teaser) return <PortalLoading brand={brand} />;

  // ---- the gate ---------------------------------------------------------
  if (!record) {
    return (
      <PortalGate
        brand={brand}
        title={`Hello ${teaser.greeting}`}
        // The one fact worth showing before anything is proved. It says
        // nothing about what the medicine is, so a link on the wrong phone
        // has disclosed nothing clinical.
        lead={teaser.waiting > 0 ? (
          <>
            <b>{teaser.waiting}</b>{" "}
            {teaser.waiting === 1 ? "item is" : "items are"} ready to collect.
          </>
        ) : "Nothing is waiting for you at the moment."}
        said={error}
        onSubmit={confirm}
        action={
          <button className="pp-btn" disabled={busy || code.length < 4}>
            {busy ? "Checking…" : "See my prescriptions"}
          </button>
        }
        fine={"The pharmacy gave you this code. If you have lost it, ring them "
              + "and they will read you a new one."}
      >
        <p className="pp-label">Enter your four-digit code</p>
        {/* Four boxes, not one letter-spaced field. The same component the
            till unlocks with: the reader can see how many digits are left
            without counting dots, it submits itself on the last one, and a
            wrong code shakes the row and clears it. */}
        <PinInput
          value={code}
          onChange={setCode}
          onComplete={(pin) => confirm(undefined, pin)}
          checking={busy}
          invalid={!!error}
          disabled={busy}
        />
      </PortalGate>
    );
  }

  // ---- their record -----------------------------------------------------
  const overdue = record.due.filter((d) => d.overdue);
  const soon = record.due.filter((d) => !d.overdue && d.days <= 14);

  return (
    <PortalShell
      brand={brand}
      title={record.first_name}
      sub={record.medical_aid
        ? `${record.medical_aid}${record.member_number ? ` · ${record.member_number}` : ""}`
        : undefined}
      foot={"Your record, as your pharmacy holds it. Ring them if anything "
            + "here looks wrong. It is quicker than it looks."}
    >

      {/* Allergies first and unmissable. It is the one thing on this page that
          could matter to somebody else reading it over their shoulder. A
          relative collecting on their behalf, a nurse, a paramedic. */}
      {record.allergies && (
        <div className="pp-alert pp-alert-bad">
          <b>Allergic to {record.allergies}</b>
          <span>Tell any pharmacist or doctor who treats you.</span>
        </div>
      )}

      {overdue.length > 0 && (
        <div className="pp-alert pp-alert-warn">
          <b>
            {overdue.length === 1
              ? `Your ${overdue[0].product} was due ${Math.abs(overdue[0].days)} days ago`
              : `${overdue.length} of your repeats are overdue`}
          </b>
          <span>Come in when you can. We will have it ready.</span>
        </div>
      )}

      <nav className="pp-tabs" role="tablist">
        {([["now", "Right now"], ["scripts", "Prescriptions"],
           ["history", "What I have had"]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k}
            className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </nav>

      {/* Asked once, about the last handover, and only while it is still
          worth asking. Nobody had ever asked a patient of one of these
          pharmacies what they thought. */}
      {tab === "now" && record.to_review && !rated && (
        <RateIt
          token={token}
          code={code}
          it={record.to_review}
          onDone={() => setRated(true)}
        />
      )}

      {tab === "now" && (
        <>
          <section className="pp-card">
            <h2>Ready to collect</h2>
            {record.waiting.length === 0 ? (
              <p className="pp-muted">Nothing is waiting for you.</p>
            ) : record.waiting.map((w, i) => (
              <div key={i} className="pp-row">
                <div>
                  <b>{w.product}</b>
                  <span className="pp-muted">{w.quantity} · since {day(w.since)}</span>
                </div>
                <span className="pp-pill pp-pill-ok">Ready</span>
              </div>
            ))}
          </section>

          <section className="pp-card">
            <h2>Due next</h2>
            {record.due.length === 0 ? (
              <p className="pp-muted">
                Nothing is due. We will let you know when something is.
              </p>
            ) : record.due.map((d, i) => (
              <div key={i} className="pp-row">
                <div>
                  <b>{d.product}</b>
                  <span className="pp-muted">
                    {d.overdue
                      ? `Was due ${Math.abs(d.days)} days ago`
                      : d.days === 0 ? "Due today"
                      : `Due in ${d.days} days`}
                    {" · "}{d.left} left on the script
                  </span>
                </div>
                <span className={`pp-pill ${d.overdue ? "pp-pill-bad"
                  : d.days <= 7 ? "pp-pill-warn" : ""}`}>
                  {day(d.on)}
                </span>
              </div>
            ))}
          </section>

          {record.deliveries.length > 0 && (
            <section className="pp-card">
              <h2>On its way</h2>
              {record.deliveries.map((d) => (
                <div key={d.number} className="pp-row">
                  <div>
                    <b>{d.status === "out" ? "Out for delivery" : "Being prepared"}</b>
                    <span className="pp-muted">{d.address}</span>
                  </div>
                  {d.to_collect > 0 && (
                    <span className="pp-pill pp-pill-warn">
                      {money(d.to_collect)} to pay
                    </span>
                  )}
                </div>
              ))}
            </section>
          )}

          {(record.owed > 0 || record.loyalty_points > 0) && (
            <section className="pp-card pp-split">
              {record.owed > 0 && (
                <div>
                  <span className="pp-muted">Outstanding</span>
                  <b className="pp-big">{money(record.owed)}</b>
                </div>
              )}
              {record.loyalty_points > 0 && (
                <div>
                  <span className="pp-muted">Points</span>
                  <b className="pp-big">{record.loyalty_points}</b>
                </div>
              )}
            </section>
          )}
        </>
      )}

      {tab === "scripts" && (
        <>
          {record.scripts.length === 0 && (
            <section className="pp-card">
              <p className="pp-muted">No prescriptions on file yet.</p>
            </section>
          )}
          {record.scripts.map((s) => (
            <section key={s.rx_number || s.date} className="pp-card">
              <div className="pp-row pp-row-head">
                <div>
                  <b>{day(s.date)}</b>
                  <span className="pp-muted">
                    {s.doctor || "Prescriber not recorded"}
                    {s.rx_number && ` · ${s.rx_number}`}
                  </span>
                </div>
                <span className={`pp-pill ${s.status === "active" ? "pp-pill-ok" : ""}`}>
                  {sentence(s.status)}
                </span>
              </div>
              {s.items.map((i, n) => (
                <div key={n} className="pp-item">
                  <b>{i.product}</b>
                  {/* The directions, in the words on the label. This is what a
                      patient actually comes here to check. */}
                  {i.instructions && (
                    <span className="pp-directions">{i.instructions}</span>
                  )}
                  <span className="pp-muted">
                    {i.quantity}
                    {i.repeats_allowed > 0
                      && ` · ${i.repeats_left} of ${i.repeats_allowed} repeats left`}
                    {i.next_repeat && ` · next ${day(i.next_repeat)}`}
                  </span>
                </div>
              ))}
            </section>
          ))}
        </>
      )}

      {tab === "history" && (
        <section className="pp-card">
          <h2>What I have collected</h2>
          {record.history.length === 0 ? (
            <p className="pp-muted">Nothing yet.</p>
          ) : record.history.map((h, i) => (
            <div key={i} className="pp-row">
              <div>
                <b>{h.product}</b>
                <span className="pp-muted">
                  {/* How it reached them, how it was paid, and whether
                      somebody signed for it. Four facts that were nowhere
                      before, and which are what a patient checks a record
                      for after the event. */}
                  {[day(h.on), String(h.quantity), h.how, h.paid,
                    h.signed ? "Signed for" : "",
                    h.is_repeat ? "Repeat" : ""]
                    .filter(Boolean).join(" · ")}
                </span>
                {h.rating > 0 && (
                  <span className="pp-stars" aria-label={`You rated this ${h.rating} out of 5`}>
                    {"★".repeat(h.rating)}{"☆".repeat(5 - h.rating)}
                  </span>
                )}
              </div>
              <span className={`pp-pill ${h.collected ? "pp-pill-ok" : "pp-pill-warn"}`}>
                {h.collected ? "Collected" : "Waiting"}
              </span>
            </div>
          ))}
        </section>
      )}

    </PortalShell>
  );
}


/** One question, five taps, and a box nobody has to fill in.
 *
 *  Asked about the handover rather than the medicine: a script with four
 *  items is one visit and one opinion, and asking four times is how a rating
 *  prompt gets dismissed and never answered again. The answer is written
 *  against every line in that handover, so a report can still group by it.
 */
function RateIt({ token, code, it, onDone }: {
  token: string;
  code: string;
  it: { on: string; ids: number[]; what: string[]; how: string };
  onDone: () => void;
}) {
  const [stars, setStars] = useState(0);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [oops, setOops] = useState("");

  async function send(rating: number) {
    setBusy(true);
    setOops("");
    try {
      const r = await fetch(`${apiBase}/api/portal/patient/${token}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, rating, note, ids: it.ids }),
      });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? "That did not save.");
      onDone();
    } catch (e: any) {
      setOops(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="pp-card pp-rate">
      <h2>How did we do</h2>
      <p className="pp-lead">
        {it.how || "Your medicine"} on {day(it.on)}
        {it.what.length > 0 && `: ${it.what.join(", ")}`}
      </p>
      <div className="pp-stars-pick" role="group" aria-label="Your rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            className={n <= stars ? "on" : ""}
            aria-label={`${n} out of 5`}
            aria-pressed={n <= stars}
            disabled={busy}
            onClick={() => setStars(n)}
          >
            {n <= stars ? "★" : "☆"}
          </button>
        ))}
      </div>
      {stars > 0 && (
        <>
          <label className="pp-label" htmlFor="pp-note">
            Anything you want to tell them
          </label>
          <textarea
            id="pp-note"
            rows={2}
            value={note}
            maxLength={2000}
            disabled={busy}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional"
          />
          <button className="pp-btn" disabled={busy}
                  onClick={() => send(stars)}>
            {busy ? "Sending…" : "Send it"}
          </button>
        </>
      )}
      {oops && <p className="pp-error">{oops}</p>}
      <button type="button" className="pp-ghost" disabled={busy}
              onClick={onDone}>
        Not now
      </button>
    </section>
  );
}
