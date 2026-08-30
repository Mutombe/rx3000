import { useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import Tenders, { TenderLine, currencyWorld } from "../components/Tenders";
import DispensaryWorklist, { WorklistPanel } from "../components/DispensaryWorklist";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
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
import BusyButton from "../components/BusyButton";
import {
  ArrowRight,
  ClockCounterClockwise,
  Printer,
  Warning,
} from "@phosphor-icons/react";
import { EntityLink } from "../components/Filters";
import InsuranceStanding from "../components/InsuranceStanding";
import RepeatsDue, { DueRepeat } from "../components/RepeatsDue";
import PatientForm, { draftFrom } from "../components/PatientForm";
import ScriptTotals from "../components/ScriptTotals";
import { TableSkeleton } from "../components/Skeleton";
import AlterScript from "../components/AlterScript";
import { Plus, Receipt, PencilSimpleLine } from "@phosphor-icons/react";

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
/** What the patient owes on a dispensed sale.
 *
 *  Not the total. The claim is raised when the script is dispensed, so by the
 *  time this screen is showing a figure the scheme is already carrying most of
 *  it — and asking a member for the funder's money as well as their own is the
 *  mistake this exists to prevent. Same rule as the till uses.
 */
function patientPortion(sale: Sale): number {
  const claim: any = (sale as any).claim;
  if (!claim) return sale.total;
  if (claim.status === "rejected" || claim.status === "reversed") return sale.total;
  return Math.max(0, Number(claim.patient_liable ?? sale.total));
}

const PAY_CHOICES = [
  { key: "till", label: "Send to till", hint: "Raise the invoice; settle at the front shop" },
  { key: "now", label: "Take payment now", hint: "Cash, card, mobile or a mix of them" },
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
  const [tenders, setTenders] = useState<TenderLine[]>([]);
  const [currencyState, setCurrencyState] = useState<any>(null);
  /** What the patient will actually hand over, once the claim is off it. */
  const [dueNow, setDueNow] = useState(0);
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
  /* The two registers on this screen load into empty tables, and an empty
     controlled register reads as "nothing was dispensed" — which for a
     schedule 5 log is the most misleading sentence on the page. */
  const [logsLoading, setLogsLoading] = useState(true);

  // `recent`, `moreRecent` and `repeatsDue` used to live here to feed the middle
  // column. They are gone with it — including the two requests they made on
  // every load, which were fetching lists nothing rendered.

  // Which segment of the worklist is open. Held here so F8 can reach it: the
  // rail that used to sit in the middle of this page is gone, and the shortcut
  // that opened it now opens the one queue instead of a second copy of it.
  const [worklistPanel, setWorklistPanel] = useState<WorklistPanel>("queue");

  useEffect(() => {
    api.get<any>("/api/currency")
      .then((c) => {
        setCurrencyState(c);
        setTenders([{ method: "cash", currency_code: c?.base ?? "USD", amount: "" }]);
      })
      .catch(() => undefined);
  }, []);

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
      .then((res) => { setOtcLog(res.items); setOtcMeta(res); if (res.page !== otcPage) setOtcPage(res.page); })
      .finally(() => setLogsLoading(false));
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

  const navigate = useNavigate();
  const [showKeys, setShowKeys] = useState(false);
  /** Somebody at the counter who is not on file yet. */
  const [newPatient, setNewPatient] = useState(false);
  const [altering, setAltering] = useState(false);
  /** Pricing a basket for somebody deciding, rather than dispensing it.
   *
   *  A quote is the same capture with nothing committed: no stock moves, no
   *  claim is raised, no register entry is written. Pharmacies are asked for
   *  one several times a day — "what would this cost me" — and the only way to
   *  answer was to capture the script and not press the button, which leaves a
   *  draft behind for somebody else to wonder about. */
  const [quoting, setQuoting] = useState(false);

  /** Start again, cleanly. */
  function newScript() {
    setItems([]); setPatient(null); setPatientQ(""); setDoneSale(null);
    setFromRx(null); setQuoting(false); aiCheck.reset();
    setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
    setInitials(""); setIdNumber(""); setComplianceNotes("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  /** The queued script this screen was opened from, if any.
   *
   *  Without it, picking a line off the worklist loaded only the patient and
   *  the dispenser re-typed the medicine — which created a *second*
   *  prescription and dispensed that one. The queued line was never touched,
   *  so the worklist could not go down however many people you served. It is
   *  cleared the moment the basket stops matching the script, because at that
   *  point what is on screen is no longer the thing that was queued. */
  const [fromRx, setFromRx] = useState<
    { id: number; number: string; draft?: boolean } | null>(null);
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

  /** Why the dispense button will not go, in one sentence.
   *
   *  These used to be three separate notices rendered in three different places
   *  further down the page — an acknowledgement note, a compliance note and an
   *  initials note — while the greyed-out button sat above them with nothing
   *  beside it. A control that refuses without saying why, and an explanation
   *  that is not next to the control, are the same fault twice. Only the first
   *  unmet condition is named, in the order somebody would fix them.
   */
  const blockedBecause = (): string => {
    if (!patient) return "Find the patient first.";
    if (items.length === 0) return "Add at least one medicine to the script.";
    if (route === "controlled" && !(idVerified && scriptSighted && prescriberVerified))
      return "Complete every item in the compliance record before this controlled substance can be dispensed.";
    if (needsInitials && !initials.trim())
      return "Enter the checking pharmacist's initials before dispensing.";
    if (ixMajor > 0 && !ixAcknowledged)
      return "Acknowledge the interaction finding above before dispensing.";
    return "";
  };

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

  /** Open a queued line as the script it actually is.
   *
   *  The whole point of a queue is that working it empties it. This loads the
   *  prescription behind the line — every outstanding item on it, with the
   *  directions, diagnosis and repeats already captured — so pressing Dispense
   *  satisfies that script rather than writing a new one beside it.
   */
  async function openQueued(row: { patient_id: number | null; prescription_id: number;
                                   schedule: number }) {
    if (!row.patient_id) {
      toast.warn("That line has no patient attached, so it cannot be opened from here.");
      return;
    }
    try {
      const [p, rx] = await Promise.all([
        api.get<Patient>(`/api/patients/${row.patient_id}`),
        api.get<Prescription>(`/api/prescriptions/${row.prescription_id}`),
      ]);
      setPatient(p);
      setPatientQ("");
      setRoute(row.schedule >= 5 ? "controlled" : "prescription");
      if (rx.doctor_id) setDoctorId(rx.doctor_id);

      // Lines the prescriber marked "do not dispense" are on the script but are
      // not to go out. Everything else is offered, and the server decides what
      // is genuinely still outstanding when the dispense is posted — it holds
      // the dispensing records and this screen does not.
      //
      // The product comes back with the item, so it is read rather than fetched:
      // a request per line here would be a fresh N+1 in the browser to answer
      // something the response already contains.
      const ready = (rx.items ?? [])
        .filter((i: any) => !i.not_dispensed && i.product)
        .map((i: any) => ({
          product: i.product,
          quantity: i.quantity ?? 1,
          dosage_instructions: i.dosage_instructions ?? "",
          repeats_allowed: i.repeats_allowed ?? 0,
          repeat_interval_days: i.repeat_interval_days ?? 30,
          auto_refill: !!i.auto_refill,
          icd10_code: i.icd10_code ?? "",
          item_id: i.id,
        }));
      if (!ready.length) {
        toast.warn("Nothing is outstanding on that script.");
        return;
      }
      setItems(ready);
      // Whether it is a draft governs what can be done with it. A draft has
      // no Rx number and the server refuses to dispense one — so if this is not
      // carried, opening a draft leads to a button that cannot work.
      setFromRx({ id: rx.id, number: rx.rx_number || rx.draft_ref || `#${rx.id}`,
                  draft: rx.status === "draft" });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      toast.error(errorText(e, "That queued line could not be opened."));
    }
  }

  /** Put a repeat that is due onto the script being written.
   *
   *  Carried across whole — the directions, the diagnosis, what is left of the
   *  repeats — because retyping them is how a repeat comes to be dispensed with
   *  different directions from the one before it, and because the claim needs
   *  the diagnosis that was on the original.
   *
   *  It is added as a fresh line rather than dispensed against the original
   *  item, so everything below still applies: the interaction screen runs, the
   *  schedule policy is enforced, and the pharmacist records their initials.
   *  Offering a repeat is not the same as waving it through.
   */
  function addDueRepeat(r: DueRepeat) {
    if (items.some((i) => i.product.id === r.product_id)) return;
    api.get<Product>(`/api/products/${r.product_id}`)
      .then((full: any) => {
        const product = full.product ?? full;
        setItems((rows) => [...rows, {
          product,
          quantity: r.quantity,
          dosage_instructions: r.dosage_instructions,
          repeats_allowed: r.repeats_left,
          repeat_interval_days: r.repeat_interval_days,
          auto_refill: false,
          icd10_code: r.icd10_code,
        }]);
        toast.ok(`${r.product} added — ${money(r.value)} of theirs that was waiting.`);
      })
      .catch(() => toast.error("That repeat could not be added to the script."));
  }

  /** What is on screen, in the shape the draft endpoints want. */
  function scriptPayload() {
    return {
      patient_id: patient?.id ?? null,
      doctor_id: doctorId === "" ? null : doctorId,
      notes: complianceNotes,
      items: items.map((i) => ({
        product_id: i.product.id, quantity: i.quantity,
        dosage_instructions: i.dosage_instructions,
        repeats_allowed: i.repeats_allowed,
        repeat_interval_days: i.repeat_interval_days,
        auto_refill: i.auto_refill, icd10_code: i.icd10_code,
      })),
    };
  }

  /** Put a half-captured script down and come back to it.
   *
   *  A pharmacist gets interrupted — the telephone, a query at the till, a
   *  delivery — and until now the only ways out of a part-typed script were to
   *  dispense it or to lose it. Drafts have existed since prescriptions did,
   *  and could be created and re-opened; there was no way to save one back, so
   *  re-opening a draft led to a screen whose only button the server refuses.
   */
  async function saveDraft() {
    if (!patient) {
      toast.error("A draft still needs to be against a patient, or nobody can find it again.");
      return;
    }
    setBusy(true);
    try {
      if (fromRx?.draft) {
        await api.put(`/api/prescriptions/${fromRx.id}/draft`, scriptPayload());
        toast.ok(`${fromRx.number} saved. It is waiting on the worklist.`);
      } else {
        const rx = await api.post<any>("/api/prescriptions",
                                       { ...scriptPayload(), draft: true });
        setFromRx({ id: rx.id, number: rx.rx_number || rx.draft_ref || `#${rx.id}`,
                    draft: true });
        toast.ok("Saved for later. It is on the worklist as an unfinished script.");
      }
    } catch (e) {
      toast.error(errorText(e, "That could not be saved."));
    } finally {
      setBusy(false);
    }
  }

  /** Turn a draft into a real script, so it can be dispensed.
   *
   *  Finalising is where the checks skipped while it was a draft happen, and
   *  where it takes its Rx number — the register is a numbered sequence and a
   *  draft must not consume one.
   */
  async function finaliseDraft() {
    if (!fromRx?.draft) return;
    setBusy(true);
    try {
      await api.put(`/api/prescriptions/${fromRx.id}/draft`, scriptPayload());
      const rx = await api.post<any>(`/api/prescriptions/${fromRx.id}/finalise`, {});
      setFromRx({ id: rx.id, number: rx.rx_number || `#${rx.id}`, draft: false });
      toast.ok(`${rx.rx_number} finished. It can be dispensed now.`);
    } catch (e) {
      // The server refuses a script with no prescriber, no items, or a
      // prohibited schedule, and names which. Shown as written.
      toast.error(errorText(e, "That draft could not be finished."));
    } finally {
      setBusy(false);
    }
  }

  async function createAndDispense() {
    if (!patient || doctorId === "" || items.length === 0) {
      toast.error("Select a patient, a doctor and at least one medication.");
      return;
    }
    setBusy(true);
    try {
      // A queued script is dispensed as itself. Capturing it again would leave
      // the original waiting in the queue for ever, which is exactly what used
      // to happen: the worklist never went down however many people you served.
      const rx = fromRx
        ? await api.get<Prescription>(`/api/prescriptions/${fromRx.id}`)
        : await api.post<Prescription>("/api/prescriptions", {
          patient_id: patient.id, doctor_id: doctorId,
          items: items.map((i) => ({
            product_id: i.product.id, quantity: i.quantity,
            dosage_instructions: i.dosage_instructions, repeats_allowed: i.repeats_allowed,
            repeat_interval_days: i.repeat_interval_days, auto_refill: i.auto_refill,
            icd10_code: i.icd10_code,
          })),
        });
      const sale = await api.post<Sale>(`/api/prescriptions/${rx.id}/dispense`, {
        // Whatever is on screen, which for a queued script is the outstanding
        // lines and for a fresh capture is everything just written.
        item_ids: fromRx
          ? items.map((i: any) => i.item_id).filter(Boolean)
          : rx.items.map((i) => i.id),
        ...compliancePayload(),
      });
      // Take the money here when that is what was asked for. The sale is
      // raised pending either way; settling it is the same call the till makes,
      // so there is one payment path in the system rather than two that can
      // disagree about what a scheme has already covered.
      let finished = sale;
      if (payHow === "now") {
        try {
          const due = patientPortion(sale);
          const lines = tenders.filter((t) => Number(t.amount) > 0);
          finished = await api.post<Sale>(`/api/pos/sales/${sale.id}/pay`, {
            payment_method: "split",
            // Each piece kept separate, with what it needs to be matched to a
            // statement later: the wallet and number, or the bank and last four.
            tenders: lines.map((t) => ({
              method: t.method,
              currency_code: t.currency_code || (currencyState?.base ?? "USD"),
              amount: Number(t.amount),
              reference: [t.wallet, t.phone, t.scheme, t.last4 && `••${t.last4}`, t.auth]
                .filter(Boolean).join(" "),
            })),
          });
          toast.ok(due < sale.total - 0.005
            ? `${money(due)} taken from the patient, ${money(sale.total - due)} on the scheme.`
            : `${money(due)} taken. ${sale.sale_number} is settled.`);
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
      setItems([]); aiCheck.reset(); setFromRx(null);
      setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
      setInitials(""); setIdNumber(""); setComplianceNotes("");
      loadLists();
      // The queue is why anybody is on this screen. It refreshed itself every
      // two minutes and not on dispensing, so the count sat unchanged after the
      // very act that should have moved it — which reads as the dispensing not
      // having registered at all.
      setWorklistNonce((n) => n + 1);
      // Labels first, then the screen moves. Printing is fire-and-forget — the
      // browser dialog or the roll takes it from here — so it must be started
      // before navigating away rather than left to a component that is about
      // to unmount.
      printRxLabels(rx.id);
      // "Send to till" is an instruction, so the screen follows it. It used to
      // raise the invoice and stay put with a banner, leaving the dispenser to
      // find the front shop and search for the sale they had just made — two
      // screens for one act, and the commonest way a pending sale is forgotten.
      if (payHow === "till" && finished?.id) {
        navigate(`/pos?settle=${finished.id}&tab=pending`);
      }
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

  // What the tender rows are settling. The basket's own total, since the claim
  // has not been raised yet at this point — the confirmation afterwards shows
  // the scheme's share once the server has worked it out.
  useEffect(() => {
    setDueNow(items.reduce((n, i) => n + (i.product.unit_price || 0) * (i.quantity || 0), 0));
  }, [items]);

  const otcTotal = otcProduct ? otcProduct.unit_price * otcQty : 0;
  const otcPolicy = otcProduct ? policyFor(otcProduct.schedule || 0) : undefined;

  /** The quote, as something a patient can take away and think about.
   *
   *  A quote is the one thing on this screen that leaves the building without
   *  any medicine attached to it. It is read at a kitchen table, compared
   *  against another pharmacy's, and brought back a week later — so it needs
   *  the pharmacy's name on it and a date it expires, or it comes back in a
   *  month with last month's prices on it and an argument attached.
   *
   *  Priced through the same endpoint the till uses, on the patient's own
   *  scheme. A quote worked out differently from the sale is worse than no
   *  quote at all.
   */
  async function printQuote() {
    if (items.length === 0) return;
    try {
      const priced = await Promise.all(items.map(async (line: any) => {
        const q = await api.post<any>("/api/quick-price", {
          product_id: line.product.id,
          quantity: line.quantity,
          medical_aid_id: patient?.medical_aid_id ?? null,
        });
        return { line, q };
      }));
      const head = await letterhead();
      // `scheme_price` where there is a scheme — the regulated price including
      // the dispensing fee — and the shelf price where there is not. Quoting
      // the shelf price to somebody on a scheme is quoting a figure the till
      // will not charge.
      const lineTotal = (q: any) => q.scheme ? q.scheme_price : q.cash_price;
      const total = priced.reduce((n, r) => n + (lineTotal(r.q) ?? 0), 0);
      const scheme = priced.reduce((n, r) => n + (r.q.scheme_pays ?? 0), 0);
      const own = priced.reduce((n, r) => n + (r.q.patient_pays ?? 0), 0);
      // A fortnight. Long enough to think it over, short enough that the price
      // on the paper is still the price in the system.
      const expires = new Date(Date.now() + 14 * 86_400_000);

      printDocument(head, {
        kind: "Quotation",
        to: [patient ? `${patient.first_name} ${patient.last_name}` : "Customer",
             patient?.phone ?? ""].filter(Boolean),
        meta: [
          { label: "Date", value: new Date().toLocaleDateString() },
          { label: "Valid until", value: expires.toLocaleDateString() },
          ...(patient?.medical_aid
            ? [{ label: "Scheme",
                 value: `${patient.medical_aid.name}`
                      + (patient.medical_aid_number
                         ? ` · ${patient.medical_aid_number}` : "") }]
            : []),
          { label: "To pay", value: money(own), strong: true },
        ],
        columns: [
          { key: "item", label: "Medicine" },
          { key: "directions", label: "Directions" },
          { key: "qty", label: "Qty", numeric: true, width: "16mm" },
          { key: "price", label: "Price", numeric: true, width: "26mm" },
          { key: "scheme", label: "Scheme pays", numeric: true, width: "28mm" },
          { key: "own", label: "You pay", numeric: true, width: "26mm" },
        ],
        rows: priced.map(({ line, q }) => ({
          item: `${line.product.name} ${line.product.strength ?? ""}`.trim(),
          directions: line.dosage_instructions || "—",
          qty: String(line.quantity),
          price: money(lineTotal(q) ?? 0),
          scheme: money(q.scheme_pays ?? 0),
          own: money(q.patient_pays ?? 0),
        })),
        totals: {
          directions: "Total",
          price: money(total), scheme: money(scheme), own: money(own),
        },
        note: "This is a quotation, not an invoice. Nothing has been dispensed "
            + "and no stock has been set aside. Prices hold until the date "
            + "above and are subject to the medicine being in stock and, where "
            + "a scheme is shown, to that scheme's authorisation on the day.",
      });
    } catch (e) {
      toast.error(errorText(e, "That quote could not be priced."));
    }
  }

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
        {/* The three things somebody starts on this screen, where the hand
            already is. Everything below is the work; these are the ways in. */}
        <div className="page-actions">
          <button className="btn" onClick={newScript}>
            <Plus size={14} weight="bold" /> New script
          </button>
          <button className="btn secondary" onClick={() => { newScript(); setQuoting(true); }}>
            <Receipt size={14} /> New quote
          </button>
          <button className="btn secondary" onClick={() => setAltering(true)}>
            <PencilSimpleLine size={14} /> Alter script
          </button>
          <Link className="btn secondary" to="/dispensing-history">
            <ClockCounterClockwise size={15} /> History
          </Link>
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


      {/* Nothing on this screen commits while it is a quote, so it says so
          once, plainly, at the top — a mode you cannot see is a mode somebody
          forgets they are in. */}
      {quoting && (
        <div className="alert warn no-print">
          <span>
            <b>This is a quote.</b> Nothing will be dispensed, no stock moves
            and no claim is raised. Price it, print it, and the patient decides.
          </span>
          <button className="btn ghost small" onClick={() => setQuoting(false)}>
            Turn it into a script
          </button>
        </div>
      )}

      {/* Which route is being dispensed governs the whole screen below it, so
          it floats rather than scrolling away. */}
      <div className="pill-tabs disp-routes">
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
            {logsLoading && otcLog.length === 0 && (
              <TableSkeleton cols={5} rows={4} />
            )}
            {!logsLoading && otcLog.length === 0 && (
              <div className="empty">
                <b>No pharmacy-medicine sales recorded yet</b>
                <p>
                  Everything sold over the counter without a script is entered
                  here, and this register is what an inspector asks to see.
                </p>
              </div>
            )}
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
                  {/* The end of the search is the beginning of the work.
                      "No match" used to be where this screen stopped: the
                      person is standing there with a script, and the dispenser
                      had to leave for the patient register, type the name
                      again, and come back to an empty basket. */}
                  {patientQ.trim().length >= 2 && patients.length === 0 && (
                    <div className="pick-none">
                      <span>Nobody on file matches &ldquo;{patientQ.trim()}&rdquo;.</span>
                      <button type="button" className="btn small"
                              onClick={() => setNewPatient(true)}>
                        Add them
                      </button>
                    </div>
                  )}
                  {patients.map((p) => (
                    <div key={p.id} className="product-pick"
                      onClick={() => { setPatient(p); setPatients([]); setPatientQ(""); setIdNumber(p.id_number); }}>
                      <span><b>{p.last_name}, {p.first_name}</b> <span className="muted">{p.id_number}</span></span>
                      <span className="muted">{p.medical_aid?.name ?? "Private"}</span>
                    </div>
                  ))}
                </>
              )}
              {/* Read before the first medicine goes on the script, not after
                  the basket is built. Whether the scheme is paying changes
                  whether this should be supplied on credit at all. */}
              {patient && <InsuranceStanding patientId={patient.id} />}

              {/* What else of theirs is waiting. Every other repeat screen in
                  this system reports a loss after it has happened; this is the
                  only place one can still be prevented, and it costs nothing —
                  the patient is here and the script already exists. */}
              {patient && !quoting && (
                <RepeatsDue
                  patientId={patient.id}
                  alreadyOn={items.map((i) => i.product.id)}
                  onAdd={addDueRepeat}
                />
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
                  <div key={it.product.id} className="rx-item">
                    <div className="rx-item-head">
                      <b>
                        {it.product.name} {it.product.strength}
                        <span className={`badge ${it.product.schedule >= 5 ? "danger" : "muted"}`}>
                          S{it.product.schedule}{pol?.register_entry ? " · register" : ""}
                        </span>
                      </b>
                      <IconButton action="remove" title="Take this line off the script"
                        onClick={() => setItems(items.filter((_, i) => i !== idx))} />
                    </div>
                    {/* Whether the same medicine is on the shelf under another
                        name, and what it costs. The substitution conversation
                        happens here, with the script in hand — not later. */}
                    <Variants productId={it.product.id} />
                    <div className="form-row">
                      {/* On the twelve-column grid rather than a pixel width.
                          `maxWidth: 90` made the quantity a stub beside a
                          directions field that still spanned half the row, so
                          the two never lined up with anything below them. */}
                      <div className="field span-2">
                        <label>Qty</label>
                        <input type="number" min={1} value={it.quantity}
                          onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })} />
                      </div>
                      <div className="field span-10">
                        <label>Dosage instructions</label>
                        {/* Shorthand in, sentence out. `1 t tds pc` becomes the
                            line the patient reads on the label. */}
                        <SigInput
                          value={it.dosage_instructions}
                          onChange={(next) => updateItem(idx, { dosage_instructions: next })}
                        />
                      </div>
                    </div>
                    <div className="field span-12">
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
                      <div className="field span-3">
                        <label>Repeats (max {maxRepeats})</label>
                        <input type="number" min={0} max={maxRepeats} value={it.repeats_allowed}
                          disabled={maxRepeats === 0}
                          onChange={(e) => updateItem(idx, {
                            repeats_allowed: Math.min(maxRepeats, Math.max(0, Number(e.target.value))),
                          })} />
                      </div>
                      <div className="field span-3">
                        <label>Interval (days)</label>
                        <input type="number" min={1} value={it.repeat_interval_days}
                          onChange={(e) => updateItem(idx, { repeat_interval_days: Number(e.target.value) })} />
                      </div>
                      <div className="field span-6">
                        <label>Auto-refill</label>
                        <Select
                          value={String(it.auto_refill ? "yes" : "no")}
                          onChange={(__value) => updateItem(idx, { auto_refill: __value === "yes" })}
                          options={[{ value: "no", label: "No, remind patient" }, { value: "yes", label: "Yes, prepare automatically" }]} disabled={maxRepeats === 0}
                        />
                      </div>
                    </div>
                    {maxRepeats === 0 && (
                      <div className="muted small">
                        Schedule {it.product.schedule}: no repeats permitted. A fresh
                        script is required each time.
                      </div>
                    )}
                  </div>
                );
              })}
              {/* The dozen figures the incumbent prints along the bottom of a
                  script, read before it is finished rather than in a report
                  next month — by which time the medicine has gone. */}
              {items.length > 0 && (
                <ScriptTotals
                  items={items.map((i: any) => ({
                    product_id: i.product.id,
                    quantity: i.quantity,
                    no_claim: !!i.no_claim,
                  }))}
                  medicalAidId={patient?.medical_aid_id ?? null}
                />
              )}
              {items.length === 0 && (
                <div className="empty">
                  <b>Nothing on this script yet</b>
                  <p>
                    Search above for what is being dispensed. Each line carries
                    its own directions, diagnosis and repeats.
                  </p>
                </div>
              )}
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

              {/* How it is paid for is decided before it is dispensed, not
                  after. It changes what pressing the button does — the till
                  route sends the patient to the front shop, taking payment
                  here does not — and a setting that governs an action reads
                  as an afterthought when it sits below it. */}
              {items.length > 0 && (
                <div className="disp-pay">
                  <span className="disp-pay-label">How this is paid for</span>
                  {/* A segmented control, because these are two states of one
                      setting rather than two things to do. Set out flat as
                      buttons with the explanation trailing off the end of the
                      row, the sentence read as a third option. */}
                  <div className="seg" role="radiogroup" aria-label="How this is paid for">
                    {PAY_CHOICES.map((c) => (
                      <button
                        key={c.key}
                        role="radio"
                        aria-checked={payHow === c.key}
                        className={payHow === c.key ? "on" : ""}
                        onClick={() => setPayHow(c.key)}
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>
                  <span className="muted small disp-pay-hint">
                    {PAY_CHOICES.find((c) => c.key === payHow)?.hint}
                  </span>
                </div>
              )}
              {/* Built out of the pieces it was actually paid with, rather than
                  a single word. "Card now" recorded no bank and no currency,
                  which on a counter taking USD and ZiG across three wallets is
                  a figure nobody can reconcile at cash-up. Same component the
                  till uses, so the question is asked once and asked the same. */}
              {items.length > 0 && payHow === "now" && (
                <div className="card" style={{ marginBottom: 12 }}>
                  <Tenders
                    lines={tenders}
                    onChange={setTenders}
                    owed={dueNow}
                    allowAid={false}
                    {...currencyWorld(currencyState)}
                  />
                  <p className="muted small">
                    The medical aid is not listed here: the claim is raised by
                    the dispensing itself, so this is only what the patient
                    hands over.
                  </p>
                </div>
              )}

              {fromRx?.draft && (
                <div className="alert warn">
                  <Warning size={16} weight="fill" />
                  <span>
                    <b>{fromRx.number} is an unfinished script.</b> It has no Rx
                    number yet and cannot be dispensed. Finish capturing it —
                    that is where it takes its number and where the checks
                    happen — or save it and come back.
                  </span>
                </div>
              )}

              {/* The one act this page exists for, and beside it the reason
                  it cannot happen yet. */}
              <div className="disp-commit">
                <div className="disp-commit-row">
                  <button className="btn secondary"
                          onClick={aiCheck.streaming ? aiCheck.stop : checkInteractions}
                          disabled={!aiCheck.streaming && (!patient || items.length === 0)}>
                    {aiCheck.streaming ? "Stop" : <><ClaudeIcon size={14} /> AI interaction check</>}
                  </button>
                  {/* A quote commits nothing: no stock moves, no claim is
                      raised, no register entry is written. So it is a different
                      button rather than the same one in a different mood — the
                      one thing that must never happen by accident on this
                      screen is dispensing when somebody meant to price. */}
                  {/* Put it down and come back to it. A pharmacist gets
                      interrupted, and the only ways out of a part-typed script
                      were to dispense it or lose it. Not offered while quoting:
                      a quote is not a script and saving one as a draft would
                      put a price enquiry on the dispensing worklist. */}
                  {!quoting && (
                    <BusyButton className="btn secondary" busyLabel="Saving…"
                                disabled={!patient || items.length === 0}
                                onClick={saveDraft}>
                      {fromRx?.draft ? "Save the draft" : "Save for later"}
                    </BusyButton>
                  )}
                  {quoting ? (
                    <button className="btn primary disp-go"
                            disabled={items.length === 0}
                            onClick={printQuote}>
                      Print the quote
                    </button>
                  ) : fromRx?.draft ? (
                    // A draft has no Rx number and the server will not dispense
                    // one. Finishing it is a separate act — it is where the
                    // checks skipped during capture happen and where the script
                    // takes its number — so it is a separate button, and the
                    // dispense appears only once it is a real script.
                    <BusyButton
                      className="btn primary disp-go"
                      busyLabel="Finishing…"
                      disabled={!patient || items.length === 0 || doctorId === ""}
                      onClick={finaliseDraft}
                    >
                      Finish capturing
                    </BusyButton>
                  ) : (
                    <BusyButton
                      className="btn primary disp-go"
                      busyLabel="Dispensing…"
                      disabled={!patient || items.length === 0 || !complianceReady}
                      onClick={createAndDispense}
                    >
                      Dispense {items.length} item{items.length === 1 ? "" : "s"}
                    </BusyButton>
                  )}
                </div>
                {blockedBecause() && (
                  <p className="disp-blocked">
                    <Warning size={14} weight="fill" />
                    <span>{blockedBecause()}</span>
                  </p>
                )}
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
                    <>Dispensed. Invoice <b>{doneSale.sale_number}</b>:{" "}
                    <b>{money(patientPortion(doneSale))}</b> to collect from the
                    patient
                    {/* The scheme's share, said plainly. A dispenser reading
                        only the total asks a member for the funder's money as
                        well as their own — and "where is the claim half" was
                        unanswerable on this screen. */}
                    {patientPortion(doneSale) < doneSale.total - 0.005 && (
                      <> ({money(doneSale.total - patientPortion(doneSale))} of{" "}
                      {money(doneSale.total)} is on the scheme)</>
                    )}
                    . <b>Not yet paid</b>. Labels sent to the printer.</>
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

      {/* Created here, selected here, dispensed to here. A dialog that closes
          and leaves you to search for what you just made is barely better than
          the navigation it replaced. */}
      <PatientForm
        open={newPatient}
        initial={draftFrom(patientQ)}
        onClose={() => setNewPatient(false)}
        onSaved={(p) => { setPatient(p); setPatients([]); setPatientQ(""); }}
      />

      {altering && (
        <AlterScript onClose={() => setAltering(false)}
                     onAltered={() => setWorklistNonce((n) => n + 1)} />
      )}

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
        onPick={(row) => openQueued(row)}
        onPickDraft={(d) => {
          // A draft is a script somebody walked away from. Opening it puts the
          // patient and the lines back on screen so it can be finished rather
          // than started again beside it.
          openQueued({ patient_id: d.patient_id ?? d.patient?.id ?? null,
                       prescription_id: d.id, schedule: 0 });
        }}
      />
      </div>
    </>
  );
}
