/** What a patient sees when they open the link the pharmacy sent them.
 *
 *  Built as its own page, outside the staff application, and that is not a
 *  detail. A patient must never load the pharmacy's sidebar, its bundle, or its
 *  session handling — none of it is theirs, and shipping it would mean a person
 *  checking whether their tablets are ready downloads a point-of-sale system to
 *  find out.
 *
 *  It also assumes a phone on a slow connection, because that is exactly what it
 *  will be opened on: one column, large touch targets, no table, and nothing
 *  that needs a second request before the first thing appears.
 */
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiBase } from "../api";
import "./portal.css";

interface Overview {
  greeting: string;
  pharmacy_ready: number;
  active_scripts: number;
  note: string;
}
interface Item {
  product: string; instructions: string; quantity: number;
  repeats_left: number; next_repeat: string | null;
}
interface Script {
  rx_number: string; date: string; status: string; doctor: string; items: Item[];
}
interface Full {
  patient: string; allergies: string; loyalty_points: number; scripts: Script[];
}

export default function PatientPortal() {
  const { token = "" } = useParams();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [full, setFull] = useState<Full | null>(null);
  const [dob, setDob] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${apiBase}/api/portal/patient/${token}`)
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail ?? "This link could not be opened.");
        setOverview(data);
      })
      .catch((e) => setError(e.message));
  }, [token]);

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/portal/patient/${token}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date_of_birth: dob }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "That did not work.");
      setFull(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pp">
      <header className="pp-head">
        <div className="pp-brand">RX5000</div>
        {overview && <h1>Hello, {overview.greeting}</h1>}
      </header>

      {/* A dead or expired link is the most likely failure here, and the person
          reading it can do nothing about it except ask. So the message says what
          to do rather than what went wrong. */}
      {error && !full && <p className="pp-error">{error}</p>}

      {overview && !full && (
        <>
          <section className="pp-card pp-status">
            <div className="pp-big">{overview.pharmacy_ready}</div>
            <div>
              {overview.pharmacy_ready === 1
                ? "prescription ready at the pharmacy"
                : "prescriptions ready at the pharmacy"}
            </div>
          </section>

          <section className="pp-card">
            <h2>See your medicines</h2>
            <p className="pp-muted">{overview.note}</p>
            <form onSubmit={confirm}>
              <label>
                Date of birth
                <input
                  type="date"
                  value={dob}
                  onChange={(e) => setDob(e.target.value)}
                  required
                />
              </label>
              <button disabled={busy || !dob}>
                {busy ? "Checking…" : "Show my medicines"}
              </button>
            </form>
            <p className="pp-fine">
              We ask because this link may have been forwarded. Your date of birth
              keeps your medicines private.
            </p>
          </section>
        </>
      )}

      {full && (
        <>
          <section className="pp-card">
            <h2>{full.patient}</h2>
            {full.allergies && (
              <p className="pp-allergy">Allergies on file: {full.allergies}</p>
            )}
            <p className="pp-muted">{full.loyalty_points} loyalty points</p>
          </section>

          {full.scripts.map((s) => (
            <section className="pp-card" key={s.rx_number}>
              <div className="pp-row">
                <b>{s.rx_number}</b>
                <span className={`pp-tag ${s.status === "active" ? "ok" : ""}`}>
                  {s.status}
                </span>
              </div>
              <div className="pp-muted">
                {s.date}
                {s.doctor && ` · ${s.doctor}`}
              </div>
              <ul className="pp-items">
                {s.items.map((i, n) => (
                  <li key={n}>
                    <b>{i.product}</b>
                    <div>{i.instructions}</div>
                    <div className="pp-muted">
                      {i.quantity} supplied
                      {i.repeats_left > 0 && ` · ${i.repeats_left} repeat(s) left`}
                      {i.next_repeat && ` · next due ${i.next_repeat}`}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}

          {full.scripts.length === 0 && (
            <section className="pp-card">
              <p className="pp-muted">Nothing has been dispensed to you yet.</p>
            </section>
          )}
        </>
      )}

      <footer className="pp-foot">
        This page is for you only. Please do not forward the link.
      </footer>
    </div>
  );
}
