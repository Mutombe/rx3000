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
 *  more" — and both are answered before anything is scrolled. The prescription
 *  history is underneath, where somebody looking for it will go and nobody else
 *  has to wade through it.
 *
 *  A four-digit code, not a date of birth. A forwarded message usually reaches
 *  somebody who already knows the birthday, and telling a patient their own
 *  date of birth is wrong is close to the rudest thing software can say.
 */
import { FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { apiBase } from "../api";
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
             collected: string | null; is_repeat: boolean }[];
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
  const [teaser, setTeaser] = useState<Teaser | null>(null);
  const [record, setRecord] = useState<Record | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"now" | "scripts" | "history">("now");
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${apiBase}/api/portal/patient/${token}`)
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json()).detail ?? "");
        setTeaser(await r.json());
      })
      .catch((e) => setError(e.message
        || "This link is no longer valid. Please ask the pharmacy for a new one."));
  }, [token]);

  useEffect(() => { if (teaser) box.current?.focus(); }, [teaser]);

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/portal/patient/${token}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
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
      box.current?.focus();
    } finally {
      setBusy(false);
    }
  }

  if (error && !teaser) {
    return (
      <div className="pp pp-gate">
        <form className="pp-card pp-centre" onSubmit={(e) => e.preventDefault()}>
          <div className="pp-mark">℞</div>
          <h1>This link has expired</h1>
          <p className="pp-muted">{error}</p>
        </form>
      </div>
    );
  }

  if (!teaser) {
    return (
      <div className="pp pp-gate">
        <form className="pp-card pp-centre" onSubmit={(e) => e.preventDefault()}>
          <div className="pp-spinner" />
        </form>
      </div>
    );
  }

  // ---- the gate ---------------------------------------------------------
  if (!record) {
    return (
      // Centred in the screen, like the sign-in the staff use. It used to sit
      // near the top of an empty page, which reads as a form somebody forgot
      // to finish rather than as the front door.
      <div className="pp pp-gate">
        <form className="pp-card pp-centre" onSubmit={confirm}>
          <div className="pp-mark">℞</div>
          <h1>Hello {teaser.greeting}</h1>

          {/* The one fact worth showing before anything is proved. It says
              nothing about what the medicine is, so a link on the wrong phone
              has disclosed nothing clinical. */}
          {teaser.waiting > 0 ? (
            <p className="pp-lead">
              <b>{teaser.waiting}</b>{" "}
              {teaser.waiting === 1 ? "item is" : "items are"} ready to collect.
            </p>
          ) : (
            <p className="pp-lead">Nothing is waiting for you at the moment.</p>
          )}

          <label className="pp-label" htmlFor="code">
            Enter your four-digit code
          </label>
          <input
            id="code"
            ref={box}
            className="pp-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]*"
            maxLength={8}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            placeholder="••••"
            aria-describedby={error ? "pp-error" : undefined}
          />
          {error && <p id="pp-error" className="pp-error">{error}</p>}

          <button className="pp-btn" disabled={busy || code.length < 4}>
            {busy ? "Checking…" : "See my prescriptions"}
          </button>
          <p className="pp-fine">
            The pharmacy gave you this code. If you have lost it, ring them and
            they will read you a new one.
          </p>
        </form>
      </div>
    );
  }

  // ---- their record -----------------------------------------------------
  const overdue = record.due.filter((d) => d.overdue);
  const soon = record.due.filter((d) => !d.overdue && d.days <= 14);

  return (
    <div className="pp">
      <header className="pp-head">
        <div>
          <div className="pp-mark pp-mark-sm">℞</div>
          <h1>{record.first_name}</h1>
          {record.medical_aid && (
            <p className="pp-muted">
              {record.medical_aid}
              {record.member_number && ` · ${record.member_number}`}
            </p>
          )}
        </div>
      </header>

      {/* Allergies first and unmissable. It is the one thing on this page that
          could matter to somebody else reading it over their shoulder — a
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
          <span>Come in when you can — we will have it ready.</span>
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
                <span className="pp-pill pp-pill-ok">ready</span>
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
                      ? `was due ${Math.abs(d.days)} days ago`
                      : d.days === 0 ? "due today"
                      : `due in ${d.days} days`}
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
                  {s.status}
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
                  {day(h.on)} · {h.quantity}
                  {h.is_repeat && " · repeat"}
                </span>
              </div>
              <span className={`pp-pill ${h.collected ? "pp-pill-ok" : "pp-pill-warn"}`}>
                {h.collected ? "collected" : "waiting"}
              </span>
            </div>
          ))}
        </section>
      )}

      <footer className="pp-foot">
        Your record, as your pharmacy holds it. Ring them if anything here looks
        wrong — it is quicker than it looks.
      </footer>
    </div>
  );
}
