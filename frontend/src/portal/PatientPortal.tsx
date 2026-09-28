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
import { PortalApp, PortalBy, PortalGate, PortalGone, PortalLoading,
         PortalMark, PortalNav, PortalNone, useBrand } from "./PortalShell";
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
  const [tab, setTab] = useState<"now" | "scripts" | "history" | "shop">("now");
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

  /* Overdue is not "due, but redder". It is a different question — something
     you should already have collected — so it is its own section with its own
     count, rather than eight red chips down a list of twelve. */
  const overdueDue = record.due.filter((d) => d.overdue);
  const comingUp = record.due.filter((d) => !d.overdue);
  const ready = record.waiting.length;

  const tabs = [
    { key: "now" as const, label: "Right now", icon: <IconNow />,
      badge: ready + overdueDue.length },
    { key: "scripts" as const, label: "Scripts", icon: <IconScript /> },
    { key: "history" as const, label: "History", icon: <IconPast /> },
    { key: "shop" as const, label: "Pharmacy", icon: <IconShop /> },
  ];

  return (
    <PortalApp
      bar={
        <>
          <PortalMark brand={brand} small />
          <span className="pp-appbar-said">
            <b className="pp-appbar-shop">{brand?.name || "Your pharmacy"}</b>
            <span className="pp-appbar-who">
              {record.patient}
              {record.medical_aid ? ` · ${record.medical_aid}` : ""}
            </span>
          </span>
        </>
      }
      nav={<PortalNav tabs={tabs} tab={tab} setTab={setTab} />}
    >

      {tab === "now" && (
        <>
          {/* Allergies first and unmissable. It is the one thing on this page
              that could matter to somebody else reading it over their
              shoulder: a relative collecting on their behalf, a nurse, a
              paramedic. */}
          {record.allergies && (
            <div className="pp-alert pp-alert-bad">
              <b>Allergic to {record.allergies}</b>
              <span>Tell any pharmacist or doctor who treats you.</span>
            </div>
          )}

          <section className="pp-card pp-sec">
            <h2>
              Ready to collect
              {ready > 0 && <span className="pp-sec-n">{ready}</span>}
            </h2>
            <div className="pp-sec-body">
              {ready === 0 ? (
                <PortalNone
                  mark={<IconNow />}
                  said="Nothing is waiting for you"
                  next="When the pharmacy has something ready, it appears here
                        and they will send you a message."
                />
              ) : record.waiting.map((w, i) => (
                <div key={i} className="pp-row">
                  <div>
                    <b>{w.product}</b>
                    <span className="pp-muted">{w.quantity} · since {day(w.since)}</span>
                  </div>
                  <span className="pp-pill pp-pill-ok">Ready</span>
                </div>
              ))}
            </div>
          </section>

          {/* What you should already have had. Its own section, because "you
              are late for this" and "this is coming" are not the same
              sentence and do not belong in one list. */}
          {overdueDue.length > 0 && (
            <section className="pp-card pp-sec">
              <h2>
                Overdue
                <span className="pp-sec-n">{overdueDue.length}</span>
              </h2>
              <div className="pp-sec-body">
                {overdueDue.map((d, i) => (
                  <div key={i} className="pp-row">
                    <div>
                      <b>{d.product}</b>
                      <span className="pp-muted">
                        {Math.abs(d.days)} days ago · {d.left} left on the script
                      </span>
                    </div>
                    <span className="pp-pill pp-pill-bad">{day(d.on)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="pp-card pp-sec">
            <h2>
              Coming up
              {comingUp.length > 0 && <span className="pp-sec-n">{comingUp.length}</span>}
            </h2>
            <div className="pp-sec-body">
              {comingUp.length === 0 ? (
                <PortalNone
                  mark={<IconScript />}
                  said="Nothing is due"
                  next="We will let you know when something is."
                />
              ) : comingUp.map((d, i) => (
                <div key={i} className="pp-row">
                  <div>
                    <b>{d.product}</b>
                    <span className="pp-muted">
                      {d.days === 0 ? "Due today" : `Due in ${d.days} days`}
                      {" · "}{d.left} left on the script
                    </span>
                  </div>
                  <span className={`pp-pill ${d.days <= 7 ? "pp-pill-warn" : ""}`}>
                    {day(d.on)}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {record.deliveries.length > 0 && (
            <section className="pp-card pp-sec">
              <h2>On its way</h2>
              <div className="pp-sec-body">
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
              </div>
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

          {/* Asked last, not first. It used to sit above the medicines, so the
              screen opened by asking a favour before answering the question
              somebody came with. */}
          {record.to_review && !rated && (
            <RateIt
              token={token}
              code={code}
              it={record.to_review}
              onDone={() => setRated(true)}
            />
          )}
        </>
      )}

      {tab === "scripts" && (
        <>
          {record.scripts.length === 0 && (
            <section className="pp-card">
              <PortalNone
                mark={<IconScript />}
                said="No prescriptions on file yet"
                next="A prescription appears here once the pharmacy has
                      dispensed against it."
              />
            </section>
          )}
          {record.scripts.map((s) => (
            <section key={s.rx_number || s.date} className="pp-card pp-sec">
              <h2>
                {day(s.date)}
                <span className="pp-sec-n">{sentence(s.status)}</span>
              </h2>
              <div className="pp-sec-body">
                <p className="pp-muted" style={{ marginTop: 0 }}>
                  {s.doctor || "Prescriber not recorded"}
                  {s.rx_number && ` · ${s.rx_number}`}
                </p>
                {s.items.map((i, n) => (
                  <div key={n} className="pp-item">
                    <b>{i.product}</b>
                    {/* The directions, in the words on the label. This is what
                        a patient actually comes here to check. */}
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
              </div>
            </section>
          ))}
        </>
      )}

      {tab === "history" && (
        <section className="pp-card pp-sec">
          <h2>
            What I have collected
            {record.history.length > 0
              && <span className="pp-sec-n">{record.history.length}</span>}
          </h2>
          <div className="pp-sec-body">
            {record.history.length === 0 ? (
              <PortalNone
                mark={<IconPast />}
                said="Nothing collected yet"
                next="Everything the pharmacy hands over is listed here, with
                      the date and how it was paid for."
              />
            ) : record.history.map((h, i) => (
              <div key={i} className="pp-row">
                <div>
                  <b>{h.product}</b>
                  <span className="pp-muted">
                    {/* How it reached them, how it was paid, and whether
                        somebody signed for it. */}
                    {[day(h.on), String(h.quantity), h.how, h.paid,
                      h.signed ? "Signed for" : "",
                      h.is_repeat ? "Repeat" : ""]
                      .filter(Boolean).join(" · ")}
                  </span>
                  {h.rating > 0 && (
                    <span className="pp-stars"
                          aria-label={`You rated this ${h.rating} out of 5`}>
                      {"★".repeat(h.rating)}{"☆".repeat(5 - h.rating)}
                    </span>
                  )}
                </div>
                <span className={`pp-pill ${h.collected ? "pp-pill-ok" : "pp-pill-warn"}`}>
                  {h.collected ? "Collected" : "Waiting"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* The pharmacy, as somewhere you can reach rather than as grey small
          print at the bottom of a two-thousand-pixel page. Every line here is
          something to do: ring them, find them, check they are who they say. */}
      {tab === "shop" && (
        <>
          <section className="pp-card pp-shopcard">
            <PortalMark brand={brand} />
            <h1 className="pp-shopname-lg">{brand?.name || "Your pharmacy"}</h1>
            {brand && brand.address.length > 0 && (
              <p className="pp-shopline">{brand.address.join(", ")}</p>
            )}
            {brand?.registration_no && (
              <p className="pp-shopline">Licence {brand.registration_no}</p>
            )}
          </section>

          <div className="pp-acts">
            {brand?.phone && (
              <a className="pp-act" href={`tel:${brand.phone.replace(/\s+/g, "")}`}>
                <IconPhone />
                <span>
                  Ring the pharmacy
                  <span className="pp-act-said">{brand.phone}</span>
                </span>
                <span className="pp-act-go" aria-hidden="true"><IconGo /></span>
              </a>
            )}
            {brand && brand.address.length > 0 && (
              <a
                className="pp-act"
                target="_blank"
                rel="noreferrer"
                href={`https://www.google.com/maps/search/?api=1&query=${
                  encodeURIComponent([brand.name, ...brand.address].join(", "))}`}
              >
                <IconPin />
                <span>
                  Directions
                  <span className="pp-act-said">{brand.address.join(", ")}</span>
                </span>
                <span className="pp-act-go" aria-hidden="true"><IconGo /></span>
              </a>
            )}
            {brand?.email && (
              <a className="pp-act" href={`mailto:${brand.email}`}>
                <IconMail />
                <span>
                  Email them
                  <span className="pp-act-said">{brand.email}</span>
                </span>
                <span className="pp-act-go" aria-hidden="true"><IconGo /></span>
              </a>
            )}
          </div>

          <p className="pp-shopline" style={{ marginTop: "var(--pp-5)",
                                              textAlign: "center" }}>
            Your record, as your pharmacy holds it. Ring them if anything here
            looks wrong. It is quicker than it looks.
          </p>
          <PortalBy />
        </>
      )}

    </PortalApp>
  );
}

/* The marks on the navigation and in the empty states. Drawn here rather than
   imported: the icon set the staff application uses is a dependency a
   patient's phone should not be downloading to find out whether their tablets
   are ready. Each is one path, on a 24 grid, inheriting its colour. */
const svg = {
  width: 24, height: 24, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.8,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};
function IconNow() {
  return (
    <svg {...svg} aria-hidden="true">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
    </svg>
  );
}
function IconScript() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4" /><path d="M9 13h6M9 17h4" />
    </svg>
  );
}
function IconPast() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M4 5v6h6" />
      <path d="M4.5 11a8 8 0 1 0 2-5.3L4 8" />
      <path d="M12 8v4.5l3 1.8" />
    </svg>
  );
}
function IconShop() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M4 9h16v11H4z" /><path d="M3 9l1.6-4.5h14.8L21 9" />
      <path d="M10 20v-5h4v5" />
    </svg>
  );
}
function IconPhone() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M6 3h3l2 5-2.5 1.5a12 12 0 0 0 6 6L16 13l5 2v3a2 2 0 0 1-2.2 2A17 17 0 0 1 4 5.2 2 2 0 0 1 6 3z" />
    </svg>
  );
}
function IconPin() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}
function IconMail() {
  return (
    <svg {...svg} aria-hidden="true">
      <path d="M3 6h18v12H3z" /><path d="M3 7l9 6 9-6" />
    </svg>
  );
}
function IconGo() {
  return (
    <svg {...svg} width={18} height={18} aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
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
