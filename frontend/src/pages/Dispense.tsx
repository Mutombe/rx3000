import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import DispensaryWorklist, { WorklistPanel } from "../components/DispensaryWorklist";
import { Link, useSearchParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import AiOutput from "../components/AiOutput";
import CounterMessages from "../components/CounterMessages";
import DiagnosisPicker from "../components/DiagnosisPicker";
import KeyMap, { KeyBar } from "../components/KeyMap";
import AiPhase from "../components/AiPhase";
import InteractionPanel from "../components/InteractionPanel";
import { useAiStream } from "../hooks/useAiStream";
import { useTypewriter } from "../hooks/useTypewriter";
import LabelSheet from "../components/LabelSheet";
import SigInput from "../components/SigInput";
import Variants from "../components/Variants";
import { Hotkey, useHotkeys } from "../hooks/useHotkeys";
import { printLabels } from "../print";
import * as roll from "../shellPrinter";
import { labelLines } from "../deviceAgent";
import {
  ControlledDispensing, CoverageReport, Doctor, Label, OTCSale, Patient,
  Prescription, PrescriptionItem, Product, Sale, SchedulePolicy, User,
} from "../types";
import Pagination, { Paged } from "../components/Pagination";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import ClaudeIcon from "../components/ClaudeIcon";
import {
  ArrowRight,
  ClockCounterClockwise,
  Printer,
  Warning,
} from "@phosphor-icons/react";
import { EntityLink } from "../components/Filters";

type Route = "prescription" | "controlled" | "otc";

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
  { key: "controlled", label: "Dangerous Drugs (S5-S6)", hint: "Controlled substances, full compliance record required" },
  { key: "otc", label: "OTC / Pharmacy Medicine (S0–S2)", hint: "Counter sale, no prescription" },
];

/** What happens to the money at the moment of dispensing.
 *
 *  "Send to till" is the old behaviour and stays the default: the invoice is
 *  raised as pending and settled at the front shop, which is right when a
 *  relative is collecting, when it is going on the will-call shelf, or when the
 *  medical aid is carrying it. The others take the money here, because making
 *  somebody walk to another screen to hand over two dollars is not a workflow,
 *  it is an errand.
 */
