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
import { useCallback, useEffect, useRef, useState } from "react";
import SectionNav from "../components/SectionNav";
import { CLAIMING_TABS } from "../reconTabs";
import { api, errorText, fmtDate, money } from "../api";
import { useConfirm } from "../components/Confirm";
import LookupInput, { LookupItem } from "../components/LookupInput";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Pagination, { Paged } from "../components/Pagination";
import { useDebounced } from "../hooks/useDebounced";
import { Patient, Product } from "../types";

interface Use {
  // `created_at`, not `at`. The field was declared as `at` here and the server
  // has always sent `created_at`, so every draw's date was undefined — which
  // nothing noticed, because nothing rendered a draw.
  id: number; quantity: number; amount: number; reference: string;
  created_at?: string; claim_id?: number | null; reversed?: boolean;
}
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

/** Look up ICD-10 codes for the picker.
 *
 *  Outside the component so it keeps its identity between renders — passed in
 *  as a prop, a function rebuilt every render would restart the debounce on
 *  every keystroke and the list would never settle.
 */
async function searchDiagnoses(q: string): Promise<LookupItem[]> {
  const rows = await api.get<{
    id: number; code: string; description: string;
    chapter: string; valid_primary: boolean;
  }[]>(`/api/claiming/diagnoses?q=${encodeURIComponent(q)}&limit=25`);
  return rows.map((r) => ({
    value: r.code,
    label: r.description,
    // Said where it matters rather than everywhere: a code that cannot be a
    // primary diagnosis is the one that comes back rejected.
    hint: r.valid_primary ? r.chapter : `${r.chapter} · not valid as a primary diagnosis`,
    usable: true,
  }));
}

