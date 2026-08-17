import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import DispensaryWorklist from "../components/DispensaryWorklist";
import { Link, useSearchParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import AiOutput from "../components/AiOutput";
import CounterMessages from "../components/CounterMessages";
import DiagnosisPicker from "../components/DiagnosisPicker";
import KeyMap, { KeyBar } from "../components/KeyMap";
import LabelSheet from "../components/LabelSheet";
import SigInput from "../components/SigInput";
import { Hotkey, useHotkeys } from "../hooks/useHotkeys";
import { printLabels } from "../print";
import {
  ControlledDispensing, CoverageReport, Doctor, Label, OTCSale, Patient,
  Prescription, PrescriptionItem, Product, Sale, SchedulePolicy, User,
} from "../types";

type Route = "prescription" | "controlled" | "otc";
type RailKey = "due" | "recent" | "log" | "rules";

interface DraftItem {
  product: Product;
  quantity: number;
  dosage_instructions: string;
  repeats_allowed: number;
  repeat_interval_days: number;
  auto_refill: boolean;
  /** Diagnosis for this line. A claim line without one is rejected. */
  icd10_code: string;
}

const ROUTE_TABS: { key: Route; label: string; hint: string }[] = [
  { key: "prescription", label: "Prescription (S3–S4)", hint: "Ordinary prescription medicine" },
  { key: "controlled", label: "⚠ Dangerous Drugs (S5–S6)", hint: "Controlled substances — full compliance record required" },
  { key: "otc", label: "OTC / Pharmacy Medicine (S0–S2)", hint: "Counter sale, no prescription" },
];

export default function Dispense() {
  const [route, setRoute] = useState<Route>("prescription");
  const [policies, setPolicies] = useState<SchedulePolicy[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const toast = useToast();

  // shared patient picker
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);

  // script capture
  const [doctorId, setDoctorId] = useState<number | "">("");
  const [productQ, setProductQ] = useState("");
  const [productResults, setProductResults] = useState<Product[]>([]);
  const [items, setItems] = useState<DraftItem[]>([]);
  const [aiResult, setAiResult] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [doneSale, setDoneSale] = useState<Sale | null>(null);
  const [doneRxId, setDoneRxId] = useState<number | null>(null);
  // ?reprint=<rx id> opens the label preview straight away. Without it a reprint
  // is only reachable in the moments after dispensing, in the same browser
  // session — so nobody could reprint a label for yesterday's script, which is
  // when labels are actually asked for again.
  const [params, setParams] = useSearchParams();
  const [reprintRx, setReprintRx] = useState<number | null>(() => {
    const n = Number(params.get("reprint"));
    return Number.isFinite(n) && n > 0 ? n : null;
  });

  function closeReprint() {
    setReprintRx(null);
    if (params.has("reprint")) {
      // Clear it, or a refresh reopens a dialog the user just dismissed.
      const next = new URLSearchParams(params);
      next.delete("reprint");
      setParams(next, { replace: true });
    }
  }

  // controlled compliance
  const [idVerified, setIdVerified] = useState(false);
  const [idNumber, setIdNumber] = useState("");
  const [scriptSighted, setScriptSighted] = useState(false);
  const [prescriberVerified, setPrescriberVerified] = useState(false);
  // Initials of the pharmacist who checked the dispensing. This replaced the
  // independent-witness selector: the server now asks for initials wherever it
  // used to ask for a second member of staff.
  const [initials, setInitials] = useState("");
  const [complianceNotes, setComplianceNotes] = useState("");
  const [controlledLog, setControlledLog] = useState<ControlledDispensing[]>([]);

  // OTC
  const [otcProduct, setOtcProduct] = useState<Product | null>(null);
  const [otcQty, setOtcQty] = useState(1);
  const [customerName, setCustomerName] = useState("");
  const [indication, setIndication] = useState("");
  const [counselled, setCounselled] = useState(false);
  const [referred, setReferred] = useState(false);
  const [otcNotes, setOtcNotes] = useState("");
  const [tendered, setTendered] = useState("");
  const [otcLog, setOtcLog] = useState<OTCSale[]>([]);

  const [recent, setRecent] = useState<Prescription[]>([]);
  const [moreRecent, setMoreRecent] = useState(false);
  const [repeatsDue, setRepeatsDue] = useState<PrescriptionItem[]>([]);

  // The side rail shows one list at a time; which lists are offered depends on
  // the dispensing route, so the selection resets whenever the route changes.
  const [rail, setRail] = useState<RailKey>("due");
  const railTabs: { key: RailKey; label: string; count?: number }[] =
    route === "controlled"
      ? [{ key: "log", label: "Hand-over log", count: controlledLog.length },
         { key: "rules", label: "Schedule rules" }]
      : [{ key: "due", label: "Repeats due", count: repeatsDue.length },
         { key: "recent", label: "Recent scripts", count: recent.length },
         { key: "rules", label: "Schedule rules" }];

  useEffect(() => {
    setRail(route === "controlled" ? "log" : "due");
  }, [route]);

  useEffect(() => {
    api.get<SchedulePolicy[]>("/api/dispensing/policy").then(setPolicies);
    api.get<Doctor[]>("/api/doctors").then(setDoctors);
    api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {});
    loadLists();
  }, []);

  function loadLists() {
    api.get<Prescription[]>("/api/prescriptions?limit=12").then(setRecent);
    // Ask for one more than is shown. If it comes back there are more, which
    // is all the screen needs to say — a truthful "there is more" beats a
    // precise total that costs another endpoint, and beats silence entirely.
    api.get<Prescription[]>("/api/prescriptions?limit=13")
      .then((all) => setMoreRecent(all.length > 12)).catch(() => setMoreRecent(false));
    api.get<PrescriptionItem[]>("/api/repeats/due?days=14").then(setRepeatsDue);
    api.get<ControlledDispensing[]>("/api/dispensing/controlled/log?days=90").then(setControlledLog);
    api.get<OTCSale[]>("/api/dispensing/otc?days=30").then(setOtcLog);
  }

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=8`).then(setPatients);
  }, [patientQ]);

  useEffect(() => {
    setItems([]); setProductQ(""); setProductResults([]); setAiResult("");
  }, [route]);

  useEffect(() => {
    if (productQ.length < 2) { setProductResults([]); return; }
    api.get<Product[]>(`/api/dispensing/products?route=${route}&q=${encodeURIComponent(productQ)}`)
      .then(setProductResults);
  }, [productQ, route]);

  useEffect(() => {
    if (route !== "otc" || productQ.length >= 2) return;
    api.get<Product[]>("/api/dispensing/products?route=otc&limit=12").then(setProductResults);
  }, [route, productQ]);

  const policyFor = (schedule: number) => policies.find((p) => p.schedule === schedule);
  const highestSchedule = items.reduce((m, i) => Math.max(m, i.product.schedule || 0), 0);
  const activePolicy = policyFor(highestSchedule);
  // The policy field is still called requires_witness — it is the jurisdiction
  // pack's name for "this needs a second signature". What satisfies it is now
  // the checking pharmacist's initials.
  const needsInitials = items.some((i) => policyFor(i.product.schedule)?.requires_witness);

  const [showKeys, setShowKeys] = useState(false);
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  // A blocking counter message stops the dispense. The server enforces this
  // too; the button is disabled so the pharmacist is not invited to try.
  const [blocked, setBlocked] = useState(false);

  // Check the scheme's formulary while the script is being built, not at claim
  // time — by then the medicine has left the shelf and the patient has gone.
  useEffect(() => {
    if (!patient?.medical_aid_id || items.length === 0) { setCoverage(null); return; }
    const t = setTimeout(() => {
      api.post<CoverageReport>("/api/claiming/coverage", {
        medical_aid_id: patient.medical_aid_id,
        items: items.map((i) => ({ product_id: i.product.id, quantity: i.quantity })),
      }).then(setCoverage).catch(() => setCoverage(null));
    }, 350);
    return () => clearTimeout(t);
  }, [patient?.medical_aid_id, items.map((i) => `${i.product.id}:${i.quantity}`).join(",")]);

  const coverageFor = (productId: number) =>
    coverage?.lines.find((l) => l.product_id === productId) ?? null;

  /** Swap a line for a covered alternative on the same molecule. */
  function substitute(idx: number, productId: number) {
    api.get<Product>(`/api/products/${productId}`).then((p) => {
      const detail = (p as any).product ?? p;
      setItems((current) => current.map((it, i) =>
        (i === idx ? { ...it, product: detail } : it)));
    }).catch((e) => toast.error(errorText(e)));
  }
  // Declared below; read lazily so the binding always sees the current value.
  const complianceReadyRef = () =>
    !blocked &&
    (route !== "controlled" ||
    (items.length > 0 && idVerified && scriptSighted && prescriberVerified &&
      (!needsInitials || initials.trim() !== "")));

  // One declaration drives the bindings, the bottom bar and the help overlay,
  // so a shortcut can never exist without being documented.
  const hotkeys: Hotkey[] = [
    { combo: "F2", label: "Find patient", group: "Capture",
      run: () => document.querySelector<HTMLInputElement>("[data-hk='patient']")?.focus() },
    { combo: "F3", label: "Add medicine", group: "Capture",
      run: () => document.querySelector<HTMLInputElement>("[data-hk='product']")?.focus() },
    { combo: "F4", label: "Diagnosis", group: "Capture",
      disabled: items.length === 0,
      run: () => document.querySelector<HTMLInputElement>("[data-hk='dx']")?.focus() },
    { combo: "F6", label: "Interaction check", group: "Safety",
      disabled: !patient || items.length === 0 || aiBusy, run: checkInteractions },
    { combo: "F8", label: "Repeats due", group: "Lists",
      disabled: route === "controlled", run: () => setRail("due") },
    { combo: "F9", label: "Recent scripts", group: "Lists",
      disabled: route === "controlled", run: () => setRail("recent") },
    { combo: "F12", label: "Dispense", group: "Finish",
      disabled: busy || !patient || items.length === 0 || !complianceReadyRef(),
      run: () => { if (!busy && patient && items.length && complianceReadyRef()) createAndDispense(); } },
    { combo: "Escape", label: "Clear the script", group: "Finish",
      disabled: items.length === 0, run: () => setItems([]) },
    { combo: "?", label: "Show this key map", group: "Finish", run: () => setShowKeys(true) },
  ];
  useHotkeys(hotkeys);

  const complianceReady =
    route !== "controlled" ||
    (items.length > 0 && idVerified && scriptSighted && prescriberVerified &&
      (!needsInitials || initials.trim() !== ""));

  function addItem(p: Product) {
    if (items.some((i) => i.product.id === p.id)) return;
    const pol = policyFor(p.schedule || 0);
    const maxRepeats = pol && pol.max_repeats >= 0 ? pol.max_repeats : 6;
    setItems([...items, {
      product: p, quantity: 1, dosage_instructions: "",
      repeats_allowed: Math.min(0, maxRepeats), repeat_interval_days: 30, auto_refill: false,
      // Carry the diagnosis down from the previous line — a script usually
      // treats one condition, so re-typing it on every item is wasted keystrokes.
      icd10_code: items.length ? items[items.length - 1].icd10_code : "",
    }]);
    setProductQ(""); setProductResults([]); setAiResult("");
  }

  const updateItem = (idx: number, patch: Partial<DraftItem>) =>
    setItems(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  async function printRxLabels(rxId: number) {
    try {
      printLabels(await api.get<Label[]>(`/api/prescriptions/${rxId}/labels`));
    } catch (e: any) { toast.error(errorText(e)); }
  }

  async function checkInteractions() {
    if (!patient || items.length === 0) return;
    setAiBusy(true); setAiResult("");
    try {
      const res = await api.post<{ text: string }>("/api/ai/interaction-check", {
        patient_id: patient.id, product_ids: items.map((i) => i.product.id),
      });
      setAiResult(res.text);
    } catch (e: any) { setAiResult(`Error: ${e.message}`); } finally { setAiBusy(false); }
  }

  function compliancePayload() {
    return route === "controlled"
      ? {
          id_verified: idVerified, id_number_seen: idNumber, script_sighted: scriptSighted,
          prescriber_verified: prescriberVerified,
          pharmacist_initial: initials.trim(),
          compliance_notes: complianceNotes,
        }
      : {};
  }

  async function createAndDispense() {
    if (!patient || doctorId === "" || items.length === 0) {
      toast.error("Select a patient, a doctor and at least one medication.");
      return;
    }
    setBusy(true);
    try {
      const rx = await api.post<Prescription>("/api/prescriptions", {
        patient_id: patient.id, doctor_id: doctorId,
        items: items.map((i) => ({
          product_id: i.product.id, quantity: i.quantity,
          dosage_instructions: i.dosage_instructions, repeats_allowed: i.repeats_allowed,
          repeat_interval_days: i.repeat_interval_days, auto_refill: i.auto_refill,
          icd10_code: i.icd10_code,
        })),
      });
      const sale = await api.post<Sale>(`/api/prescriptions/${rx.id}/dispense`, {
        item_ids: rx.items.map((i) => i.id), ...compliancePayload(),
      });
      setDoneSale(sale); setDoneRxId(rx.id);
      setItems([]); setAiResult("");
      setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
      setInitials(""); setIdNumber(""); setComplianceNotes("");
      loadLists();
      printRxLabels(rx.id);
    } catch (e: any) { toast.error(errorText(e)); } finally { setBusy(false); }
  }

  async function dispenseRepeat(item: PrescriptionItem) {
    if (!item.prescription) return;
    try {
      const sale = await api.post<Sale>(`/api/prescriptions/${item.prescription.id}/dispense`, {
        item_ids: [item.id],
      });
      setDoneSale(sale); setDoneRxId(item.prescription.id);
      loadLists();
      printRxLabels(item.prescription.id);
    } catch (e: any) { toast.error(errorText(e)); }
  }

  async function sellOtc() {
    if (!otcProduct) return;
    setBusy(true);
    try {
      const record = await api.post<OTCSale>("/api/dispensing/otc", {
        product_id: otcProduct.id, quantity: otcQty, patient_id: patient?.id ?? null,
        customer_name: customerName, indication, counselling_given: counselled,
        referred_to_doctor: referred, notes: otcNotes,
        payment_method: "cash", amount_tendered: Number(tendered) || 0,
      });
      setOtcProduct(null); setOtcQty(1); setCustomerName(""); setIndication("");
      setCounselled(false); setReferred(false); setOtcNotes(""); setTendered("");
      loadLists();
      alert(`Sold — ${record.quantity} × ${record.product?.name}. Recorded in the pharmacy-medicine register.`);
    } catch (e: any) { toast.error(errorText(e)); } finally { setBusy(false); }
  }

  const otcTotal = otcProduct ? otcProduct.unit_price * otcQty : 0;
  const otcPolicy = otcProduct ? policyFor(otcProduct.schedule || 0) : undefined;

  return (
    <>
      <KeyMap keys={hotkeys} open={showKeys} onClose={() => setShowKeys(false)} />
      <div className="page-head">
        <div>
          <h1>Dispensary</h1>
          <div className="sub">
            {ROUTE_TABS.find((t) => t.key === route)?.hint}
          </div>
        </div>
      </div>

      {/* Work on the left, worklist on the right. The queue has to be in view
          while dispensing happens — a panel you navigate to is a panel checked
          twice a day. It stacks below laptop width, where a 320px column would
          leave no room for the work itself. */}
      <div className="disp-with-worklist">
      <div>
      {reprintRx !== null && (
        <LabelSheet rxId={reprintRx} onClose={closeReprint} />
      )}

      {doneSale && (
        <div className="success-banner">
          Dispensed — invoice <b>{doneSale.sale_number}</b> for {money(doneSale.total)} is pending payment.
          Labels sent to the printer.{" "}
          {/* A reprint gets the preview: whoever is asking for one already had a
              set come out, so the question now is how many and for which item —
              not "print immediately", which is what already happened. */}
          {doneRxId && <button className="ghost small" onClick={() => setReprintRx(doneRxId)}>🖨 Reprint labels</button>}
          {" "}<Link to="/pos">Settle at Point of Sale →</Link>
        </div>
      )}

      <div className="pill-tabs">
        {ROUTE_TABS.map((t) => (
          <button key={t.key} className={route === t.key ? "active" : ""} onClick={() => setRoute(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {route === "otc" ? (
        <div className="grid cols-2">
          <div>
            <div className="card">
              <h3>1 · Choose a pharmacy medicine</h3>
              <input data-hk="product" type="search" placeholder="Search S0–S2 medicines…" value={productQ}
                onChange={(e) => setProductQ(e.target.value)} />
              {productResults.map((p) => (
                <div key={p.id} className="product-pick" onClick={() => setOtcProduct(p)}
                  style={otcProduct?.id === p.id ? { background: "#fff", borderColor: "var(--accent)" } : undefined}>
                  <span>
                    <b>{p.name}</b> {p.strength}
                    <span className={`badge ${p.schedule > 0 ? "warn" : "muted"}`} style={{ marginLeft: 6 }}>
                      S{p.schedule}
                    </span>
                  </span>
                  <span className="muted">{money(p.unit_price)} · {p.quantity_on_hand} on hand</span>
                </div>
              ))}
              {otcPolicy && (
                <div className={otcPolicy.counselling_required ? "error-banner" : "success-banner"} style={{ marginTop: 14 }}>
                  <b>{otcPolicy.label}.</b> {otcPolicy.notes}
                </div>
              )}
            </div>

            <div className="card">
              <h3>2 · Consultation record</h3>
              <div className="form-row">
                <div className="field" style={{ maxWidth: 110 }}>
                  <label>Quantity</label>
                  <input type="number" min={1} value={otcQty} onChange={(e) => setOtcQty(Math.max(1, Number(e.target.value)))} />
                </div>
                <div className="field">
                  <label>Customer name (if not a registered patient)</label>
                  <input value={customerName} onChange={(e) => setCustomerName(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label>Link a registered patient (optional)</label>
                {patient ? (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <b>{patient.first_name} {patient.last_name}</b>
                    {patient.allergies && <span className="badge danger">⚠ {patient.allergies}</span>}
                    <button className="ghost small" onClick={() => setPatient(null)}>Remove</button>
                  </div>
                ) : (
                  <>
                    <input data-hk="patient" type="search" placeholder="Search patient…" value={patientQ}
                      onChange={(e) => setPatientQ(e.target.value)} />
                    {patients.map((p) => (
                      <div key={p.id} className="product-pick"
                        onClick={() => { setPatient(p); setPatients([]); setPatientQ(""); }}>
                        <span>{p.last_name}, {p.first_name}</span>
                        <span className="muted">{p.phone}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
              <div className="field">
                <label>Presenting complaint / indication</label>
                <input value={indication} onChange={(e) => setIndication(e.target.value)}
                  placeholder="e.g. Headache for 2 days, no red flags" />
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <input type="checkbox" checked={counselled} onChange={(e) => setCounselled(e.target.checked)} />
                Patient counselled on dose, duration and side effects
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <input type="checkbox" checked={referred} onChange={(e) => setReferred(e.target.checked)} />
                Referred to a doctor
              </label>
              <div className="field"><label>Notes</label>
                <textarea rows={2} value={otcNotes} onChange={(e) => setOtcNotes(e.target.value)} /></div>
              <div className="form-row">
                <div className="field">
                  <label>Cash tendered — total {money(otcTotal)}</label>
                  <input type="number" step="0.01" value={tendered} onChange={(e) => setTendered(e.target.value)} />
                </div>
              </div>
              <button onClick={sellOtc}
                disabled={busy || !otcProduct || (otcPolicy?.counselling_required && !counselled)}>
                {busy ? "Selling…" : `Sell & record${otcProduct ? ` — ${money(otcTotal)}` : ""}`}
              </button>
              {otcPolicy?.counselling_required && !counselled && (
                <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                  Counselling must be confirmed before a pharmacy medicine can be handed over.
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <h3>Pharmacy-medicine register (30 days)</h3>
            <table>
              <thead><tr><th>When</th><th>Medicine</th><th>Customer</th><th>Indication</th><th>Pharmacist</th></tr></thead>
              <tbody>
                {otcLog.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtDateTime(r.created_at)}</td>
                    <td>
                      <b>{r.product?.name}</b> ×{r.quantity}
                      <span className={`badge ${r.schedule > 0 ? "warn" : "muted"}`} style={{ marginLeft: 6 }}>S{r.schedule}</span>
                    </td>
                    <td>{r.patient ? `${r.patient.first_name} ${r.patient.last_name}` : (r.customer_name || "—")}</td>
                    <td>
                      {r.indication || "—"}
                      {r.referred_to_doctor && <div><span className="badge warn">referred to doctor</span></div>}
                    </td>
                    <td className="muted">{r.pharmacist?.full_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {otcLog.length === 0 && <div className="empty">No pharmacy-medicine sales recorded yet</div>}
          </div>
        </div>
      ) : (
        <div className="rx-split">
          <div>
            {route === "controlled" && (
              <div className="card" style={{ borderColor: "rgba(240,120,70,0.45)" }}>
                <h3>⚠ Controlled substance — dangerous drugs protocol</h3>
                <p className="muted" style={{ fontSize: 13 }}>
                  Schedule 5 and 6 medicines must be dispensed by a pharmacist, entered in the
                  electronic schedule register, and supported by a full compliance record.
                  Schedule 6 permits <b>no repeats</b> and requires the checking pharmacist’s initials.
                </p>
              </div>
            )}

            <div className="card">
              <h3>1 · Patient &amp; prescriber</h3>
              {patient ? (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <b>{patient.first_name} {patient.last_name}</b>
                    {patient.allergies && <span className="badge danger" style={{ marginLeft: 8 }}>⚠ {patient.allergies}</span>}
                    <div className="muted">
                      ID {patient.id_number || "not on file"} ·{" "}
                      {patient.medical_aid ? `${patient.medical_aid.name} #${patient.medical_aid_number}` : "Private patient"}
                    </div>
                  </div>
                  <button className="ghost small" onClick={() => setPatient(null)}>Change</button>
                </div>
              ) : (
                <>
                  <input type="search" placeholder="Search patient…" value={patientQ}
                    onChange={(e) => setPatientQ(e.target.value)} />
                  {patients.map((p) => (
                    <div key={p.id} className="product-pick"
                      onClick={() => { setPatient(p); setPatients([]); setPatientQ(""); setIdNumber(p.id_number); }}>
                      <span><b>{p.last_name}, {p.first_name}</b> <span className="muted">{p.id_number}</span></span>
                      <span className="muted">{p.medical_aid?.name ?? "Private"}</span>
                    </div>
                  ))}
                </>
              )}
              <div className="field" style={{ marginTop: 14 }}>
                <label>Prescribing doctor</label>
                <select value={doctorId} onChange={(e) => setDoctorId(e.target.value === "" ? "" : Number(e.target.value))}>
                  <option value="">Select doctor…</option>
                  {doctors.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.practice_number})</option>)}
                </select>
              </div>
            </div>

            <div className="card">
              <h3>2 · Script items {route === "controlled" && <span className="badge sched">S5–S6 only</span>}</h3>
              <input data-hk="product" type="search"
                placeholder={`Search ${route === "controlled" ? "controlled substances" : "prescription medicines"}…`}
                value={productQ} onChange={(e) => setProductQ(e.target.value)} />
              {productResults.map((p) => (
                <div key={p.id} className="product-pick" onClick={() => addItem(p)}>
                  <span>
                    <b>{p.name}</b> {p.strength} <span className="muted">{p.dosage_form}</span>
                    <span className={`badge ${p.schedule >= 5 ? "danger" : "muted"}`} style={{ marginLeft: 6 }}>S{p.schedule}</span>
                  </span>
                  <span className="muted">{money(p.unit_price)} · {p.quantity_on_hand} in stock</span>
                </div>
              ))}
              {items.map((it, idx) => {
                const pol = policyFor(it.product.schedule || 0);
                const maxRepeats = pol && pol.max_repeats >= 0 ? pol.max_repeats : 6;
                return (
                  <div key={it.product.id} style={{ borderTop: "1px solid rgba(28,29,27,0.08)", paddingTop: 12, marginTop: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <b>
                        {it.product.name} {it.product.strength}
                        <span className={`badge ${it.product.schedule >= 5 ? "danger" : "muted"}`} style={{ marginLeft: 6 }}>
                          S{it.product.schedule}{pol?.register_entry ? " · register" : ""}
                        </span>
                      </b>
                      <button className="ghost small" onClick={() => setItems(items.filter((_, i) => i !== idx))}>Remove</button>
                    </div>
                    <div className="form-row" style={{ marginTop: 8 }}>
                      <div className="field" style={{ maxWidth: 90 }}>
                        <label>Qty</label>
                        <input type="number" min={1} value={it.quantity}
                          onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })} />
                      </div>
                      <div className="field">
                        <label>Dosage instructions</label>
                        {/* Shorthand in, sentence out. `1 t tds pc` becomes the
                            line the patient reads on the label. */}
                        <SigInput
                          value={it.dosage_instructions}
                          onChange={(next) => updateItem(idx, { dosage_instructions: next })}
                        />
                      </div>
                    </div>
                    <div className="field">
                      <label>
                        Diagnosis (ICD-10)
                        {!it.icd10_code && <span className="badge warn" style={{ marginLeft: 8 }}>
                          required to claim
                        </span>}
                      </label>
                      <DiagnosisPicker autoFocus={false} value={it.icd10_code}
                        onChange={(code) => updateItem(idx, { icd10_code: code })} />
                    </div>
                    {(() => {
                      const cov = coverageFor(it.product.id);
                      if (!cov || cov.status === "unknown") return null;
                      const tone = cov.status === "covered" ? "ok"
                        : cov.status === "excluded" ? "danger" : "warn";
                      return (
                        <div className={`coverage coverage-${tone}`}>
                          <div className="coverage-head">
                            <span className={`badge ${tone}`}>
                              {cov.status === "covered" ? "on benefit"
                                : cov.status === "reference" ? "reference priced"
                                : cov.status === "authorisation" ? "authorisation required"
                                : "not on benefit"}
                            </span>
                            <span className="coverage-reason">{cov.reason}</span>
                          </div>
                          {cov.alternatives.length > 0 && (
                            <div className="coverage-alts">
                              <span className="muted">Covered alternatives:</span>
                              {cov.alternatives.map((a) => (
                                <button key={a.product_id} type="button" className="alt-chip"
                                  onClick={() => substitute(idx, a.product_id)}
                                  title={`Substitute with ${a.name}`}>
                                  {a.name} {a.strength} · {money(a.unit_price)}
                                  {a.saving > 0 && <em> saves {money(a.saving)}</em>}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })()}
                    <div className="form-row">
                      <div className="field" style={{ maxWidth: 130 }}>
                        <label>Repeats (max {maxRepeats})</label>
                        <input type="number" min={0} max={maxRepeats} value={it.repeats_allowed}
                          disabled={maxRepeats === 0}
                          onChange={(e) => updateItem(idx, {
                            repeats_allowed: Math.min(maxRepeats, Math.max(0, Number(e.target.value))),
                          })} />
                      </div>
                      <div className="field" style={{ maxWidth: 140 }}>
                        <label>Interval (days)</label>
                        <input type="number" min={1} value={it.repeat_interval_days}
                          onChange={(e) => updateItem(idx, { repeat_interval_days: Number(e.target.value) })} />
                      </div>
                      <div className="field">
                        <label>Auto-refill</label>
                        <select value={it.auto_refill ? "yes" : "no"} disabled={maxRepeats === 0}
                          onChange={(e) => updateItem(idx, { auto_refill: e.target.value === "yes" })}>
                          <option value="no">No — remind patient</option>
                          <option value="yes">Yes — prepare automatically</option>
                        </select>
                      </div>
                    </div>
                    {maxRepeats === 0 && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        Schedule {it.product.schedule}: no repeats permitted — a fresh script is required each time.
                      </div>
                    )}
                  </div>
                );
              })}
              {items.length === 0 && <div className="empty">No items added yet</div>}
            </div>

            {route === "controlled" && items.length > 0 && (
              <div className="card" style={{ borderColor: "rgba(240,120,70,0.45)" }}>
                <h3>3 · Compliance record {activePolicy && <span className="badge danger">{activePolicy.label}</span>}</h3>
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <input type="checkbox" checked={scriptSighted} onChange={(e) => setScriptSighted(e.target.checked)} />
                  Original prescription sighted and retained
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <input type="checkbox" checked={prescriberVerified} onChange={(e) => setPrescriberVerified(e.target.checked)} />
                  Prescriber and practice number verified
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <input type="checkbox" checked={idVerified} onChange={(e) => setIdVerified(e.target.checked)} />
                  Patient identity document verified
                </label>
                <div className="field">
                  <label>ID number sighted</label>
                  <input value={idNumber} onChange={(e) => setIdNumber(e.target.value)} placeholder="As per identity document" />
                </div>
                <div className="field">
                  <label>
                    Checked by (pharmacist initials)
                    {needsInitials && <span className="muted"> — required for this schedule</span>}
                  </label>
                  <input
                    value={initials} maxLength={8}
                    onChange={(e) => setInitials(e.target.value.toUpperCase())}
                    placeholder="e.g. TM"
                  />
                </div>
                <div className="field">
                  <label>Compliance notes</label>
                  <textarea rows={2} value={complianceNotes} onChange={(e) => setComplianceNotes(e.target.value)}
                    placeholder="e.g. Script filed in the S6 register folder, ref 2026/044" />
                </div>
              </div>
            )}

            {/* Warnings belong on screen while the script is being built, not
                at the moment somebody tries to finish it. */}
            <CounterMessages
              patientId={patient?.id}
              productIds={items.map((i) => i.product.id)}
              medicalAidId={patient?.medical_aid_id}
              onBlockingChange={setBlocked}
            />

            <div className="card">
              <h3>{route === "controlled" ? "4" : "3"} · Safety check &amp; dispense</h3>
              {coverage && !coverage.all_claimable && (
                <div className="error-banner">
                  {coverage.blocked_count} line{coverage.blocked_count === 1 ? "" : "s"} not covered
                  by {coverage.formulary}. Dispensing is allowed — the patient pays for
                  {coverage.blocked_count === 1 ? " it" : " them"} — but the scheme will not.
                </div>
              )}
              {coverage?.authorisation_required && coverage.all_claimable && (
                <div className="device-note">
                  One or more lines need an authorisation number from the scheme before
                  the claim will be paid.
                </div>
              )}
              <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
                <button className="secondary" onClick={checkInteractions} disabled={!patient || items.length === 0 || aiBusy}>
                  {aiBusy ? "Checking…" : "✦ AI interaction check"}
                </button>
                <button onClick={createAndDispense} disabled={busy || !patient || items.length === 0 || !complianceReady}>
                  {busy ? "Dispensing…" : `Dispense ${items.length} item${items.length === 1 ? "" : "s"}`}
                </button>
              </div>
              {!complianceReady && items.length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                  Complete every item in the compliance record before this controlled substance can be dispensed.
                </div>
              )}
              {aiResult && <AiOutput text={aiResult} title="Interaction check" />}
              <KeyBar keys={hotkeys} />
            </div>
          </div>

          <div className="rx-aside">
            <div className="pill-tabs">
              {railTabs.map((t) => (
                <button key={t.key} className={rail === t.key ? "active" : ""} onClick={() => setRail(t.key)}>
                  {t.label}
                  {t.count !== undefined && <span className="tab-count">{t.count}</span>}
                </button>
              ))}
            </div>

            {rail === "log" && (
              <div className="card">
                <table>
                  <thead><tr><th>When</th><th>Sched.</th><th>Qty</th><th>Compliance</th><th>Dispensed by</th><th>Checked by</th></tr></thead>
                  <tbody>
                    {controlledLog.map((d) => (
                      <tr key={d.id}>
                        <td>{fmtDateTime(d.dispensed_at)}</td>
                        <td><span className="badge sched">S{d.schedule}</span></td>
                        <td className="num">{d.quantity}</td>
                        <td>
                          <span className={`badge ${d.id_verified ? "ok" : "danger"}`}>ID</span>{" "}
                          <span className={`badge ${d.script_sighted ? "ok" : "danger"}`}>script</span>{" "}
                          <span className={`badge ${d.prescriber_verified ? "ok" : "danger"}`}>prescriber</span>
                          {d.id_number_seen && <div className="muted mono">{d.id_number_seen}</div>}
                        </td>
                        <td className="muted">{d.dispensed_by?.full_name}</td>
                        <td className="mono">{d.pharmacist_initial || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {controlledLog.length === 0 && <div className="empty">No controlled substances dispensed in the last 90 days</div>}
              </div>
            )}

            {rail === "due" && (
                <div className="card">
                  {repeatsDue.length === 0 && <div className="empty">No repeats due in the next 14 days</div>}
                  <table>
                    <tbody>
                      {repeatsDue.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <b>{r.product?.name} {r.product?.strength}</b>
                            <div className="muted">
                              {r.prescription?.patient ? `${r.prescription.patient.first_name} ${r.prescription.patient.last_name}` : ""} · {r.prescription?.rx_number}
                            </div>
                          </td>
                          <td>{fmtDate(r.next_repeat_date)}<div className="muted">{r.repeats_used}/{r.repeats_allowed} used</div></td>
                          <td className="right"><button className="small" onClick={() => dispenseRepeat(r)}>Dispense</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
            )}

            {rail === "recent" && (
                <div className="card">
                  <table>
                    <tbody>
                      {recent.map((rx) => (
                        <tr key={rx.id}>
                          <td>
                            <b className="mono">{rx.rx_number}</b>
                            <div className="muted">{rx.patient ? `${rx.patient.first_name} ${rx.patient.last_name}` : ""}</div>
                          </td>
                          <td>{rx.items.map((i) => i.product?.name).join(", ")}</td>
                          <td className="muted">{fmtDate(rx.date_prescribed)}</td>
                        </tr>
                      ))}
                      {moreRecent && (
                        <div className="rx-capped">
                          <span>Showing the {recent.length} most recent</span>
                          <Link to="/prescriptions">See all</Link>
                        </div>
                      )}
                    </tbody>
                  </table>
                  {recent.length === 0 && <div className="empty">No prescriptions yet</div>}
                </div>
            )}

            {rail === "rules" && (
            <div className="card">
              <table>
                <thead><tr><th>Schedule</th><th>Route</th><th>Requirements</th></tr></thead>
                <tbody>
                  {policies.map((p) => (
                    <tr key={p.schedule}>
                      <td><b>S{p.schedule}</b></td>
                      <td>
                        <span className={`badge ${p.route === "controlled" ? "danger"
                          : p.route === "prohibited" ? "danger"
                          : p.route === "prescription" ? "warn" : "ok"}`}>
                          {p.route}
                        </span>
                      </td>
                      <td style={{ fontSize: 12 }}>{p.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            )}
          </div>
        </div>
      )}
      </div>

      <DispensaryWorklist
        onPick={(row) => {
          // Load the patient the queued line belongs to. This screen captures
          // and dispenses against a patient rather than looking a script up by
          // number, so putting their record in the picker is what actually
          // starts the work — a queue you can only read is a list, not a queue.
          if (!row.patient_id) {
            toast.warn("That line has no patient attached, so it cannot be opened from here.");
            return;
          }
          api.get<Patient>(`/api/patients/${row.patient_id}`)
            .then((p) => {
              setPatient(p);
              setPatientQ("");
              setRoute(row.schedule >= 5 ? "controlled" : "prescription");
              window.scrollTo({ top: 0, behavior: "smooth" });
            })
            .catch((e) => toast.error(errorText(e, "That patient could not be opened.")));
        }}
      />
      </div>
    </>
  );
}