const PAY_CHOICES = [
  { key: "till", label: "Send to till", hint: "Raise the invoice; settle at the front shop" },
  { key: "cash", label: "Cash now", hint: "Take it here and print the receipt" },
  { key: "card", label: "Card now", hint: "Take it here on the terminal" },
  { key: "mobile_money", label: "Mobile now", hint: "Take it here by EcoCash or OneMoney" },
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
  /* Interaction screening runs on every basket change, so its state lives here
     and gates the dispense button. `ixMajor` is how many major findings are
     outstanding; `ixAcknowledged` is whether the pharmacist has accepted them. */
  /* The wider read, streamed. The deterministic screen above it is the one that
     runs on every basket change and holds the dispense button; this one sees the
     whole history, the allergies and the chronic conditions, and is advisory. */
  const aiCheck = useAiStream();
  const aiShown = useTypewriter(aiCheck.text, aiCheck.streaming);
  function checkInteractions() {
    if (!patient || items.length === 0) return;
    aiCheck.run("/api/ai/interaction-check/stream", {
      patient_id: patient.id, product_ids: items.map((i) => i.product.id),
    });
  }

  const [ixMajor, setIxMajor] = useState(0);
  const [ixAcknowledged, setIxAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [doneSale, setDoneSale] = useState<Sale | null>(null);
  const [payHow, setPayHow] = useState("till");
  /** Bumped after a dispensing so the worklist reloads at once. */
  const [worklistNonce, setWorklistNonce] = useState(0);
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
  const [controlledMeta, setControlledMeta] = useState<Paged<ControlledDispensing> | null>(null);
  const [controlledPage, setControlledPage] = useState(1);
  const [otcMeta, setOtcMeta] = useState<Paged<OTCSale> | null>(null);
  const [otcPage, setOtcPage] = useState(1);

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

  // `recent`, `moreRecent` and `repeatsDue` used to live here to feed the middle
  // column. They are gone with it — including the two requests they made on
  // every load, which were fetching lists nothing rendered.

  // Which segment of the worklist is open. Held here so F8 can reach it: the
  // rail that used to sit in the middle of this page is gone, and the shortcut
  // that opened it now opens the one queue instead of a second copy of it.
  const [worklistPanel, setWorklistPanel] = useState<WorklistPanel>("queue");

  useEffect(() => {
    api.get<SchedulePolicy[]>("/api/dispensing/policy").then(setPolicies);
    api.get<Doctor[]>("/api/doctors").then(setDoctors);
    api.get<User[]>("/api/auth/users").then(setUsers).catch(() => {});
    loadLists();
  }, []);

  function loadLists() {
    // Ask for one more than is shown. If it comes back there are more, which
    // is all the screen needs to say — a truthful "there is more" beats a
    // precise total that costs another endpoint, and beats silence entirely.
    api.get<Paged<ControlledDispensing>>(
      `/api/dispensing/controlled/log/paged?days=90&page=${controlledPage}&per_page=25`)
      .then((res) => {
        setControlledLog(res.items); setControlledMeta(res);
        if (res.page !== controlledPage) setControlledPage(res.page);
      });
    api.get<Paged<OTCSale>>(`/api/dispensing/otc/paged?days=30&page=${otcPage}&per_page=25`)
      .then((res) => { setOtcLog(res.items); setOtcMeta(res); if (res.page !== otcPage) setOtcPage(res.page); });
  }

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=8`).then(setPatients);
  }, [patientQ]);

  useEffect(() => {
    setItems([]); setProductQ(""); setProductResults([]); aiCheck.reset();
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
  // Whether an initial is required is a *setting* on the server —
  // `dispensing.require_pharmacist_initial` — and when it is on it applies to
  // every dispensing, not only to controlled schedules. This screen used to
  // decide for itself from the schedule alone, so on an ordinary prescription it
  // enabled the button, never asked for initials, and the server refused the
  // dispensing with a 400 that the dispenser could do nothing about. Two rules
  // for one question, and the one the user could see was the wrong one.
  const [initialAlwaysRequired, setInitialAlwaysRequired] = useState(false);
  useEffect(() => {
    // `groups` is an object keyed by group name, each holding a list of
    // settings — not a list of groups with a `settings` field, which is what I
    // assumed first and what made this read `undefined` and quietly decide no
    // initials were needed. Written against the shape the endpoint actually
    // returns, and tolerant of either, because a wrong guess here fails silently
    // and shows up as a 400 the dispenser cannot act on.
    api.get<{ groups: Record<string, { key: string; value: unknown }[]> }>("/api/settings")
      .then((d) => {
        const groups = d.groups ?? {};
        const all = Array.isArray(groups)
          ? (groups as any[]).flatMap((g) => g?.settings ?? g ?? [])
          : Object.values(groups).flat();
        const rule = all.find((x: any) => x?.key === "dispensing.require_pharmacist_initial");
        setInitialAlwaysRequired(rule?.value === true || rule?.value === "true");
      })
      .catch(() => undefined);   // the server enforces it regardless
  }, []);

  const needsInitials =
    initialAlwaysRequired ||
    items.some((i) => policyFor(i.product.schedule)?.requires_witness);

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
    // Initials gate every route when the setting demands them.
    (!needsInitials || initials.trim() !== "") &&
    (route !== "controlled" ||
    (items.length > 0 && idVerified && scriptSighted && prescriberVerified));

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
      disabled: !patient || items.length === 0 || aiCheck.streaming, run: checkInteractions },
    { combo: "F8", label: "Repeats due", group: "Lists",
      run: () => setWorklistPanel("due") },
    { combo: "F9", label: "Queue", group: "Lists",
      run: () => setWorklistPanel("queue") },
    { combo: "F12", label: "Dispense", group: "Finish",
      disabled: busy || !patient || items.length === 0 || !complianceReadyRef(),
      run: () => { if (!busy && patient && items.length && complianceReadyRef()) createAndDispense(); } },
    { combo: "Escape", label: "Clear the script", group: "Finish",
      disabled: items.length === 0, run: () => setItems([]) },
    { combo: "?", label: "Show this key map", group: "Finish", run: () => setShowKeys(true) },
  ];
  useHotkeys(hotkeys);

  const complianceReady =
    (!needsInitials || initials.trim() !== "") &&
    (route !== "controlled" ||
    (items.length > 0 && idVerified && scriptSighted && prescriberVerified)) &&
    // A major interaction has to be acknowledged, not blocked. The checker holds
    // twelve pairs and says so; refusing outright on twelve while missing
    // thousands teaches a pharmacist that a clear result means safe.
    (ixMajor === 0 || ixAcknowledged);

  useEffect(() => {
    // Adding or removing a line makes it a different question, so a previous
    // acknowledgement stops applying. Carrying it over would let somebody accept
    // one finding and dispense a basket that now has another in it.
    setIxAcknowledged(false);
  }, [items.map((i) => i.product.id).join(","), patient?.id]);

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
    setProductQ(""); setProductResults([]); aiCheck.reset();
  }

  const updateItem = (idx: number, patch: Partial<DraftItem>) =>
    setItems(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));

  /** Print this script's labels, straight to the roll where there is one.
   *
   *  This is the path with a queue behind it. A print dialog here is a
   *  keystroke and a decision for every item on every script, so where the
   *  till has a label printer the stickers come off it the moment the script
   *  is dispensed, and the dialog is only what happens when it has not.
   */
  async function printRxLabels(rxId: number) {
    try {
      const labels = await api.get<Label[]>(`/api/prescriptions/${rxId}/labels`);
      if (roll.labelsGoStraightToRoll()) {
        try {
          for (const l of labels) await roll.printLines(labelLines(l, roll.printerWidth()));
          toast.ok(`${labels.length} label(s) printed.`);
          return;
        } catch (e) {
          // The medicine is already in the bag. A roll that will not take the
          // job must not cost the label, so the dialog is the fallback rather
          // than the error being the end of it.
          toast.error(errorText(e, "The label printer did not take it — using the print dialog."));
        }
      }
      printLabels(labels);
    } catch (e: any) { toast.error(errorText(e)); }
  }


  function compliancePayload() {
    // The initial is sent whenever there is one, on every route.
    //
    // It used to belong to the controlled-substance block and nothing else, so
    // on an ordinary prescription a pharmacist could type their initials into a
    // field that existed and still have the dispensing refused for not having
    // them — the value was collected and then dropped. Three places held an
    // opinion about when an initial is needed: this function, the field's
    // visibility, and a server setting. Only the server's counted.
    const initial = initials.trim();
    return {
      ...(initial ? { pharmacist_initial: initial } : {}),
      ...(route === "controlled"
        ? {
            id_verified: idVerified, id_number_seen: idNumber, script_sighted: scriptSighted,
            prescriber_verified: prescriberVerified,
            compliance_notes: complianceNotes,
          }
        : {}),
    };
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
      // Take the money here when that is what was asked for. The sale is
      // raised pending either way; settling it is the same call the till makes,
      // so there is one payment path in the system rather than two that can
      // disagree about what a scheme has already covered.
      let finished = sale;
      if (payHow !== "till") {
        try {
          finished = await api.post<Sale>(`/api/pos/sales/${sale.id}/pay`, {
            payment_method: payHow,
            amount_tendered: payHow === "cash" ? sale.total : 0,
          });
          toast.ok(`${money(sale.total)} taken. ${sale.sale_number} is settled.`);
        } catch (err) {
          // The medicine has already gone out and the invoice exists — the
          // dispensing is not undone because the card machine declined. It
          // becomes an ordinary pending sale, which is exactly what the till
          // is for, and the message says so instead of reading as a failure.
          toast.error(errorText(err,
            "Dispensed, but the payment did not go through. It is waiting at the till."));
        }
      }
      setDoneSale(finished); setDoneRxId(rx.id);
      setItems([]); aiCheck.reset();
      setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
      setInitials(""); setIdNumber(""); setComplianceNotes("");
      loadLists();
      // The queue is why anybody is on this screen. It refreshed itself every
      // two minutes and not on dispensing, so the count sat unchanged after the
      // very act that should have moved it — which reads as the dispensing not
      // having registered at all.
      setWorklistNonce((n) => n + 1);
      printRxLabels(rx.id);
    } catch (e: any) { toast.error(errorText(e)); } finally { setBusy(false); }
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
      alert(`Sold ${record.quantity} × ${record.product?.name}. Recorded in the pharmacy-medicine register.`);
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
        {/* What has already gone out. A dispensary is asked about yesterday's
            script several times a day — "did she collect it", "was that one
            paid for", "print that label again" — and the only way to answer
            was to know the patient and open their record. */}
        <Link className="btn secondary" to="/dispensing-history">
          <ClockCounterClockwise size={15} /> Dispensing history
        </Link>
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


      <div className="pill-tabs">
        {ROUTE_TABS.map((t) => (
          <button key={t.key} className={route === t.key ? "active" : ""} onClick={() => setRoute(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {route === "otc" ? (
        <div className="disp-work">
          {/* One column. It was a two-column grid because there was a second
              column to hold; with the work alone, splitting it only made the
              work narrower. */}
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
                    {patient.allergies && <span className="badge danger"><Warning size={11} weight="fill" /> {patient.allergies}</span>}
                    <IconButton action="remove" onClick={() => setPatient(null)} />
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
              <Checkbox checked={counselled} onChange={setCounselled}>Patient counselled on dose, duration and side effects</Checkbox>
              <Checkbox checked={referred} onChange={setReferred}>Referred to a doctor</Checkbox>
              <div className="field"><label>Notes</label>
                <textarea rows={2} value={otcNotes} onChange={(e) => setOtcNotes(e.target.value)} /></div>
              <div className="form-row">
                <div className="field">
                  <label>Cash tendered, total {money(otcTotal)}</label>
                  <input type="number" step="0.01" value={tendered} onChange={(e) => setTendered(e.target.value)} />
                </div>
              </div>
              <button onClick={sellOtc}
                disabled={busy || !otcProduct || (otcPolicy?.counselling_required && !counselled)}>
                {busy ? "Selling…" : `Sell & record${otcProduct ? ` for ${money(otcTotal)}` : ""}`}
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
                      <EntityLink kind="product" id={r.product_id}><b>{r.product?.name}</b></EntityLink> ×{r.quantity}
                      <span className={`badge ${r.schedule > 0 ? "warn" : "muted"}`} style={{ marginLeft: 6 }}>S{r.schedule}</span>
                    </td>
                    <td>
                      <EntityLink kind="patient" id={r.patient_id}>
                        {r.patient ? `${r.patient.first_name} ${r.patient.last_name}` : (r.customer_name || "—")}
                      </EntityLink>
                    </td>
                    <td>
                      {r.indication || "—"}
                      {r.referred_to_doctor && <div><span className="badge warn">referred to doctor</span></div>}
                    </td>
                    <td className="muted">{r.pharmacist?.full_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {otcMeta && <Pagination meta={otcMeta} onPage={setOtcPage} noun="sales" />}
            {otcLog.length === 0 && <div className="empty">No pharmacy-medicine sales recorded yet</div>}
          </div>
        </div>
      ) : (
        <div className="rx-split">
          <div>
            {route === "controlled" && (
              <div className="card" style={{ borderColor: "rgba(240,120,70,0.45)" }}>
                <h3><Warning size={17} weight="fill" /> Controlled substance, dangerous drugs protocol</h3>
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
                    {patient.allergies && <span className="badge danger" style={{ marginLeft: 8 }}><Warning size={11} weight="fill" /> {patient.allergies}</span>}
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
                <Select
                  value={String(doctorId ?? "")}
                  onChange={(__value) => setDoctorId(__value === "" ? "" : Number(__value))}
                  options={[{ value: "", label: "Select doctor…" }, ...doctors.map((d) => ({ value: String(d.id), label: `${d.name} (${d.practice_number})` }))]}
                />
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
                      <IconButton action="remove" onClick={() => setItems(items.filter((_, i) => i !== idx))} />
                    </div>
                    {/* Whether the same medicine is on the shelf under another
                        name, and what it costs. The substitution conversation
                        happens here, with the script in hand — not later. */}
                    <Variants productId={it.product.id} />
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
                        <Select
                          value={String(it.auto_refill ? "yes" : "no")}
                          onChange={(__value) => updateItem(idx, { auto_refill: __value === "yes" })}
                          options={[{ value: "no", label: "No, remind patient" }, { value: "yes", label: "Yes, prepare automatically" }]} disabled={maxRepeats === 0}
                        />
                      </div>
                    </div>
                    {maxRepeats === 0 && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        Schedule {it.product.schedule}: no repeats permitted. A fresh script is required each time.
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
                <Checkbox checked={scriptSighted} onChange={setScriptSighted}>Original prescription sighted and retained</Checkbox>
                <Checkbox checked={prescriberVerified} onChange={setPrescriberVerified}>Prescriber and practice number verified</Checkbox>
                <Checkbox checked={idVerified} onChange={setIdVerified}>Patient identity document verified</Checkbox>
                <div className="field">
                  <label>ID number sighted</label>
                  <input value={idNumber} onChange={(e) => setIdNumber(e.target.value)} placeholder="As per identity document" />
                </div>
                <div className="field">
                  <label>
                    Checked by (pharmacist initials)
                    {needsInitials && <span className="muted">, required for this schedule</span>}
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
              {/* Asked wherever it is required. The controlled route has its own
                  copy inside the compliance record; on an ordinary prescription
                  this was the missing step — the server wanted initials and the
                  screen never offered anywhere to put them. */}
              {needsInitials && route !== "controlled" && (
                <div className="field" style={{ maxWidth: 260 }}>
                  <label>
                    Checked by (pharmacist initials)
                    <span className="muted">, required</span>
                  </label>
                  <input
                    value={initials} maxLength={8}
                    onChange={(e) => setInitials(e.target.value.toUpperCase())}
                    placeholder="e.g. TM"
                  />
                </div>
              )}
              {coverage && !coverage.all_claimable && (
                <div className="error-banner">
                  {coverage.blocked_count} line{coverage.blocked_count === 1 ? "" : "s"} not covered
                  by {coverage.formulary}. Dispensing is allowed, the patient pays for
                  {coverage.blocked_count === 1 ? " it" : " them"}, but the scheme will not.
                </div>
              )}
              {coverage?.authorisation_required && coverage.all_claimable && (
                <div className="device-note">
                  One or more lines need an authorisation number from the scheme before
                  the claim will be paid.
                </div>
              )}
              {/* Runs itself as the basket changes. The button below is the
                  second opinion, not the first: this one is the check that
                  cannot be forgotten on a busy afternoon. */}
              <InteractionPanel
                patientId={patient?.id ?? null}
                productIds={items.map((i) => i.product.id)}
                lines={items.map((i) => ({
                  product_id: i.product.id,
                  instructions: i.dosage_instructions,
                  quantity: i.quantity,
                }))}
                acknowledged={ixAcknowledged}
                onAcknowledge={setIxAcknowledged}
                onScreened={setIxMajor}
              />

              <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
                <button className="secondary"
                        onClick={aiCheck.streaming ? aiCheck.stop : checkInteractions}
                        disabled={!aiCheck.streaming && (!patient || items.length === 0)}>
                  {aiCheck.streaming ? "Stop" : <><ClaudeIcon size={14} /> AI interaction check</>}
                </button>
                <button onClick={createAndDispense} disabled={busy || !patient || items.length === 0 || !complianceReady}>
                  {busy ? "Dispensing…" : `Dispense ${items.length} item${items.length === 1 ? "" : "s"}`}
                </button>
              </div>

              {/* How it gets paid for, decided here rather than afterwards.
                  Dispensing always raised a pending invoice and sent the
                  patient to the till, even for a two-dollar cash sale where the
                  same person is standing at the same counter — so a transaction
                  that is one act became two screens. The till is still the right
                  answer when somebody else settles, or when it is going on the
                  shelf to be collected later, so it stays the default. */}
              {/* The outcome, where the action was.
                  This used to render at the top of the page. After dispensing,
                  the dispenser is at the bottom — beside the button they just
                  pressed — so the one message telling them what happened, what
                  is owed and where to settle it appeared off screen. On a
                  counter that is indistinguishable from nothing happening. */}
              {doneSale && (
                <div className={doneSale.status === "paid" ? "success-banner" : "alert warn"}>
                  {doneSale.status === "paid" ? (
                    <>Dispensed and paid. Invoice <b>{doneSale.sale_number}</b>,{" "}
                    {money(doneSale.total)}. Labels sent to the printer.</>
                  ) : (
                    <>Dispensed. Invoice <b>{doneSale.sale_number}</b> for{" "}
                    {money(doneSale.total)} is <b>not yet paid</b>. Labels sent to
                    the printer.</>
                  )}
                  {" "}
                  {doneRxId && (
                    <button className="ghost small" onClick={() => setReprintRx(doneRxId)}>
                      <Printer size={14} /> Reprint labels
                    </button>
                  )}
                  {doneSale.status !== "paid" && (
                    <>
                      {" "}
                      {/* Carries the invoice with it. A bare link to /pos landed
                          the cashier on an empty till and left them to find the
                          sale by hand, with the patient standing there. */}
                      <Link to={`/pos?settle=${doneSale.id}`}>
                        Take payment for this one <ArrowRight size={12} weight="bold" />
                      </Link>
                    </>
                  )}
                  {" "}
                  <button className="ghost small" onClick={() => setDoneSale(null)}>Dismiss</button>
                </div>
              )}

              {items.length > 0 && (
                <div className="disp-pay">
                  <span className="muted small">Payment</span>
                  {PAY_CHOICES.map((c) => (
                    <button
                      key={c.key}
                      className={`btn small ${payHow === c.key ? "" : "ghost"}`}
                      onClick={() => setPayHow(c.key)}
                      title={c.hint}
                    >
                      {c.label}
                    </button>
                  ))}
                  <span className="muted small">{PAY_CHOICES.find((c) => c.key === payHow)?.hint}</span>
                </div>
              )}
              {ixMajor > 0 && !ixAcknowledged && items.length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                  Acknowledge the interaction finding above before dispensing.
                </div>
              )}
              {/* Only when the controlled record is what is actually missing.
                  This used to fire on any incomplete gate, so a Schedule 4 line
                  held up by an unacknowledged interaction was told to complete a
                  compliance record that is not on its route and does not exist —
                  two messages at once, one of them impossible to act on. */}
              {!complianceReady && items.length > 0 && route === "controlled"
                && !(idVerified && scriptSighted && prescriberVerified) && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                  Complete every item in the compliance record before this controlled substance can be dispensed.
                </div>
              )}
              {needsInitials && !initials.trim() && items.length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                  Enter the checking pharmacist's initials before dispensing.
                </div>
              )}
              {(aiCheck.streaming || aiCheck.text) && (
                <div className="ai-block">
                  <AiPhase phase={aiCheck.phase} />
                  {aiCheck.error && <div className="alert error">{aiCheck.error}</div>}
                  {/* Plain text with a caret while it writes; Markdown only once
                      it is finished, or headings and lists flicker in and out as
                      the syntax completes. */}
                  {aiCheck.streaming
                    ? aiShown && <p className="ai-live ai-caret">{aiShown}</p>
                    : <AiOutput text={aiCheck.text} title="Interaction check" />}
                </div>
              )}
              <KeyBar keys={hotkeys} />
            </div>
          </div>

          {/* The third column is gone.
              It held three unrelated things because there was space for them: a
              second repeats list that asked the same question as the worklist
              and answered it differently (53 against 0, from a 14-day horizon
              against a 7-day one), a recent-scripts list whose "See all" linked
              to a route that does not exist, and a page of schedule rules —
              reference material occupying a third of a console.

              None of it was actionable. Its one button posted a dispensing
              without the checking pharmacist's initials, which the server
              requires, so it returned 400 every single time it was pressed.

              Repeats now live in the worklist, which is where "what needs doing"
              already lived, and clicking one loads it into the form on the left
              — through the safety check, where the initials are captured. */}
        </div>
      )}
      </div>

      <DispensaryWorklist
        reloadOn={worklistNonce}
        panel={worklistPanel}
        onPanelChange={setWorklistPanel}
        onPickRepeat={(row) => {
          // Load the repeat into the form rather than dispensing it behind the
          // dispenser's back. A repeat still needs a safety check and a
          // pharmacist's initials; the shortcut this replaces skipped both and
          // was rejected by the server for exactly that reason.
          setRoute(row.schedule >= 5 ? "controlled" : "prescription");
          if (row.doctor_id) setDoctorId(row.doctor_id);
          api.get<Patient>(`/api/patients/${row.patient_id}`)
            .then((p) => { setPatient(p); setPatientQ(""); })
            .catch(() => toast.warn("That patient's record could not be opened."));
          // The detail endpoint answers with an envelope — {product, batches,
          // movements, …} — not a bare product. Declaring `api.get<Product>`
          // made TypeScript agree with the wrong shape, and the item went into
          // the basket with `id: undefined`, which then asked the server for
          // /api/products/undefined/variants.
          api.get<{ product: Product }>(`/api/products/${row.product_id}`)
            .then(({ product }) => {
              setItems((current) =>
                current.some((it) => it.product.id === product.id)
                  ? current
                  : [...current, {
                      product,
                      quantity: row.quantity || 1,
                      dosage_instructions: row.dosage_instructions,
                      repeats_allowed: 0, repeat_interval_days: 30,
                      auto_refill: false, icd10_code: "",
                    }]);
              toast.ok(`${product.name} loaded. Check it and record your initials to dispense.`);
            })
            .catch(() => toast.warn("That medicine could not be loaded."));
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
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