export default function Authorisations() {
  const toast = useToast();
  const confirm = useConfirm();
  const [rows, setRows] = useState<Auth[] | null>(null);
  const [meta, setMeta] = useState<Paged<Auth> | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  const [search, setSearch] = useState("");
  // The server does the narrowing, and only once the typing stops.
  const settled = useDebounced(search);
  const [busy, setBusy] = useState("");
  const [showUses, setShowUses] = useState<number | null>(null);
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
    api.get<Paged<Auth>>(
      `/api/authorisations/paged?page=${page}&per_page=${perPage}`
      + `&q=${encodeURIComponent(settled)}`)
      .then((res) => {
        // The previous page stays on screen until the next one arrives, so
        // paging never blanks the table or collapses its height.
        setRows(res.items);
        setMeta(res);
        if (res.page !== page) setPage(res.page);
      })
      .catch((e) => toast.error(errorText(e, "The authorisations could not be listed.")));
  }, [toast, page, perPage, settled]);

  useEffect(load, [load]);

  // A new search on page 7 of a set that now has two pages shows nothing at all.
  const firstSearch = useRef(true);
  useEffect(() => {
    if (firstSearch.current) { firstSearch.current = false; return; }
    setPage(1);
  }, [settled]);

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
        // Which member on the policy. A family shares one policy number and the
        // dependent code is what tells the funder whether this is the principal
        // or a child — it is already on the patient record, and was simply not
        // being sent, so every authorisation went up as the principal member.
        dependent_code: patient?.dependent_code ?? "",
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
        ? `${made.reference} approved${made.authorisation_number ? `, number ${made.authorisation_number}` : ""}.`
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
        toast.ok(`Usable, ${res.quantity_remaining} left`
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

  /** Give back what a reversed sale had drawn.
   *
   *  When a sale is voided the medicine comes back over the counter, and if the
   *  authorisation is not released with it the patient has silently lost cover
   *  they never received. It surfaces months later as a refusal nobody can
   *  explain. The endpoint has existed since authorisations were written; the
   *  draws it releases were fetched by this screen, typed in this file, and
   *  never once rendered, so there was nothing to press.
   */
  async function release(a: Auth, use: Use) {
    const ok = await confirm({
      title: `Give back ${use.quantity} on ${a.reference}?`,
      body: (
        <>
          This puts {use.quantity} unit{use.quantity === 1 ? "" : "s"}
          {use.amount > 0 ? <> and {money(use.amount)}</> : null} back on the
          authorisation, for a sale that was reversed. Do it when the medicine
          came back — not to correct a mistyped quantity, which is a fresh draw
          of the difference.
        </>
      ),
      confirmLabel: "Give it back",
    });
    if (!ok) return;
    setBusy(`release-${a.id}-${use.reference}`);
    try {
      const q = use.claim_id
        ? `claim_id=${use.claim_id}`
        : `reference=${encodeURIComponent(use.reference)}`;
      const r = await api.post<{ released: number }>(
        `/api/authorisations/${a.id}/release?${q}`, {});
      toast.ok(r.released
        ? `Given back on ${a.reference}.`
        : "Nothing was outstanding against that reference.");
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be given back."));
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
        <div className="page-actions">
          <SectionNav tabs={CLAIMING_TABS} end="/claiming" />
          <input
            className="page-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search reference, number or item"
          />
          <button className="btn primary" onClick={() => setAsking(true)}>
            Request an authorisation
          </button>
        </div>
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
                  <th>Valid to</th><th className="num">Left</th><th className="actions" />
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
                        <span className="clip" title={a.description}>
                          {a.description || <span className="muted">—</span>}
                        </span>
                        {a.icd10_code && <div className="muted mono small">{a.icd10_code}</div>}
                      </td>
                      <td>
                        <span className={`badge ${badge(state)}`}>{state}</span>
                        {/* The reason a funder gave for refusing is the whole
                            value of a refusal — it says what to fix and resubmit.   */}
                        {!live && a.decision_reason && (
                          <div className="muted small clip-2" title={a.decision_reason}>
                            {a.decision_reason}
                          </div>
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
                        {a.uses.length > 0 && (
                          <button className="small ghost"
                                  onClick={() => setShowUses(
                                    showUses === a.id ? null : a.id)}>
                            {showUses === a.id ? "Hide draws"
                              : `${a.uses.length} draw${a.uses.length === 1 ? "" : "s"}`}
                          </button>
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
                {/* The draws, under the authorisation they came out of.
                    Rendered as a second row rather than a modal: the question
                    "what used this up" is asked while looking at "3 of 10
                    left", and a dialog takes that figure off the screen. */}
                {rows.filter((a) => showUses === a.id).map((a) => (
                  <tr key={`uses-${a.id}`} className="auth-uses">
                    <td colSpan={7}>
                      <table className="dt sub">
                        <thead>
                          <tr>
                            <th>Reference</th><th>When</th>
                            <th className="num">Quantity</th>
                            <th className="num">Amount</th>
                            <th className="actions" />
                          </tr>
                        </thead>
                        <tbody>
                          {a.uses.map((u, i) => (
                            <tr key={u.id ?? i} className={u.reversed ? "is-off" : ""}>
                              <td className="mono">{u.reference || "—"}</td>
                              <td>{u.created_at ? fmtDate(u.created_at) : "—"}</td>
                              <td className="num">{u.quantity}</td>
                              <td className="num">
                                {u.amount > 0 ? money(u.amount)
                                  : <span className="muted">—</span>}
                              </td>
                              <td className="actions">
                                {u.reversed ? (
                                  <span className="badge muted">given back</span>
                                ) : !u.reference && !u.claim_id ? (
                                  // Release works by reference or by claim, and
                                  // this draw carries neither, so the button
                                  // could only ever report that it found
                                  // nothing. Say why instead of offering it.
                                  <span className="muted small">
                                    no reference to give back against
                                  </span>
                                ) : (
                                  <button className="small ghost"
                                    disabled={busy === `release-${a.id}-${u.reference}`}
                                    onClick={() => release(a, u)}>
                                    Give it back
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {meta && (
          <Pagination
            meta={meta}
            onPage={setPage}
            onPerPage={(n) => { setPerPage(n); setPage(1); }}
            noun="authorisations"
          />
        )}
      </div>

      {asking && (
        <div className="modal-backdrop" onClick={() => setAsking(false)}>
          <form className="modal lb-modal" onClick={(e) => e.stopPropagation()} onSubmit={request}>
            <h2>Request an authorisation</h2>
            <p className="muted">
              Sent to the funder for a decision. An approval comes back with a
              quantity, an amount and dates it is valid between, all of which the
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
                {/* Searched, not remembered. "e.g. E11.9" asked somebody to
                    recall a code, and the ones people recall are the three they
                    always use — whether or not those fit this patient. There is
                    no "add new" here on purpose: a pharmacy may decide what it
                    calls an allergy, it may not invent a diagnosis code, and an
                    invented one fails weeks later as a rejected claim. */}
                <LookupInput
                  value={icd10}
                  onChange={setIcd10}
                  placeholder="Search by code or condition"
                  emptyLabel="No diagnosis matches that."
                  search={searchDiagnoses}
                />
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
              {" "}Recording a draw is what keeps the balance honest, an
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
