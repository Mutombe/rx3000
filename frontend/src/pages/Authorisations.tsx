/** Pre-authorisations: what a funder has agreed to cover, and what is left of it.
 *
 *  Six endpoints, no screen. The model's own note is the reason this page is
 *  shaped the way it is: "an authorisation is not a number to file against a
 *  claim — it is a promise with an expiry date and a balance. A pharmacy that
 *  stores only the number will dispense against an authorisation that has run
 *  out or lapsed, and find out when the claim is rejected weeks later."
 *
 *  So the balance is the headline on every row, not the number. An approval for
 *  six repeats with five drawn is nearly spent, and that is what somebody
 *  standing at the counter needs to see before handing over the sixth.
 *
 *  `effective_status` rather than `status`, everywhere. A row can be approved
 *  and expired at the same time; the server works out which of those actually
 *  governs, and a screen that showed the stored status would show "approved"
 *  over an authorisation that lapsed last month.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Patient, Product } from "../types";

interface Use { quantity: number; amount: number; reference: string; at?: string }
interface Auth {
  id: number; reference: string; authorisation_number: string;
  funder_id: string; policy_number: string; description: string;
  icd10_code: string; requested_quantity: number; requested_amount: number;
  currency_code: string; valid_from: string | null; valid_to: string | null;
  status: string; effective_status: string; decision_reason: string;
  conditions: string; created_at: string | null;
  quantity_authorised: number; quantity_used: number; quantity_remaining: number;
  amount_authorised: number; amount_used: number; amount_remaining: number;
  uses: Use[];
}
interface Check {
  usable: boolean; status: string; reasons: string[];
  quantity_remaining: number; amount_remaining: number;
  valid_to: string | null;
}

export default function Authorisations() {
  const toast = useToast();
  const confirm = useConfirm();
  const [rows, setRows] = useState<Auth[] | null>(null);
  const [busy, setBusy] = useState("");
  const [checked, setChecked] = useState<Record<number, Check>>({});

  // requesting
  const [asking, setAsking] = useState(false);
  const [funder, setFunder] = useState("CIMAS_ZW");
  const [policy, setPolicy] = useState("");
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [productQ, setProductQ] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [icd10, setIcd10] = useState("");
  const [motivation, setMotivation] = useState("");
  const [qty, setQty] = useState("1");
  const [amount, setAmount] = useState("");

  // drawing against one
  const [using, setUsing] = useState<Auth | null>(null);
  const [useQty, setUseQty] = useState("");
  const [useAmount, setUseAmount] = useState("");

  const load = useCallback(() => {
    api.get<Auth[]>("/api/authorisations?limit=100")
      .then(setRows)
      .catch((e) => toast.error(errorText(e, "The authorisations could not be listed.")));
  }, [toast]);

  useEffect(load, [load]);

  useEffect(() => {
    if (patientQ.trim().length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`)
      .then(setPatients).catch(() => setPatients([]));
  }, [patientQ]);

  useEffect(() => {
    if (productQ.trim().length < 2) { setProducts([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(productQ)}&limit=6`)
      .then(setProducts).catch(() => setProducts([]));
  }, [productQ]);

  async function request(e: React.FormEvent) {
    e.preventDefault();
    setBusy("request");
    try {
      const made = await api.post<Auth>("/api/authorisations", {
        funder_id: funder.trim().toUpperCase(),
        policy_number: policy.trim(),
        patient_id: patient?.id ?? null,
        product_id: product?.id ?? null,
        description: product?.name ?? "",
        icd10_code: icd10.trim(),
        motivation: motivation.trim(),
        requested_quantity: Number(qty) || 0,
        requested_amount: Number(amount) || 0,
      });
      // The funder's answer, said plainly. A refusal is as useful as an approval
      // and there is no point dressing it up: it decides whether the patient
      // pays today.
      toast.ok(made.effective_status === "approved"
        ? `${made.reference} approved${made.authorisation_number ? ` — ${made.authorisation_number}` : ""}.`
        : `${made.reference}: ${made.effective_status}. ${made.decision_reason}`);
      setAsking(false);
      setPolicy(""); setMotivation(""); setIcd10("");
      setPatient(null); setProduct(null); setPatientQ(""); setProductQ("");
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function check(a: Auth) {
    setBusy(`check-${a.id}`);
    try {
      const res = await api.get<Check>(`/api/authorisations/${a.id}/check`);
      setChecked((c) => ({ ...c, [a.id]: res }));
      if (!res.usable) {
        toast.error(`Not usable: ${res.reasons.join(" ")}`);
      } else {
        toast.ok(`Usable — ${res.quantity_remaining} left`
          + (res.valid_to ? `, until ${fmtDate(res.valid_to)}.` : "."));
      }
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function draw(e: React.FormEvent) {
    e.preventDefault();
    if (!using) return;
    setBusy("use");
    try {
      await api.post(`/api/authorisations/${using.id}/use`, {
        quantity: Number(useQty) || 0,
        amount: Number(useAmount) || 0,
      });
      toast.ok(`Drawn against ${using.reference}.`);
      setUsing(null);
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function cancel(a: Auth) {
    const ok = await confirm({
      title: `Cancel ${a.reference}?`,
      body: `${a.description || "This authorisation"} will no longer be usable. `
          + `Anything already drawn against it stays on the record.`,
      confirmLabel: "Cancel the authorisation",
      destructive: true,
    });
    if (!ok) return;
    setBusy(`cancel-${a.id}`);
    try {
      await api.post(`/api/authorisations/${a.id}/cancel`, {});
      toast.ok(`${a.reference} cancelled.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Authorisations</h1>
          <div className="sub">
            What each funder has agreed to cover, what has been drawn against it,
            and what is left
          </div>
        </div>
        <button className="btn primary" onClick={() => setAsking(true)}>
          Request an authorisation
        </button>
      </div>

      <div className="card">
        {!rows ? <TableSkeleton cols={6} rows={6} /> : rows.length === 0 ? (
          <div className="empty">No authorisations yet.</div>
        ) : (
          <div className="cu-scroll">
            <table>
              <thead>
                <tr>
                  <th>Reference</th><th>Funder</th><th>For</th><th>Status</th>
                  <th>Valid to</th><th className="num">Left</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const state = a.effective_status || a.status;
                  const live = state === "approved";
                  const c = checked[a.id];
                  return (
                    <tr key={a.id} className={state === "declined" ? "is-off" : ""}>
                      <td>
                        <span className="mono">{a.reference}</span>
                        {a.authorisation_number && (
                          <div className="muted mono small">{a.authorisation_number}</div>
                        )}
                      </td>
                      <td>{a.funder_id}</td>
                      <td>
                        {a.description || <span className="muted">—</span>}
                        {a.icd10_code && <div className="muted mono small">{a.icd10_code}</div>}
                      </td>
                      <td>
                        <span className={`badge ${badge(state)}`}>{state}</span>
                        {/* The reason a funder gave for refusing is the whole
                            value of a refusal — it says what to fix and resubmit. */}
                        {!live && a.decision_reason && (
                          <div className="muted small">{a.decision_reason}</div>
                        )}
                      </td>
                      <td className={expired(a) ? "cu-diff" : ""}>
                        {a.valid_to ? fmtDate(a.valid_to) : "—"}
                      </td>
                      <td className="num">
                        {live ? (
                          <>
                            {a.quantity_remaining}
                            <span className="muted"> of {a.quantity_authorised}</span>
                            {a.amount_authorised > 0 && (
                              <div className="muted small">
                                {money(a.amount_remaining)} left
                              </div>
                            )}
                          </>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="num lb-actions">
                        <button className="small ghost" disabled={busy === `check-${a.id}`}
                          onClick={() => check(a)}>
                          {busy === `check-${a.id}` ? "Checking…" : "Check"}
                        </button>
                        {live && (
                          <>
                            <button className="small" onClick={() => {
                              setUsing(a);
                              setUseQty(String(Math.min(1, a.quantity_remaining || 1)));
                              setUseAmount("");
                            }}>
                              Draw
                            </button>
                            <button className="small ghost" disabled={busy === `cancel-${a.id}`}
                              onClick={() => cancel(a)}>
                              Cancel
                            </button>
                          </>
                        )}
                        {c && (
                          <div className={`small ${c.usable ? "" : "cu-diff"}`}>
                            {c.usable ? "usable" : c.reasons[0]}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {asking && (
        <div className="modal-backdrop" onClick={() => setAsking(false)}>
          <form className="modal lb-modal" onClick={(e) => e.stopPropagation()} onSubmit={request}>
            <h2>Request an authorisation</h2>
            <p className="muted">
              Sent to the funder for a decision. An approval comes back with a
              quantity, an amount and dates it is valid between — all of which the
              claim is later checked against.
            </p>

            <div className="form-row">
              <div className="field">
                <label>Funder</label>
                <input value={funder} onChange={(e) => setFunder(e.target.value)} required />
              </div>
              <div className="field">
                <label>Policy number</label>
                <input value={policy} onChange={(e) => setPolicy(e.target.value)} />
              </div>
            </div>

            <label>
              Patient
              {patient ? (
                <div className="st-picked">
                  <b>{patient.first_name} {patient.last_name}</b>
                  <button type="button" className="btn ghost small"
                    onClick={() => { setPatient(null); setPatientQ(""); }}>Change</button>
                </div>
              ) : (
                <input value={patientQ} onChange={(e) => setPatientQ(e.target.value)}
                  placeholder="Search by name" />
              )}
            </label>
            {!patient && patients.length > 0 && (
              <ul className="st-results">
                {patients.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => { setPatient(p); setPatients([]); }}>
                      {p.first_name} {p.last_name}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <label>
              Medicine or item
              {product ? (
                <div className="st-picked">
                  <b>{product.name}</b>
                  <button type="button" className="btn ghost small"
                    onClick={() => { setProduct(null); setProductQ(""); }}>Change</button>
                </div>
              ) : (
                <input value={productQ} onChange={(e) => setProductQ(e.target.value)}
                  placeholder="Search for a product" />
              )}
            </label>
            {!product && products.length > 0 && (
              <ul className="st-results">
                {products.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => {
                      setProduct(p); setProducts([]);
                      if (!amount) setAmount(String(p.unit_price));
                    }}>
                      {p.name}<span className="muted"> {money(p.unit_price)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="form-row">
              <div className="field">
                <label>Diagnosis (ICD-10)</label>
                <input value={icd10} onChange={(e) => setIcd10(e.target.value)}
                  placeholder="e.g. E11.9" />
              </div>
              <div className="field">
                <label>Quantity</label>
                <input type="number" min="0" step="1" value={qty}
                  onChange={(e) => setQty(e.target.value)} />
              </div>
              <div className="field">
                <label>Amount</label>
                <input type="number" min="0" step="0.01" value={amount}
                  onChange={(e) => setAmount(e.target.value)} />
              </div>
            </div>

            <label>
              Motivation
              <textarea rows={3} value={motivation} onChange={(e) => setMotivation(e.target.value)}
                placeholder="Why this is needed. A funder refusing for want of a reason is the commonest avoidable refusal." />
            </label>

            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setAsking(false)}>
                Cancel
              </button>
              <button type="submit" className="btn primary" disabled={busy === "request"}>
                {busy === "request" ? "Asking…" : "Send the request"}
              </button>
            </div>
          </form>
        </div>
      )}

      {using && (
        <div className="modal-backdrop" onClick={() => setUsing(null)}>
          <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={draw}>
            <h2>Draw against {using.reference}</h2>
            <p className="muted">
              {using.quantity_remaining} of {using.quantity_authorised} left
              {using.amount_authorised > 0
                ? `, ${money(using.amount_remaining)} of ${money(using.amount_authorised)}.`
                : "."}
              {" "}Recording a draw is what keeps the balance honest — an
              authorisation drawn but not recorded is one the next dispenser
              believes is still available.
            </p>
            <div className="form-row">
              <div className="field">
                <label>Quantity</label>
                <input type="number" min="0" step="1" value={useQty} autoFocus
                  onChange={(e) => setUseQty(e.target.value)} />
              </div>
              <div className="field">
                <label>Amount <span className="muted">(optional)</span></label>
                <input type="number" min="0" step="0.01" value={useAmount}
                  onChange={(e) => setUseAmount(e.target.value)} />
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setUsing(null)}>Cancel</button>
              <button type="submit" className="btn primary" disabled={busy === "use"}>
                {busy === "use" ? "Recording…" : "Record the draw"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}

function badge(state: string): string {
  if (state === "approved") return "ok";
  if (state === "declined" || state === "cancelled") return "danger";
  if (state === "expired" || state === "exhausted") return "warn";
  return "muted";
}

function expired(a: Auth): boolean {
  return !!a.valid_to && new Date(a.valid_to) < new Date()
    && a.effective_status === "approved";
}
