/** The prescriber's side: see what happened, and send a script in.
 *
 *  The two halves of this page have different front doors on purpose. The link
 *  answers "did my patient collect" and needs no credential. Writing a
 *  prescription needs the prescriber's own sign-in, because a link that can
 *  prescribe is a prescription pad held by everyone it was ever forwarded to.
 *
 *  The page says so plainly rather than hiding the sign-in behind a menu. A
 *  prescriber who understands why they are being asked to sign in will do it;
 *  one who runs into an unexplained login will ring the pharmacy instead.
 */
import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiBase } from "../api";
import "./portal.css";

interface Script {
  rx_number: string; date: string; status: string;
  patient: string; collected: boolean;
}
interface Overview {
  doctor: string; practice_number: string; note: string; scripts: Script[];
}
interface Line {
  product_id: string; dosage_instructions: string;
  quantity: string; repeats_allowed: string;
}

const BLANK: Line = {
  product_id: "", dosage_instructions: "", quantity: "", repeats_allowed: "0",
};

export default function DoctorPortal() {
  const { token = "" } = useParams();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  // Prescribing session — separate credential, kept only in memory. A
  // prescriber writes a script and leaves; persisting this to localStorage
  // would leave a signed-in prescription pad on a shared consulting-room PC.
  const [session, setSession] = useState<{ token: string; doctor: string } | null>(null);
  const [login, setLogin] = useState({ practice_number: "", password: "" });
  const [patientId, setPatientId] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<Line[]>([{ ...BLANK }]);
  const [sent, setSent] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${apiBase}/api/portal/doctor/${token}`)
      .then(async (r) => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail ?? "This link could not be opened.");
        setOverview(data);
        setLogin((l) => ({ ...l, practice_number: data.practice_number ?? "" }));
      })
      .catch((e) => setError(e.message));
  }, [token]);

  async function signIn(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/portal/doctor/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(login),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "Sign-in failed.");
      setSession({ token: data.token, doctor: data.doctor });
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setSent("");
    try {
      const r = await fetch(`${apiBase}/api/portal/doctor/prescriptions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({
          patient_id: Number(patientId),
          notes,
          items: lines.map((l) => ({
            product_id: Number(l.product_id),
            dosage_instructions: l.dosage_instructions,
            quantity: Number(l.quantity),
            repeats_allowed: Number(l.repeats_allowed || 0),
          })),
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        const d = data.detail;
        throw new Error(typeof d === "string" ? d : "The script was not accepted.");
      }
      setSent(data.message);
      setLines([{ ...BLANK }]);
      setNotes("");
      setPatientId("");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function setLine(i: number, patch: Partial<Line>) {
    setLines((all) => all.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  }

  return (
    <div className="pp pp-wide">
      <header className="pp-head">
        <div className="pp-brand">RX5000</div>
        {overview && (
          <>
            <h1>{overview.doctor}</h1>
            <p className="pp-muted">Practice {overview.practice_number}</p>
          </>
        )}
      </header>

      {error && <p className="pp-error">{error}</p>}
      {sent && <p className="pp-ok">{sent}</p>}

      <section className="pp-card">
        <h2>Send a prescription</h2>
        {!session ? (
          <>
            <p className="pp-muted">{overview?.note}</p>
            <form onSubmit={signIn}>
              <label>
                Practice number
                <input
                  value={login.practice_number}
                  onChange={(e) => setLogin({ ...login, practice_number: e.target.value })}
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="current-password"
                  value={login.password}
                  onChange={(e) => setLogin({ ...login, password: e.target.value })}
                  required
                />
              </label>
              <button disabled={busy}>{busy ? "Signing in…" : "Sign in to prescribe"}</button>
            </form>
          </>
        ) : (
          <form onSubmit={submit}>
            <p className="pp-muted">Signed in as {session.doctor}</p>
            <label>
              Patient number
              <input value={patientId} inputMode="numeric"
                onChange={(e) => setPatientId(e.target.value)} required />
            </label>
            {lines.map((l, i) => (
              <div className="pp-line" key={i}>
                <label>
                  Product code
                  <input value={l.product_id} inputMode="numeric"
                    onChange={(e) => setLine(i, { product_id: e.target.value })} required />
                </label>
                <label>
                  Directions
                  <input value={l.dosage_instructions}
                    onChange={(e) => setLine(i, { dosage_instructions: e.target.value })}
                    placeholder="One twice daily" required />
                </label>
                <label>
                  Quantity
                  <input value={l.quantity} inputMode="numeric"
                    onChange={(e) => setLine(i, { quantity: e.target.value })} required />
                </label>
                <label>
                  Repeats
                  <input value={l.repeats_allowed} inputMode="numeric"
                    onChange={(e) => setLine(i, { repeats_allowed: e.target.value })} />
                </label>
              </div>
            ))}
            <button type="button" className="pp-ghost"
              onClick={() => setLines((all) => [...all, { ...BLANK }])}>
              Add another medicine
            </button>
            <label>
              Notes for the pharmacist
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
            </label>
            <button disabled={busy}>{busy ? "Sending…" : "Send to pharmacy"}</button>
            <p className="pp-fine">
              The pharmacist reviews every script before it is dispensed. They can
              substitute a product they stock.
            </p>
          </form>
        )}
      </section>

      <section className="pp-card">
        <h2>Your recent scripts here</h2>
        {overview?.scripts.length ? (
          <ul className="pp-items">
            {overview.scripts.map((s) => (
              <li key={s.rx_number}>
                <div className="pp-row">
                  <b>{s.patient}</b>
                  <span className={`pp-tag ${s.collected ? "ok" : ""}`}>{s.status}</span>
                </div>
                <div className="pp-muted">{s.rx_number} · {s.date}</div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="pp-muted">Nothing from this practice yet.</p>
        )}
      </section>

      <footer className="pp-foot">
        Prescriptions sent here are reviewed by a pharmacist before dispensing.
      </footer>
    </div>
  );
}
