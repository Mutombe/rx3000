import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import Tenders, { TenderLine, currencyWorld, inBase } from "../components/Tenders";
import DispensaryWorklist, { WorklistPanel } from "../components/DispensaryWorklist";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText, fmtWhen } from "../api";
import { useSession } from "../session";
import { clearScriptDraft, readScriptDraft, writeScriptDraft } from "../hooks/scriptDraft";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import AiOutput from "../components/AiOutput";
import CounterMessages, { useCounterMessages } from "../components/CounterMessages";
import DiagnosisPicker from "../components/DiagnosisPicker";
import KeyMap, { KeyBar } from "../components/KeyMap";
import AiPhase from "../components/AiPhase";
import type { Screen } from "../components/InteractionPanel";
import LineCheckModal, { findingsFor } from "../components/LineCheckModal";
import { useAiStream } from "../hooks/useAiStream";
import { useTypewriter } from "../hooks/useTypewriter";
import LabelSheet from "../components/LabelSheet";
import SigInput from "../components/SigInput";
import MixAtTheCounter, { MadeUp } from "../components/MixAtTheCounter";
import { useDoing } from "../components/Doing";
import { usePharmacy } from "../hooks/usePharmacy";
import { ScanCamera, cameraSupported, useWedgeScanner } from "../components/Scanner";
import AttachBarcode from "../components/AttachBarcode";
import { CANCELLED, useStepUp } from "../components/StepUp";
import { useConfirm } from "../components/Confirm";
import { useScanFeed } from "../components/ScannerHub";
import LotPicker, { LotChoice, ROTATION } from "../components/LotPicker";
import SchemeCodeField, { NoCodeMark, useSchemeCodes } from "../components/SchemeCode";
import SetThePrice, { PriceAsked } from "../components/SetThePrice";
import Variants from "../components/Variants";
import CounsellingPoints from "../components/CounsellingPoints";
import RepeatValue from "../components/RepeatValue";
import { Hotkey, useHotkeys } from "../hooks/useHotkeys";
import { useDoseScreen } from "../hooks/useDoseScreen";
import CellMedicineSearch from "../components/CellMedicineSearch";
import PatientHistoryModal from "../components/PatientHistoryModal";
import PatientCardModal from "../components/PatientCardModal";
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from "react";
import { printLabels, printReceipt, refusedSummary, splitPrintable } from "../print";
import PrintMenu, { type PrintAction } from "../components/PrintMenu";
import * as roll from "../shellPrinter";
import { deliveryLabelLines, priceLabelLines } from "../deviceAgent";
import type { Line } from "../escpos";
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
import { ArrowRight, CaretRight, CircleNotch, ClockCounterClockwise, PencilSimple, Printer,
  ShieldCheck, ShieldWarning, Trash, Warning, X, Check, Info, MagnifyingGlass, IdentificationCard, FirstAidKit, Tag, Truck, FileText, Sticker, Signature, Barcode, CalendarBlank } from "@phosphor-icons/react";
import { EntityLink } from "../components/Filters";
import InsuranceStanding from "../components/InsuranceStanding";
import RepeatsDue, { DueRepeat } from "../components/RepeatsDue";
import PatientForm, { draftFrom } from "../components/PatientForm";
import NewMedicine, { MedicineDraft } from "../components/NewMedicine";
import ScriptTotals, { useScriptPricing } from "../components/ScriptTotals";
import MarginTag, { shelfMargin } from "../components/MarginTag";
import { TableSkeleton } from "../components/Skeleton";
import AdjustStock from "../components/AdjustStock";
import AlterScript from "../components/AlterScript";
import { Camera, EyeSlash, Plus, Receipt, PencilSimpleLine, UserCircle, XCircle } from "@phosphor-icons/react";
import StepTrail, { Step, goToStep } from "../components/StepTrail";
import { DRAFT_SCRIPT, TERMS } from "../terms";
import { routeForSchedule, scheduleCode, useScheduleCodes } from "../schedules";
import DriverForm from "../components/DriverForm";


/** The label the server screens a line under — and so the one its findings
 *  come back under. Built in one place so the two can never drift. */
const lineName = (p: Product) => `${p.name} ${p.strength || ""}`.trim();

/** What to type, shown once the cursor is in a lane field. Worded for the
 *  narrowest the field gets — about 16 characters for Medicine at 1366px — and
 *  promising only what the search behind it actually matches. */
const PATIENT_HINT = "Name, ID, phone or aid no.";
const PRESCRIBER_HINT = "Name or practice no.";
// Short because the field is: the tools on the patient beside it took the
// room, and a hint wider than its box is an ellipsis, not a hint.
const MEDICINE_HINT = "Name or scan";

/** Initials from a person's name: "System Administrator" → "SA",
 *  "Dr Tendai M. Moyo" → "TMM". Titles are not initials. Falls back to the
 *  username's letters when the name has none. Eight at most, as the field is. */
const TITLES = new Set(["dr", "mr", "mrs", "ms", "miss", "prof", "sr", "sister"]);
function initialsOf(fullName?: string | null, username?: string | null): string {
  const words = (fullName || "")
    .replace(/\(.*?\)/g, " ")
    .split(/\s+/)
    .map((w) => w.replace(/[^A-Za-z]/g, ""))
    .filter((w) => w && !TITLES.has(w.toLowerCase()));
  if (words.length) return words.map((w) => w[0]).join("").toUpperCase().slice(0, 8);
  return (username || "").replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
}

/** Today as YYYY-MM-DD in the pharmacy's own time, to compare with a date input.
 *  `toISOString` is UTC, which for two hours after midnight in Harare is still
 *  yesterday. */
function localIsoDate(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Whether what arrived in the medicine box is a scanned code rather than a name.
 *
 *  A wedge scanner types the code and presses Enter, into whatever has the
 *  cursor. A person looking for a medicine types letters. Eight to fourteen
 *  digits is a retail barcode (EAN-8 up to GTIN-14); a GS1 string carries an
 *  application identifier or the group separator. Anything else is a search. */
function looksLikeCode(text: string): boolean {
  const t = text.trim();
  if (t.startsWith("(01)") || t.startsWith("]C1") || t.includes("")) return true;
  return /^\d{8,14}$/.test(t);
}

/* The initials box, which said the least of any field on the screen: a label
   reading "Checked by" next to a box whose placeholder read "Initials" — two
   words for one thing, and between them they never said whose initials, or
   why anybody wants them. The field now carries its own name where the
   placeholder sits, says what to type once the cursor is in it, and the whole
   sentence is on the field itself for anyone who hovers or reads it aloud. */
const INITIALS_HINT = "Your initials, e.g. TM";
/* What the patient was told, as the server names the points
   (backend/app/services/counselling.py) — worded short, because they sit as
   chips in a dialog that must not scroll. The server keeps the long labels
   for the record, and drops any key it does not know. */
const COUNSELLING_POINTS: { key: string; short: string }[] = [
  { key: "dose", short: "Dose & timing" },
  { key: "duration", short: "How long" },
  { key: "side_effects", short: "Side effects" },
  { key: "warnings", short: "Warnings" },
  { key: "missed_dose", short: "Missed dose" },
  { key: "storage", short: "Storage" },
];
const INITIALS_TITLE = "The initials of the pharmacist who checked this "
  + "dispensing. This is the record that somebody checked it.";

/** An open hold on a script (backend/app/services/holds.py). */
interface HoldSummary {
  id: number; reason_code: string; reason: string; note: string;
  placed_by: string; placed_at: string; open: boolean; hours_held: number;
}

interface DraftItem {
  product: Product;
  quantity: number;
  dosage_instructions: string;
  repeats_allowed: number;
  repeat_interval_days: number;
  auto_refill: boolean;
  /** Diagnosis for this line. A claim line without one is rejected. */
  icd10_code: string;
  /** The `PrescriptionItem` row behind this line, where one exists.
   *
   *  Declared rather than cast on. It was read as `(i as any).item_id`, which
   *  stopped the compiler asking whether the field existed at all, and the same
   *  cast on this same object had already hidden a `no_claim` that never
   *  existed. A field worth reading is worth naming.
   *
   *  Only trustworthy immediately after the server handed it over: saving a
   *  draft replaces its items and issues new ids.
   */
  item_id?: number;
  /** A price set by hand for this line, per unit, instead of the shelf's.
   *
   *  Undefined on almost every line, and that is the point: undefined means
   *  "whatever the catalogue says", so a repeat reprices itself next month.
   */
  price?: number;
  /** The authorisation behind `price` — the record written when somebody's code
   *  was accepted. The script quotes this id; it never sends the figure, because
   *  a screen free to name its own price has gone round the code rather than
   *  through it. */
  priceOverrideId?: number;
  /** What the scheme is asked for on this line, set by hand and signed for.
   *  Undefined on almost every line, which means "whatever the cover rule
   *  decides" — so a repeat re-adjudicates rather than carrying a decision
   *  somebody made once. */
  claim?: number;
  claimOverrideId?: number;
}

/** The diagnosis a line starts on.
 *
 *  Z76.9 — "person encountering health services in unspecified circumstances".
 *  The ICD-10 code for a contact with no diagnosis attached, which is what
 *  nearly every counter dispensing is, and what the previous system put there.
 *
 *  A default, not an answer. Where the prescriber wrote a diagnosis it should
 *  be typed, and the line below the picker says so.
 */
/** What ONE dispensable unit of this product sells for.
 *
 *  Mirrors `Product.per_unit()` on the server. `unit_price` is what a PACK
 *  costs despite its name, and a script quantity counts tablets — multiplying
 *  the two put $1,050 on screen for twenty-one capsules out of a $50 tub.
 *
 *  In one place because six sites in this file multiply a price by a quantity
 *  and they all have to give the same answer as the sale does. Written out six
 *  times they agree until somebody edits five of them.
 */
function perUnit(p: { unit_price?: number; units_per_pack?: number }): number {
  const pack = Math.max(1, Math.floor(p.units_per_pack ?? 1) || 1);
  return (p.unit_price ?? 0) / pack;
}

/** What this LINE charges for one unit: the hand-set price, or the shelf's.
 *
 *  Same reason `perUnit` exists. A price somebody got a password for, honoured
 *  on the row and forgotten by the totals, is a discount that reappears at the
 *  till with the patient standing there.
 */
function lineEach(i: { product: Product; price?: number }): number {
  return i.price ?? perUnit(i.product);
}

const DEFAULT_DIAGNOSIS = "Z76.9";

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
 *  it, and asking a member for the funder's money as well as their own is the
 *  mistake this exists to prevent. Same rule as the till uses.
 */
function patientPortion(sale: Sale): number {
  const claim: any = (sale as any).claim;
  if (!claim) return sale.total;
  if (claim.status === "rejected" || claim.status === "reversed") return sale.total;
  return Math.max(0, Number(claim.patient_liable ?? sale.total));
}

const PAY_CHOICES = [
  // "the shortfall" rather than "the invoice": on a scheme member the till
  // collects the patient's share, not the gross, and the choice should say so
  // where the choice is made.
  { key: "till", label: "Send to till",
    hint: "Raise it now; the patient settles their share at the front shop" },
  { key: "now", label: "Take payment now", hint: "Cash, card, mobile or a mix of them" },
  // The third thing that actually happens to a dispensed script, and the
  // screen had no word for it. A delivery leaves the building unpaid: the
  // driver collects at the door and the money is theirs to account for until
  // they hand it in, so the sale goes onto the driver's account rather than
  // sitting on a till nobody is standing at.
  { key: "delivery", label: "Out for delivery",
    hint: "The driver collects at the door and hands it in on their return" },
  // Paid by the scheme, from the card in the patient's hand. Chosen here, the
  // scheme and member number are whatever the card says — filled from the
  // patient where they are on file, typed where they are not — and the claim is
  // sent or held as the counter decides, with the shortfall taken on the spot.
  { key: "aid", label: "Medical aid",
    hint: "Claim from the scheme on the card and take the patient's shortfall here" },
];

/** How many steps the trail ends on, given which middle ones are showing. */
function steps_last_number(needsScript: boolean, needsCompliance: boolean): number {
  // Medicine is always 1. A script adds the patient step, a controlled line
  // adds the compliance one, and a counter sale adds the consultation.
  return 1 + (needsScript ? 1 : 0) + (needsCompliance ? 1 : 0)
    + (needsScript ? 0 : 1);
}

export default function Dispense() {
  const session = useSession();
  /** The script this screen last put out, so the menu can act on it.
   *
   *  Every document below the primary action is about a script that has just
   *  been dispensed — a reprint, a claim copy, a delivery label for the bag
   *  now sitting on the counter. The id was being forgotten the moment the
   *  form cleared, which is why reprinting meant finding the patient again. */
  /** The script line whose editor is open. One at a time.
   *
   *  Every line used to render its whole editor — variants, counselling, two
   *  rows of fields, the coverage note — about 300px each, so two medicines
   *  filled the screen. A back-office grid opens one row: the one being worked
   *  on, which is the one just added. */
  const [openItem, setOpenItem] = useState<number>(0);
  /** The line whose editor is open, or null. A dialog rather than a band:
   *  editing a line is a decision about that line — the quantity, the
   *  directions that print on the box, the diagnosis the claim is raised on —
   *  and it wants the screen while it is being made. Keeping it permanently on
   *  the screen cost the table 200px for fields being looked at on one row in
   *  eight. */
  const [editing, setEditing] = useState<number | null>(null);
  /** The Finish dialog, open at a section, or null.
   *
   *  Everything that is only needed at the end of a script lives in it: the
   *  warnings that must be settled, the compliance record, how it is paid, who
   *  checked it, and the button. On the page they were stacked under the table
   *  and pushed each other — and the table — off the bottom of the screen. */
  const [finishing, setFinishing] = useState<string | null>(null);
  /** The line whose check is open, by product id. */
  const [checking, setChecking] = useState<number | null>(null);
  /** The patient context a lane chip opened: the repeats due, or the scheme. */
  const [laneOpen, setLaneOpen] = useState<
    "repeats" | "insurance" | "history" | "details" | null>(null);
  /** Which stage of Finish is showing. What must be settled comes first, on its
   *  own, so payment has the whole dialog to itself and never scrolls. */
  const [finishStage, setFinishStage] = useState<"settle" | "pay">("pay");
  /** The basket the warnings were last proceeded past. Once is enough for that
   *  basket; change a line and they are shown again. */
  const [settledFor, setSettledFor] = useState<string | null>(null);
  /** Prints the pharmacist has switched on or off for this script. What is not
   *  here follows the defaults, which follow the script. */
  const [printPick, setPrintPick] = useState<Partial<Record<roll.DocKind, boolean>>>({});
  /** Each line's deliberate check, stamped with the basket it answered for. A
   *  result for a basket that has since changed is shown as not yet checked,
   *  never as the old answer. */
  const [lineChecks, setLineChecks] = useState<Record<number, {
    sig: string; status: "loading" | "ready"; screen?: Screen; error?: string }>>({});
  /** The table cell being edited in place. Keyed by product rather than row
   *  number, so deleting a line above cannot move the editor onto another. */
  const [cellEdit, setCellEdit] = useState<{
    id: number; col: "medicine" | "qty" | "sig" | "money"; orig: string | number } | null>(null);
  /** Whether the first empty row is currently a medicine search.
   *
   *  The rows below the script are where the next line goes, so that is where
   *  asking for one should happen. Sending the hand back up to the Medicine
   *  field to add a fourth line, when the eye is already on the row the fourth
   *  line will occupy, is the trip this saves. The field above still works and
   *  is still the keyboard's way in; this is the mouse's. */
  const [newLine, setNewLine] = useState(false);
  /** Lines whose price is being authorised, by product id. The row keeps its
   *  old figure with a spinner beside it rather than flickering to the new one
   *  and back if the code is refused. */
  const [authorisingPrice, setAuthorisingPrice] = useState<number | null>(null);
  const [authorisingClaim, setAuthorisingClaim] = useState<number | null>(null);
  /** An amount typed into the money cell, before it has been authorised. Text,
   *  so a half-typed "12." is not read as 12. */
  const [priceDraft, setPriceDraft] = useState("");
  /** The line whose price is being set, by row. The dialog asks for the figure
   *  — by price or by margin — and whether to keep it; the code is asked for
   *  after, because a code typed before anybody has said what they want is a
   *  code typed for nothing. */
  const [pricingLine, setPricingLine] = useState<number | null>(null);
  /** Which figure on the line editor's rail is being typed into, and what has
   *  been typed.
   *
   *  The rail showed Each and Line as plain text, so the only way to change a
   *  price inside the editor was a button that opened another dialog on top of
   *  it. Two clicks and a second window to round a line to twelve dollars, when
   *  the same figure in the table behind it takes a double-click. The dialog
   *  still exists, behind "change", because margin and "keep this price for
   *  good" are answers a bare cell cannot hold. */
  /** The medicine whose shelf count is being corrected, from wherever the
   *  dispenser noticed it was wrong. Null when nothing is. */
  const [adjusting, setAdjusting] = useState<Product | null>(null);
  const [railEdit, setRailEdit] = useState<"each" | "line" | "claim" | null>(null);
  const [railDraft, setRailDraft] = useState("");
  // Closing the editor, or moving to another line, abandons whatever was half
  // typed. Without this the box reopens on the next medicine still holding the
  // last one's figure, which is the one way an inline editor can put a price on
  // a line nobody typed it for.
  useEffect(() => { setRailEdit(null); setRailDraft(""); }, [editing]);
  const { guarded, prompt: stepUpPrompt } = useStepUp();
  /** This pharmacy's own name and registration, for the receipt. */
  const pharmacy = usePharmacy();
  /** Whether this receipt names the medicines on it.
   *
   *  Off by default — a receipt that says what it is for is the ordinary,
   *  useful thing — and turned on for the patient who asks, or for the
   *  dispenser who can see they should. Kept on the sale, so a receipt printed
   *  later at the till honours it. */
  const [receiptPrivate, setReceiptPrivate] = useState(false);
  const cellEditRef = useRef(cellEdit);
  useEffect(() => { cellEditRef.current = cellEdit; }, [cellEdit]);
  /** The full text of a truncated table cell, floated over it. */
  const [tip, setTip] = useState<{
    text: string; sub?: string; x: number; y: number; below: boolean } | null>(null);
  const [lastRxId, setLastRxId] = useState<number | null>(null);
  const [printing, setPrinting] = useState(false);
  /* The routes this person may use. Filtered only once the server has said
     what they may do: `can` is false while the session loads, and a dispensary
     that hides the controlled tab for a second every morning is one a
     pharmacist stops trusting. */
  /* Whether there is anything on this screen for this person at all.
   *
   *  This was a list of visible tabs, and the tabs are gone. What replaced
   *  them is the medicine search asking the permission matrix what to offer,
   *  so the only question left here is the whole-page one: somebody holding
   *  none of the three dispensing permissions has nothing to hand over and is
   *  told so, rather than being shown an empty search box.
   */
  const mayDispense = useMemo(
    () => !session.known
      || ["dispense.prescription", "dispense.controlled", "dispense.otc"]
        .some((c) => session.can(c)),
    [session]);

  const [policies, setPolicies] = useState<SchedulePolicy[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const toast = useToast();
  const askConfirm = useConfirm();

  // shared patient picker
  const [patientQ, setPatientQ] = useState("");
  /** What is typed into the prescriber search. */
  const [doctorQ, setDoctorQ] = useState("");
  /** The lane search the cursor is in. Its placeholder turns from the field's
   *  name into what to type. */
  const [laneFocus, setLaneFocus] = useState<"patient" | "doctor" | "product" | null>(null);
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
  // Taking the money at the counter is what happens to most scripts, so it is
  // what the dialog opens on. Sending it to the front till is the exception and
  // is one click away.
  //
  // Unless the patient is on a scheme, in which case the screen already knows.
  // The card is on the record and the claim panel below is already filled in
  // from it, and the dispenser still had to press "Medical aid" on every
  // script to reach a panel that was waiting for them. `payHowSet` records
  // that somebody chose for themselves, so the default never overrides a real
  // decision or a restored draft.
  const [payHow, setPayHow] = useState("now");
  const payHowSet = useRef(false);
  const choosePayHow = (key: string) => { payHowSet.current = true; setPayHow(key); };
  /** Who is taking it, and where. Only asked for on the delivery route. */
  const [drivers, setDrivers] = useState<{ id: number; full_name: string;
    active: boolean; cash_holding?: number; cod_limit?: number;
    over_cod_limit?: boolean; licence_expired?: boolean }[]>([]);
  const [driverId, setDriverId] = useState<number | "">("");
  const [deliverTo, setDeliverTo] = useState("");
  const [deliveryFee, setDeliveryFee] = useState("");
  const [addingDriver, setAddingDriver] = useState(false);

  useEffect(() => {
    // Fetched when the route is chosen, not on load: a dispensary that never
    // delivers should not pay for the request, and the list is short enough
    // that asking on demand is instant.
    if (payHow !== "delivery" || drivers.length) return;
    api.get<typeof drivers>("/api/drivers")
      .then((rows) => {
        setDrivers(rows);
        // One driver is not a choice, so it is not presented as one. Most
        // pharmacies have exactly one, and "Choose a driver…" made every
        // delivery wait on a dropdown with a single entry in it. The same
        // rule the order screen already applies to a single supplier.
        const active = rows.filter((d) => d.active);
        if (active.length === 1) setDriverId(active[0].id);
      })
      .catch(() => setDrivers([]));
  }, [payHow]);

  // The address it is going to. Taken from the patient the moment a driver is
  // needed, because a delivery to an address nobody typed is a parcel that
  // comes back.
  useEffect(() => {
    if (payHow === "delivery" && !deliverTo && patient?.address) {
      setDeliverTo(patient.address);
    }
  }, [payHow, patient?.id]);
  const [tenders, setTenders] = useState<TenderLine[]>([]);
  /** Paid by medical aid: the card at the counter. */
  const [schemes, setSchemes] = useState<{ id: number; name: string }[]>([]);
  const [aidScheme, setAidScheme] = useState<number | "">("");
  const [aidMember, setAidMember] = useState("");
  const [aidDep, setAidDep] = useState("00");
  const [aidHold, setAidHold] = useState(false);
  const [aidHoldReason, setAidHoldReason] = useState("");
  useEffect(() => {
    if (payHow !== "aid" || schemes.length) return;
    api.get<typeof schemes>("/api/medical-aids").then(setSchemes).catch(() => setSchemes([]));
  }, [payHow]);
  // A member's script is a claim unless somebody says otherwise.
  useEffect(() => {
    if (payHowSet.current) return;
    setPayHow(patient?.medical_aid_id ? "aid" : "now");
  }, [patient?.medical_aid_id]);
  // Whatever the patient's record holds, as the starting point: most members
  // show the same card every month, and retyping it is where numbers go wrong.
  useEffect(() => {
    setAidScheme(patient?.medical_aid_id ?? "");
    setAidMember(patient?.medical_aid_number ?? "");
    setAidDep(patient?.dependent_code || "00");
    setAidHold(false);
    setAidHoldReason("");
  }, [patient?.id]);
  const [currencyState, setCurrencyState] = useState<any>(null);
  /** What the patient will actually hand over, once the claim is off it. */
  const [dueNow, setDueNow] = useState(0);
  /** Bumped after a dispensing so the worklist reloads at once. */
  const [worklistNonce, setWorklistNonce] = useState(0);
  const [doneRxId, setDoneRxId] = useState<number | null>(null);
  // ?reprint=<rx id> opens the label preview straight away. Without it a reprint
  // is only reachable in the moments after dispensing, in the same browser
  // session, so nobody could reprint a label for yesterday's script, which is
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
  /** The signed-in person's initials, filled into Checked by.
   *
   *  Somebody is signed in, and it is almost always the person who checked the
   *  script, so making them type two letters they already are on every
   *  dispensing was a keystroke tax with no information in it. Filled in; a
   *  pharmacist checking for somebody else simply types over it. */
  const myInitials = initialsOf(session.me?.full_name, session.me?.username);
  useEffect(() => {
    if (myInitials) setInitials((current) => (current.trim() ? current : myInitials));
  }, [myInitials]);
  /** Which initials box the cursor is in.
   *
   *  The field says what it is while nobody is typing and what to type once
   *  somebody is, the same way the patient, prescriber and medicine searches
   *  do. Two boxes carry it — the one on the bar and the one in Finish — and
   *  both are in the document at the same time, so the focus is named rather
   *  than a boolean that would light up whichever one you are not looking at. */
  const [initialsFocus, setInitialsFocus] = useState<"bar" | "finish" | null>(null);
  const [complianceNotes, setComplianceNotes] = useState("");
  const [controlledLog, setControlledLog] = useState<ControlledDispensing[]>([]);
  const [controlledMeta, setControlledMeta] = useState<Paged<ControlledDispensing> | null>(null);
  const [controlledPage, setControlledPage] = useState(1);
  const [otcMeta, setOtcMeta] = useState<Paged<OTCSale> | null>(null);
  const [otcPage, setOtcPage] = useState(1);

  // OTC
  const [otcProduct, setOtcProduct] = useState<Product | null>(null);
  const [otcQty, setOtcQty] = useState(1);
  /** The expiry read off the pack, when this branch's stock carries none.
   *
   *  Cleared when the medicine changes: a date read off one box says nothing
   *  about the next. */
  const [otcPackExpiry, setOtcPackExpiry] = useState("");
  /** Which lot is going out, when it is not the one the rotation would take. */
  const [otcLot, setOtcLot] = useState<LotChoice>(ROTATION);
  /** A lot chosen by hand on a script line, keyed by the script's own item id
   *  because that is how the server keys it back. Empty for the ordinary
   *  dispensing, where the rotation decides and nobody is asked anything. */
  const [scriptLots, setScriptLots] = useState<Record<number, LotChoice>>({});
  /** Waiting on a supervisor, so the counter says so rather than looking idle. */
  const [otcAuthorising, setOtcAuthorising] = useState(false);
  const [customerName, setCustomerName] = useState("");
  const [indication, setIndication] = useState("");
  const [counselled, setCounselled] = useState(false);
  const [referred, setReferred] = useState(false);
  const [otcNotes, setOtcNotes] = useState("");
  const [tendered, setTendered] = useState("");
  const [otcLog, setOtcLog] = useState<OTCSale[]>([]);
  /* The two registers on this screen load into empty tables, and an empty
     controlled register reads as "nothing was dispensed", which for a
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
    api.get<User[]>("/api/auth/roster").then(setUsers)
      .catch((e) => toast.error(errorText(e, "The list of colleagues could not be loaded.")));
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

  /* A LATE ANSWER MUST NOT REFILL A FIELD SOMEBODY HAS EMPTIED.
   *
   *  Every one of these searches did `api.get(...).then(setResults)` with
   *  nothing watching whether the question still stood. Clearing the box runs
   *  the effect, which empties the list — and then the request for the text that
   *  was there a moment ago comes back and puts it all on screen again. The list
   *  outlives the search that asked for it, and the only way out is to type
   *  something and clear it again quickly enough to win the race.
   *
   *  `stale` closes over this run of the effect. The cleanup sets it before the
   *  next run starts, so an answer to a question nobody is asking any more is
   *  dropped instead of rendered. Same guard on all three lanes. */
  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    let stale = false;
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=8`)
      .then((found) => { if (!stale) setPatients(found); })
      .catch(() => { if (!stale) setPatients([]); });
    return () => { stale = true; };
  }, [patientQ]);


  useEffect(() => {
    if (productQ.length < 2) { setProductResults([]); return; }
    let stale = false;
    // The counter lane asks for the counter range by name, because a
    // pharmacist standing at it should be offered what may be sold there and
    // not everything they are personally allowed to dispense. The script lane
    // names nothing: the server works the range out from this person's own
    // capabilities, which is the question the tab was standing in for.
    api.get<Product[]>(
      `/api/dispensing/products?q=${encodeURIComponent(productQ)}`)
      .then((found) => { if (!stale) setProductResults(found); })
      .catch(() => { if (!stale) setProductResults([]); });
    return () => { stale = true; };
  }, [productQ]);

  /* The over-the-counter tab used to open on twelve medicines nobody had asked
   * for: the first twelve in the catalogue, alphabetically, which at CareXpress
   * is cable ties, a Barbie toy and a storage box. That wall of merchandise was
   * the first thing on the screen and it pushed the consultation record — the
   * part that is actually being filled in — off the bottom of the window.
   *
   * A search shows results. Nothing else does, here as on the prescription tab. */

  /** What this country calls its schedules. "S5" in South Africa, "PP10" in
   *  Zimbabwe — and this screen said "S5" to both until now. */
  const schedCode = useScheduleCodes();
  /** The controlled schedules and the counter ones, named the way the law here
   *  names them.
   *
   *  Listed rather than given as a range. "S0 to S2" reads as a span because
   *  the South African codes are numbered; the Zimbabwean ones are not, and
   *  "HR to PIM" reads as a span between two things that have no order. */
  const counterCodes = `${schedCode(0)}, ${schedCode(1)} and ${schedCode(2)}`;

  const policyFor = (schedule: number) => policies.find((p) => p.schedule === schedule);
  const highestSchedule = items.reduce((m, i) => Math.max(m, i.product.schedule || 0), 0);
  const activePolicy = policyFor(highestSchedule);
  /* THE COMPLIANCE RECORD IS THE LINES' QUESTION, NOT THE TAB'S.
   *
   *  The server decides it from the highest schedule on the script:
   *  `policy_for(max schedule).route == "controlled"`, then asks for each
   *  verification that policy names. This screen decided it from the route tab
   *  the dispenser happened to be on — so a Schedule 5 line captured on the
   *  Prescription tab was refused at the last step with
   *
   *    "Prescription preparation - Tenth Schedule requires: patient identity
   *     verification, original prescription sighted, prescriber verification."
   *
   *  and there was nowhere on the screen to give any of the three: the section
   *  holding those tickboxes only rendered on the Dangerous Drugs tab, and the
   *  fields were dropped from the payload for the same reason. The button was
   *  enabled, the dispensing was impossible, and the sentence named things the
   *  dispenser could not do. The same shape of dead end as the blocking
   *  warning that could never be acknowledged.
   *
   *  Read from the lines, so the two cannot disagree — and per flag, so this
   *  asks for exactly what the jurisdiction pack asks for and no more.
   *
   *  When the policies have not loaded, the schedule decides and all three are
   *  asked for: the failure has to be "this screen asked for too much", never
   *  "this screen refused to ask". */
  /* WHETHER THERE IS A PRESCRIPTION IN THE ROOM.
   *
   *  The last question on this screen the system cannot answer for itself, and
   *  it turns out it nearly can: a medicine that `requires_prescription` was
   *  bought against one, and a basket with none of those in it is a counter
   *  sale. So the dispenser is not asked. The patient and the prescriber
   *  appear when a line calls for them and stay out of the way when none does,
   *  which is what the three tabs were arranging by hand.
   *
   *  Any line is enough. A basket holding paracetamol and an antibiotic is a
   *  script, because the antibiotic is. */
  /** Whether anything in the basket has to be counselled before hand-over. */
  const counsellingWanted = items.some(
    (i) => policyFor(i.product.schedule || 0)?.counselling_required);
  const needsScript = items.some(
    (i) => policyFor(i.product.schedule || 0)?.requires_prescription
      ?? (i.product.schedule || 0) >= 3);
  const needsCompliance = activePolicy
    ? activePolicy.route === "controlled"
    : highestSchedule >= 5;
  const policyWants = (flag: keyof SchedulePolicy) =>
    needsCompliance && (activePolicy ? !!activePolicy[flag] : true);
  const needsIdVerified = policyWants("requires_id_verification");
  const needsScriptSighted = policyWants("requires_script_sighted");
  const needsPrescriberVerified = policyWants("requires_prescriber_verification");
  const complianceDone =
    (!needsIdVerified || idVerified)
    && (!needsScriptSighted || scriptSighted)
    && (!needsPrescriberVerified || prescriberVerified);
  // The policy field is still called requires_witness — it is the jurisdiction
  // pack's name for "this needs a second signature". What satisfies it is now
  // the checking pharmacist's initials.
  // Whether an initial is required is a *setting* on the server —
  // `dispensing.require_pharmacist_initial`, and when it is on it applies to
  // every dispensing, not only to controlled schedules. This screen used to
  // decide for itself from the schedule alone, so on an ordinary prescription it
  // enabled the button, never asked for initials, and the server refused the
  // dispensing with a 400 that the dispenser could do nothing about. Two rules
  // for one question, and the one the user could see was the wrong one.
  const [initialAlwaysRequired, setInitialAlwaysRequired] = useState(false);
  /** When a counselling record is required: the pharmacy's setting. */
  const [counselRule, setCounselRule] = useState<"never" | "controlled" | "always">("never");
  /** What the patient was told on this script, and anything the points miss. */
  const [counselPoints, setCounselPoints] = useState<string[]>([]);
  const [counselNotes, setCounselNotes] = useState("");
  /** The code scanned off each line's pack, by product — present only once the
   *  pack has matched. CareXpress To-Be blueprint §5: the medicine picked is
   *  checked against the line before it goes out. The server resolves every
   *  code again, so this is what the screen shows, not what it is trusted on. */
  const [scanChecks, setScanChecks] = useState<Record<number, string>>({});
  /** Whether this pharmacy will not dispense a pack nobody scanned. */
  const [requireScan, setRequireScan] = useState(false);

  /** Lines that can only go out from stock with no expiry recorded, and the date
   *  read off the pack for each.
   *
   *  The CareXpress opening stock came in as one batch per product with no
   *  expiry, so ninety-two products in a hundred could not be dispensed at all —
   *  and the refusal came after the money had been chosen, calling the stock
   *  expired. The dispenser is asked instead, before paying, for the date on the
   *  pack in their hand; the server writes it onto the stock, and the label
   *  prints with it. The shelf gets dated one dispensing at a time. */
  const [expiryNeeded, setExpiryNeeded] = useState<
    { product_id: number; name: string; needed_units: number; dated_units: number; undated_units: number }[]>([]);
  const [packExpiry, setPackExpiry] = useState<Record<number, string>>({});
  const stockKey = items.map((i) => `${i.product.id}:${i.quantity}`).join(",");
  useEffect(() => {
    if (!items.length) { setExpiryNeeded([]); return; }
    const t = window.setTimeout(() => {
      api.post<typeof expiryNeeded>("/api/dispensing/expiry-needed", {
        lines: items.map((i) => ({ product_id: i.product.id, quantity: i.quantity })),
      }).then(setExpiryNeeded).catch(() => setExpiryNeeded([]));
    }, 250);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockKey]);
  /** The first line still needing a date from its pack, or a date already past. */
  const expiryProblem = (): string => {
    const today = localIsoDate();
    const past = expiryNeeded.find((l) => packExpiry[l.product_id] && packExpiry[l.product_id] < today);
    if (past) return `The pack of ${past.name} has expired. Take another from the shelf.`;
    const missing = expiryNeeded.find((l) => !packExpiry[l.product_id]);
    if (missing) return `Enter the expiry printed on the pack of ${missing.name}.`;
    return "";
  };
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
        // Read the same way the server reads it: anything it does not
        // recognise is "never", so the screen never demands what the server
        // would not.
        const counsel = String(all.find((x: any) => x?.key === "dispensing.require_counselling")?.value
                               ?? "never").trim().toLowerCase();
        setCounselRule(counsel === "always" || counsel === "controlled" ? counsel : "never");
        const scanRule = all.find((x: any) => x?.key === "dispensing.require_scan_check")?.value;
        setRequireScan(scanRule === true || scanRule === "true");
        // Whether a sale sent to the till takes the dispenser with it. A
        // pharmacy with a cashier says stay; one person doing both says go.
        const after = String(all.find((x: any) => x?.key === "dispensing.after_till")?.value
                             ?? "stay").trim().toLowerCase();
        setGoToTill(after === "go");
      })
      .catch(() => undefined);   // the server enforces it regardless
  }, []);

  const needsInitials =
    initialAlwaysRequired ||
    items.some((i) => policyFor(i.product.schedule)?.requires_witness);
  /** Whether this script cannot go without a counselling record. Decided from
   *  the lines, like the compliance record, not from the tab. */
  const counsellingRequired =
    counselRule === "always" || (counselRule === "controlled" && needsCompliance);
  const counsellingMissing = counsellingRequired && counselPoints.length === 0;
  const unscannedLines = requireScan ? items.filter((i) => !scanChecks[i.product.id]).length : 0;
  const scanMissing = unscannedLines > 0;

  const navigate = useNavigate();
  const [showKeys, setShowKeys] = useState(false);
  /** Somebody at the counter who is not on file yet. */
  const [newPatient, setNewPatient] = useState(false);
  // A medicine the catalogue has never heard of, added without leaving the
  // script. Holds the draft rather than a boolean so that a refusal can hand
  // the typing back instead of losing it.
  const [newMedicine, setNewMedicine] = useState<MedicineDraft | null>(null);
  /** Making something up at the counter, to go on this script. */
  const [mixing, setMixing] = useState(false);
  /** A prescriber nobody has written down yet.
   *
   *  A script arrives from a doctor who is not on file and the search said
   *  "no prescriber on file matches" and stopped there — with no way to add one
   *  from any screen in the system. The dispensing could not go on at all, so
   *  the pharmacy either picked the wrong prescriber or turned the patient
   *  away. Captured here, beside the search that failed. */
  const [newDoctor, setNewDoctor] = useState<null | {
    name: string; practice_number: string; ahfoz_number: string; phone: string }>(null);
  const [altering, setAltering] = useState(false);
  /** Pricing a basket for somebody deciding, rather than dispensing it.
   *
   *  A quote is the same capture with nothing committed: no stock moves, no
   *  claim is raised, no register entry is written. Pharmacies are asked for
   *  one several times a day, "what would this cost me", and the only way to
   *  answer was to capture the script and not press the button, which leaves a
   *  draft behind for somebody else to wonder about. */
  const [quoting, setQuoting] = useState(false);

  /* WHAT WAS BEING CAPTURED WHEN SOMEBODY WALKED AWAY.
   *
   *  Leaving this screen mid-script unmounted it and took the capture with it,
   *  and leaving it mid-script is normal: a stock lookup, a price, a patient's
   *  history, the telephone. It is kept rather than prompted for — the reasons
   *  are in hooks/scriptDraft.ts, with what is deliberately not kept (the
   *  compliance ticks and the initials, which are somebody's statement that
   *  they checked something, not typing).
   *
   *  `draftReady` is the ordering, and it is load-bearing. Both effects run in
   *  the same pass on mount; without it the saving one would run with the
   *  empty script of first render and wipe the very draft the other was about
   *  to restore. It gates saving until the restore has been through a render,
   *  so the first thing saved is what came back. */
  const [draftReady, setDraftReady] = useState(false);
  useEffect(() => {
    if (draftReady || !session.me) return;
    const kept = readScriptDraft<DraftItem>(session.me.id);
    if (kept) {
      setItems(kept.items);
      if (kept.patient) setPatient(kept.patient as Patient);
      setDoctorId(kept.doctorId);
      setQuoting(kept.quoting);
      const who = kept.patient
        ? ` for ${(kept.patient as Patient).first_name} ${(kept.patient as Patient).last_name}`
        : "";
      toast.ok(`Picked up where you left off: ${kept.items.length} `
               + `line${kept.items.length === 1 ? "" : "s"}${who}. Escape clears it.`);
    }
    setDraftReady(true);
  }, [draftReady, session.me, toast]);

  useEffect(() => {
    if (!draftReady || !session.me) return;
    writeScriptDraft<DraftItem>({
      userId: session.me.id, patient, doctorId, quoting, items,
    });
  }, [draftReady, session.me, patient, doctorId, quoting, items]);

  /** Start again, cleanly. */
  function newScript() {
    clearScriptDraft();
    setItems([]); setPatient(null); setPatientQ(""); setDoneSale(null);
    // The prescriber belongs to the script, so it goes with it. It was left
    // behind here, which never showed while every fresh visit to the screen
    // started blank: now that a part-typed script comes back, pressing New
    // script left the previous doctor attached to a script that no longer
    // exists — a prescriber nobody chose, on the next patient's supply.
    setDoctorId(""); setDoctorQ("");
    setFromRx(null); setQuoting(false); aiCheck.reset();
    setFinishing(null); setChecking(null); setEditing(null); setLineChecks({}); setLaneOpen(null);
    setPrintPick({});
    setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
    setInitials(myInitials); setIdNumber(""); setComplianceNotes("");
    setCounselPoints([]); setCounselNotes(""); setScanChecks({}); setPackExpiry({});
    // A new script is a new number: whatever was dispensed while this screen
    // was open has taken one since it last asked.
    refreshNextNumber();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  /** The queued script this screen was opened from, if any.
   *
   *  Without it, picking a line off the worklist loaded only the patient and
   *  the dispenser re-typed the medicine, which created a *second*
   *  prescription and dispensed that one. The queued line was never touched,
   *  so the worklist could not go down however many people you served. It is
   *  cleared the moment the basket stops matching the script, because at that
   *  point what is on screen is no longer the thing that was queued. */
  const [fromRx, setFromRx] = useState<
    { id: number; number: string; draft?: boolean; date?: string } | null>(null);

  /** The open hold on the script on screen, if somebody put it down.
   *
   *  CareXpress To-Be blueprint §8. A script waiting on a prescriber's call used
   *  to look exactly like one waiting to be dispensed. Held, it says why on the
   *  bar, the button will not go, and the worklist marks it — and the server
   *  refuses it regardless of what this screen believes. */
  const [hold, setHold] = useState<HoldSummary | null>(null);
  /** Work the counter started and need not stand and watch. */
  const doing = useDoing();
  /** Scripts whose cancellation is still in flight: off the rail already,
   *  because the decision was made when the reason was typed. */
  const [cancelling, setCancelling] = useState<number[]>([]);
  /** The script on screen, readable from inside work that outlives this render. */
  const fromRxRef = useRef<{ id: number; number: string } | null>(null);
  useEffect(() => { fromRxRef.current = fromRx; }, [fromRx]);
  /** The camera, for a counter with no scanner on it. */
  const [cameraOpen, setCameraOpen] = useState(false);
  /** A pack the catalogue does not know yet, waiting to be told what it is. */
  const [unknownCode, setUnknownCode] = useState("");
  /** Whether a sale sent to the till should take this screen with it. */
  const [goToTill, setGoToTill] = useState(false);
  const goToTillRef = useRef(false);
  useEffect(() => { goToTillRef.current = goToTill; }, [goToTill]);
  /** Whether the dispenser has moved on to somebody else while work is in
   *  flight. Work that lands afterwards must not take their screen. */
  const itemsRef = useRef<DraftItem[]>([]);
  const patientRef = useRef<Patient | null>(null);
  useEffect(() => { itemsRef.current = items; }, [items]);
  useEffect(() => { patientRef.current = patient; }, [patient]);
  const [holdReasons, setHoldReasons] = useState<{ code: string; label: string }[]>([]);
  const [holding, setHolding] = useState(false);
  const [holdReason, setHoldReason] = useState("");
  const [holdNote, setHoldNote] = useState("");
  const loadHold = useCallback((rxId: number | null) => {
    if (!rxId) { setHold(null); return; }
    api.get<HoldSummary[]>(`/api/prescriptions/${rxId}/holds`)
      .then((all) => setHold(all.find((h) => h.open) ?? null))
      .catch(() => setHold(null));
  }, []);
  useEffect(() => {
    loadHold(fromRx && !fromRx.draft ? fromRx.id : null);
  }, [fromRx?.id, fromRx?.draft, loadHold]);
  /** Releasing a hold is a decision about why it was placed.
   *
   *  Asked of the resolved rule, not of the role. A role comparison in the
   *  browser cannot see a ceiling, an hour window, a branch scope or a denial
   *  that beats a grant, and the way it fails is a button that works until
   *  somebody is granted something by name. */
  const mayReleaseHold = session.can("script.manage");

  /** Taking a script that never went out off the worklist
   *  (backend/app/services/script_cancel.py). A saved, undispensed script had
   *  no way off the queue — including the copies refused dispensings left
   *  behind — so it sat there looking like a patient waiting. */
  /** The script the Cancel dialog is about — the one open on screen, or one
   *  picked from the worklist without opening it. */
  const [cancelTarget, setCancelTarget] = useState<
    { id: number; number: string; patient?: string; product?: string; lines?: number } | null>(null);
  function openCancel(target: NonNullable<typeof cancelTarget>) {
    // A reason the server refused comes back with the script it was typed for:
    // "already dispensed in part" is an answer about the script, not about the
    // wording, and nobody should retype a sentence to read the same refusal.
    setCancelReason(refused.current?.id === target.id ? refused.current.reason : "");
    setCancelTarget(target);
  }
  /** The last cancellation the server would not take. */
  const refused = useRef<{ id: number; reason: string } | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  /** A scanner is a keyboard that types very fast and presses Enter, and the
   *  dispenser is holding a pack in one hand. Reading it anywhere on the screen
   *  means they do not have to click into the medicine box first — and the
   *  detector puts back whatever the burst typed into whichever field the caret
   *  happened to be in. Off while a dialog owns the keyboard: a code typed into
   *  a cancellation reason is not a pack being checked. */
  // One subscription, both scanners. The workstation owns the counter
  // scanner and the borrowed phone; this screen says what it is called and
  // when it is ready, and takes whatever arrives from either.
  useScanFeed(
    "Dispensing",
    (code, _format, source) => { setProductQ(""); void scanPack(code, source); },
    finishing === null && !cameraOpen && !cancelTarget && !holding
      && !mixing && !newPatient && !altering,
  );


  const mayCancelScript = session.can("script.manage");

  /** Cancel a script, without standing there while it happens.
   *
   *  The dialog closes on the keystroke and the row goes at once, because the
   *  decision was made when the reason was typed. The work carries on in the
   *  tray, and if the server refuses — "already dispensed in part", which is an
   *  answer to act on with Alter script — the row comes back and the reason is
   *  handed back with it, so it can be re-opened rather than retyped.
   */
  function cancelScript() {
    if (!cancelTarget || cancelReason.trim().length < 3) return;
    const { id, number } = cancelTarget;
    const reason = cancelReason.trim();
    const wasOnScreen = fromRx?.id === id;
    // Kept so a refusal can put it back the way it was opened.
    const patientId = patient?.id ?? null;
    const schedule = Math.max(0, ...items.map((i) => i.product.schedule || 0));

    setCancelTarget(null);
    setCancelReason("");
    setCancelling((live) => [...live, id]);
    if (wasOnScreen) newScript();

    doing.run({
      label: `Cancelling ${number}`,
      said: `${number} is cancelled and off the worklist.`,
      run: () => api.post(`/api/prescriptions/${id}/cancel`, { reason }),
      done: () => {
        setCancelling((live) => live.filter((x) => x !== id));
        setWorklistNonce((n) => n + 1);
      },
      undo: () => {
        // Back on the rail, with what was typed, ready to be looked at again —
        // and back on the screen if that is where it was, because a refusal
        // ("already dispensed in part; use Alter script") is answered on the
        // script itself and cannot be answered from an empty screen.
        setCancelling((live) => live.filter((x) => x !== id));
        setWorklistNonce((n) => n + 1);
        refused.current = { id, reason };
        if (wasOnScreen && !itemsRef.current.length && !patientRef.current) {
          void openQueued({ patient_id: patientId, prescription_id: id, schedule });
        }
      },
    });
  }

  async function openHoldDialog() {
    if (holdReasons.length === 0) {
      try {
        setHoldReasons(await api.get<{ code: string; label: string }[]>("/api/prescriptions/holds/reasons"));
      } catch (e) {
        toast.error(errorText(e, "The hold reasons could not be loaded."));
        return;
      }
    }
    setHoldReason("");
    setHoldNote("");
    setHolding(true);
  }

  function placeHold() {
    if (!fromRx || !holdReason) return;
    const script = fromRx;
    const code = holdReason;
    const note = holdNote.trim();
    const before = hold;
    // Held on screen straight away: the decision is made, and the label the
    // server gives it back is the one this shows a moment later.
    const label = (holdReasons.find((r) => r.code === code)?.label) || code;
    setHold({ reason: label, placed_by: "", placed_at: new Date().toISOString() } as HoldSummary);
    setHolding(false);

    doing.run({
      label: `Holding ${script.number}`,
      said: `${script.number} is on hold: ${label.toLowerCase()}.`,
      run: () => api.post<HoldSummary>(`/api/prescriptions/${script.id}/holds`,
                                       { reason_code: code, note }),
      done: (placed: HoldSummary) => {
        if (fromRxRef.current?.id === script.id) setHold(placed);
        setWorklistNonce((n) => n + 1);
      },
      undo: () => {
        if (fromRxRef.current?.id === script.id) setHold(before);
        setWorklistNonce((n) => n + 1);
      },
    });
  }

  /** A pack scanned into the medicine box.
   *
   *  On a saved script it is a check: a pack on the script ticks its line; a
   *  pack that is not is refused out loud, because that is precisely the error
   *  the check exists to catch. While capturing a new script it is the quicker
   *  way to find the medicine, and the line starts out checked — it is that
   *  pack. An expired GS1 pack is refused either way. */
  async function scanPack(code: string, source?: string) {
    try {
      const res = await api.post<any>("/api/scan", {
        code, context: "dispense", source,
        prescription_id: fromRx && !fromRx.draft ? fromRx.id : null,
      });
      // A NUMBER THE CAMERA GUESSED AT, AT A DISPENSING BENCH.
      //
      // The phone already made the person holding the pack agree to the
      // digits. This is the second look, and it is a different one: not "are
      // these the right digits" but "is this the right medicine". The
      // server decides that a dispensing context needs it; this screen only
      // has to ask.
      if (res.confirm?.needed && res.confirm.level === "name" && res.product) {
        const sure = await askConfirm({
          title: "Is this the pack in your hand?",
          body: `${res.product.name} ${res.product.strength || ""}`.trim()
                + ". " + res.confirm.why,
          confirmLabel: "Yes, that is the pack",
          destructive: !res.confirm.verified,
        });
        if (!sure) return;
      }
      // A SCRIPT, NOT A PACK.
      //
      // The label this pharmacy printed carries a Code 128 of the script
      // number along its bottom edge. Scanning one used to say "nothing is
      // stocked under that code", because every scan resolved to a product.
      // Now it opens the script, which is what somebody holding a printed
      // label and looking at a worklist of four Moyos actually wants.
      if (res.kind === "prescription" && res.prescription) {
        const rx = res.prescription;
        if (!rx.may_dispense) {
          // Said and stopped. The refusal is the whole value of the scan:
          // learning at the counter that this was cancelled or already
          // dispensed is the point, and opening it anyway would invite
          // somebody to hand it over.
          toast.error(rx.refuse || rx.says || `${rx.rx_number} cannot be dispensed.`);
          return;
        }
        if (!rx.patient_id) {
          toast.warn(`${rx.rx_number} has no patient attached, so it cannot be opened here.`);
          return;
        }
        await openQueued({ patient_id: rx.patient_id,
                           prescription_id: rx.id,
                           schedule: rx.schedule ?? 0 });
        toast.ok(`${rx.rx_number} for ${rx.patient}.`);
        return;
      }
      if (!res.found) {
        // Two thirds of this catalogue arrived with no barcode at all, so an
        // unrecognised pack is the ordinary case rather than an error. The
        // dispenser is holding it and knows what it is; asking is quicker than
        // a search, and the answer is kept for everybody.
        setUnknownCode(code);
        return;
      }
      if (res.expired) {
        toast.error(res.warnings.find((w: string) => w.includes("expired")) || "That pack has expired.");
        return;
      }
      // A GS1 pack carries its own expiry. Where the stock has none recorded,
      // the scan answers the question Finish would otherwise ask.
      if (res.expiry_date && expiryNeeded.some((l) => l.product_id === res.product.id)) {
        setPackExpiry((cur) => ({ ...cur, [res.product.id]: res.expiry_date }));
      }
      const line = items.find((i) => i.product.id === res.product.id);
      if (line) {
        setScanChecks((cur) => ({ ...cur, [res.product.id]: code }));
        toast.ok(`${lineName(line.product)}. The pack matches the script.`);
        return;
      }
      if (fromRx && !fromRx.draft) {
        toast.error(`${res.product.name} is not on this script. Check the pack against what was prescribed.`);
        return;
      }
      // NO LANE CHECK. A scanned medicine goes on the script if this person
      // may dispense it, and that is the server's answer, asked of the
      // permission matrix when the search offered it and asked again when the
      // script is dispensed. This used to refuse a controlled pack for being
      // scanned on the wrong tab and send the dispenser to another one, which
      // cleared the basket they had just built.
      const full = await api.get<any>(`/api/products/${res.product.id}`);
      addItem(full.product ?? full);
      setScanChecks((cur) => ({ ...cur, [res.product.id]: code }));
    } catch (e) {
      toast.error(errorText(e, "That scan could not be read."));
    }
  }

  // A line taken off takes its scan with it, so a medicine removed and typed
  // back on does not come back already checked.
  useEffect(() => {
    setScanChecks((cur) => {
      const onScreen = new Set(items.map((i) => i.product.id));
      const kept = Object.fromEntries(Object.entries(cur).filter(([pid]) => onScreen.has(Number(pid))));
      return Object.keys(kept).length === Object.keys(cur).length ? cur : kept;
    });
  }, [items]);

  async function releaseHold() {
    if (!hold || !fromRx) return;
    try {
      await api.post(`/api/prescriptions/holds/${hold.id}/clear`, { note: "" });
      setHold(null);
      setWorklistNonce((n) => n + 1);
      toast.ok(`${fromRx.number} is released and can be dispensed.`);
    } catch (e) {
      toast.error(errorText(e, "That hold could not be released."));
    }
  }
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);

  /** The number this script will be given, shown before it is given.
   *
   *  The screen used to say "New script · numbered on dispensing", which is
   *  true and useless: the number is what everything else in the building is
   *  filed under, and the dispenser could not see it until the medicine had
   *  gone out. It is read here on open, and again after each dispensing, so
   *  coming back to the screen shows the next one.
   *
   *  A prediction, not a reservation — see the endpoint for why nothing is
   *  held. Two tills are told the same number and the first to dispense takes
   *  it, so the line beneath says the number is taken on dispensing rather
   *  than claiming this script already owns it. If the read fails the header
   *  falls back to the words it used to show; a number nobody can reach is
   *  not worth an error on a screen that is otherwise working. */
  const [nextNumber, setNextNumber] = useState<string | null>(null);
  const refreshNextNumber = useCallback(() => {
    api.get<{ number: string }>("/api/prescriptions/next-number")
      .then((d) => setNextNumber(d.number || null))
      .catch(() => setNextNumber(null));
  }, []);
  useEffect(() => { refreshNextNumber(); }, [refreshNextNumber]);
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
    (!needsCompliance || (items.length > 0 && complianceDone)) &&
    !counsellingMissing && !hold && !scanMissing;

  // One declaration drives the bindings, the bottom bar and the help overlay,
  // so a shortcut can never exist without being documented.
  // The numbers are the incumbent's, not ours.
  //
  // Three of these already existed under different keys — the interaction check
  // was on F6, repeats due on F8, the queue on F9 — chosen against nothing in
  // particular. Where their number and ours disagree, theirs wins: the whole
  // value of a function key is that the hand goes there without the person
  // deciding to, and a hand that has pressed F6 for authorisations for fifteen
  // years will press F6 for authorisations here.
  //
  // Nothing is lost by the two that give up a key. The interaction check is a
  // button on the screen and runs itself as the basket changes; the queue is
  // the panel occupying the right-hand third of the screen at all times.
  /* The dose check, on the rows rather than in a panel.
   *
   *  It reads the directions on each line and says when a daily dose is over a
   *  maximum, or when the directions could not be read at all — the second
   *  being the common case and the useful one, because a line nobody can parse
   *  is a line nobody has checked.
   *
   *  The name is rebuilt exactly as the server builds it, because that is the
   *  string the finding comes back under. */
  const doseScreen = useDoseScreen(
    patient?.id ?? null,
    items.map((i) => ({
      product_id: i.product.id,
      name: `${i.product.name} ${i.product.strength || ""}`.trim(),
      instructions: i.dosage_instructions,
      quantity: i.quantity,
    })),
  );

  // The dose check holds the dispense on a dose over a maximum. The panel used
  // to tell the page so; with the panel gone `ixMajor` stayed at 0 whatever the
  // directions said, and the gate was open without anybody deciding it should be.
  useEffect(() => { setIxMajor(doseScreen.major); }, [doseScreen.major]);

  /** Counter messages, fetched once: counted on the bar, listed in Finish. */
  const counter = useCounterMessages({
    patientId: patient?.id,
    productIds: items.map((i) => i.product.id),
    medicalAidId: patient?.medical_aid_id,
    prescriptionId: fromRx?.id ?? null,
    onBlockingChange: setBlocked,
  });

  /** The question a line check answers: this patient, these lines, these
   *  directions. Any change makes every previous answer stale. */
  const basketSig = `${patient?.id ?? 0}|` + items
    .map((i) => `${i.product.id}=${i.quantity}=${i.dosage_instructions}`).join("|");

  /** Check one line: dose, and interactions with the rest and with history. */
  function runLineCheck(it: DraftItem) {
    const id = it.product.id;
    const sig = basketSig;
    setLineChecks((m) => ({ ...m, [id]: { sig, status: "loading" } }));
    api.post<Screen>("/api/dispensing/interaction-screen", {
      patient_id: patient?.id ?? null,
      product_ids: items.map((i) => i.product.id),
      lines: items.map((i) => ({
        product_id: i.product.id, instructions: i.dosage_instructions, quantity: i.quantity,
      })),
    })
      // Dropped if this line was checked again meanwhile: an answer arriving
      // late must not overwrite the answer to the newer question.
      .then((screen) => setLineChecks((m) => (m[id]?.sig === sig
        ? { ...m, [id]: { sig, status: "ready", screen } } : m)))
      .catch((e) => setLineChecks((m) => (m[id]?.sig === sig
        ? { ...m, [id]: { sig, status: "ready", error: errorText(e) } } : m)));
  }

  function lineState(it: DraftItem) {
    const c = lineChecks[it.product.id];
    if (!c || c.sig !== basketSig) return "idle" as const;
    if (c.status === "loading") return "loading" as const;
    if (c.error) return "error" as const;
    const f = findingsFor(c.screen, lineName(it.product));
    return f.major ? "major" as const : f.any ? "minor" as const : "clean" as const;
  }

  /** The shield: first press checks, a press on a finished check opens it. */
  function onCheckIcon(it: DraftItem) {
    const c = lineChecks[it.product.id];
    if (c && c.sig === basketSig) {
      if (c.status === "ready") setChecking(it.product.id);
      return;
    }
    runLineCheck(it);
  }

  function removeLine(idx: number) {
    const id = items[idx]?.product.id;
    setItems(items.filter((_, i) => i !== idx));
    setEditing(null); setChecking(null);
    setOpenItem((o) => Math.max(0, Math.min(o, items.length - 2)));
    if (id !== undefined) {
      setLineChecks((m) => { const next = { ...m }; delete next[id]; return next; });
    }
  }

  /** Anything the first stage of Finish would show. */
  function needsSettling() {
    return (counter.data?.count ?? 0) > 0 || doseScreen.major > 0 || expiryNeeded.length > 0
      || !!(coverage && (!coverage.all_claimable || coverage.authorisation_required));
  }

  /** Why Proceed is held, or "". Only what has to be acknowledged holds it;
   *  advisories are read, not signed. */
  function settleBlocks() {
    const n = counter.outstanding.length;
    if (n > 0) return `Acknowledge the ${n === 1 ? "blocking warning" : `${n} blocking warnings`} to continue.`;
    if (doseScreen.major > 0 && !ixAcknowledged) return "Confirm the dose over the maximum to continue.";
    const expiry = expiryProblem();
    if (expiry) return expiry;
    return "";
  }

  /** Whether a document prints on dispense: the pharmacist's choice for this
   *  script, else what the script itself calls for. */
  /** What prints unless somebody says otherwise, decided by what is happening.
   *
   *  Each of these follows the money rather than a setting: if the customer is
   *  paying here they get a receipt, if a funder is being billed there is a
   *  claim copy, if a driver is taking it there is a delivery label. A tile
   *  somebody has to remember to press every single time is a tile that is
   *  forgotten on the one sale it mattered for.
   */
  function printDefault(kind: roll.DocKind) {
    if (kind === "label") return true;
    // Money taken at this counter is a sale, and a sale hands over a tax
    // invoice. "Take payment now" printed nothing at all: the patient paid at
    // the dispensary and walked away without a receipt, which the till would
    // never have allowed.
    if (kind === "receipt") return payHow === "now" || payHow === "aid";
    if (kind === "claim") return !!split?.covered || payHow === "aid";
    if (kind === "delivery") return payHow === "delivery";
    // Off, now that the dispensing label carries the barcode itself. MCAZ
    // expects a dispensed script to have one and it does; this kind is the
    // second, separate sticker, and defaulting it on meant sticking two labels
    // on every pack to satisfy a requirement one of them already met.
    if (kind === "barcode") return false;
    return false;
  }
  function willPrint(kind: roll.DocKind) {
    return printPick[kind] ?? printDefault(kind);
  }

  function proceedToPay() {
    if (settleBlocks()) return;
    setSettledFor(basketSig);
    setFinishStage("pay");
  }

  // ---- setting a price by hand -------------------------------------------

  /** Change what this line charges, per unit, on somebody's code.
   *
   *  Catalogue prices come off a supplier file and they are wrong often enough
   *  that a dispenser has to be able to change one — a margin loaded wrong on
   *  import, a figure that wants rounding to something a person can hand over
   *  notes for. Refusing outright does not stop it: it moves it to a calculator
   *  and a handwritten slip, where nothing is recorded at all.
   *
   *  So it is allowed and it costs a code, in the line editor and on the table
   *  alike. One rule in both places, because the same act with two different
   *  rules is the kind of thing people work out how to route around.
   *
   *  The price on the screen only moves once the code is accepted. An optimistic
   *  figure would be the one thing on this page it is wrong to show early: money
   *  the patient has been quoted and nobody approved.
   */
  async function setLinePrice(idx: number, asked: PriceAsked): Promise<boolean> {
    const it = items[idx];
    if (!it) return false;
    const { each, keep, reason } = asked;
    const shelf = perUnit(it.product);
    const before = lineEach(it);
    if (!Number.isFinite(each) || each < 0) {
      toast.warn("A price has to be a number, and not a negative one.");
      return false;
    }
    // Nothing typed, or typed back to what it already was. Not an error and not
    // worth a password — a dispenser who tabs through the field has not asked
    // for anything.
    if (Math.abs(each - before) < 0.005) return false;

    setAuthorisingPrice(it.product.id);
    try {
      const said = await guarded<{ id: number; now: number; below_cost?: boolean;
                                   note?: string; approved_by?: string;
                                   kept?: boolean; shelf_price?: number;
                                   margin_percent?: number }>(
        "script.price_set",
        (token) => api.post("/api/price-override", {
          product_id: it.product.id, now: Number(each.toFixed(4)), was: shelf,
          quantity: it.quantity, reason, keep,
        }, token),
        `${lineName(it.product)} · ${money(before)} → ${money(each)} each`,
      );
      if (said === CANCELLED) return false;
      // A script waiting on the worklist is dispensed as itself — this screen
      // fetches it rather than re-creating it — so the price has to reach the
      // line that already exists. Without this it was quoted on screen and the
      // till charged the shelf price, which is the worst way for it to fail.
      if (it.item_id && fromRxRef.current?.id) {
        await api.post(
          `/api/prescriptions/${fromRxRef.current.id}/items/${it.item_id}/price`,
          { price_override_id: said.id });
      }
      setItems((list) => list.map((x, j) => {
        if (j !== idx) return x;
        // Kept for good, the catalogue itself now says this, so the line has no
        // override at all — it is simply priced from the shelf like every other.
        // Leaving one behind would make the row read "set by hand" for ever on
        // a price that is now perfectly ordinary.
        if (said.kept && said.shelf_price !== undefined) {
          return { ...x, price: undefined, priceOverrideId: undefined,
                   product: { ...x.product, unit_price: said.shelf_price } };
        }
        return { ...x, price: said.now, priceOverrideId: said.id };
      }));
      toast.ok(
        said.kept
          ? `${it.product.name} is now ${money(said.now)} each on every script`
            + (said.approved_by ? `, changed by ${said.approved_by}.` : ".")
          : `${it.product.name} now ${money(said.now)} each on this script`
            + (said.approved_by ? `, approved by ${said.approved_by}.` : "."),
      );
      if (said.below_cost && said.note) toast.warn(said.note);
      return true;
    } catch (e) {
      toast.error(errorText(e, "That price could not be authorised."));
      return false;
    } finally {
      setAuthorisingPrice(null);
    }
  }

  /** Set what the scheme is asked for on this line, on somebody's code.
   *
   *  It moves one number. The line still costs what it costs; the scheme is
   *  asked for less and the patient covers the difference, so the script totals
   *  the same and the shortfall moves. A field that quietly reduced the price
   *  would be a discount nobody approved wearing a claim's name.
   *
   *  Like the price beside it, the figure is never sent with the script: what
   *  is quoted is the id of a row written when the code was accepted.
   */
  async function setLineClaim(idx: number, amount: number): Promise<boolean> {
    const it = items[idx];
    if (!it) return false;
    const line = marginFor(it.product.id);
    const before = Number(line?.claim ?? 0);
    if (!Number.isFinite(amount) || amount < 0) {
      toast.warn("What a scheme is asked for has to be a number, and not a negative one.");
      return false;
    }
    if (Math.abs(amount - before) < 0.005) return false;

    setAuthorisingClaim(it.product.id);
    try {
      const said = await guarded<{ id: number; now: number; approved_by?: string }>(
        "script.claim_set",
        (token) => api.post("/api/claim-override", {
          product_id: it.product.id, now: Number(amount.toFixed(2)), was: before,
          quantity: it.quantity, reason: "Set at the counter",
        }, token),
        `${lineName(it.product)} · the scheme asked for ${money(before)} → ${money(amount)}`,
      );
      if (said === CANCELLED) return false;
      // A script off the worklist is dispensed as itself, so the figure has to
      // reach the line that already exists — the same gap the price had, and
      // the same consequence: quoted on screen, billed differently.
      if (it.item_id && fromRxRef.current?.id) {
        await api.post(
          `/api/prescriptions/${fromRxRef.current.id}/items/${it.item_id}/claim`,
          { claim_override_id: said.id });
      }
      setItems((list) => list.map((x, j) => (
        j === idx ? { ...x, claim: said.now, claimOverrideId: said.id } : x)));
      toast.ok(`${schemeName} will be asked for ${money(said.now)} on this line`
        + (said.approved_by ? `, approved by ${said.approved_by}.` : ".")
        + " The patient covers the difference.");
      return true;
    } catch (e) {
      toast.error(errorText(e, "That claim amount could not be authorised."));
      return false;
    } finally {
      setAuthorisingClaim(null);
    }
  }

  /** Back to what the cover rule says. Free, for the same reason clearing a
   *  price is: nobody needs approval to bill a scheme what the rule already
   *  says, and an override you cannot undo is one people avoid starting. */
  function clearLineClaim(idx: number) {
    const it = items[idx];
    if (!it || it.claim === undefined) return;
    setItems((list) => list.map((x, j) => (
      j === idx ? { ...x, claim: undefined, claimOverrideId: undefined } : x)));
    toast.ok(`${it.product.name} is back on what ${schemeName} normally covers.`);
  }

  /** Put the line back on the catalogue's price. Free — nobody needs approval
   *  to charge what the shelf says, and an override you cannot undo without a
   *  manager is one people avoid starting. */
  function clearLinePrice(idx: number) {
    const it = items[idx];
    if (!it || it.price === undefined) return;
    setItems((list) => list.map((x, j) => (
      j === idx ? { ...x, price: undefined, priceOverrideId: undefined } : x)));
    toast.ok(`${it.product.name} is back on the shelf price, ${money(perUnit(it.product))} each.`);
  }

  // ---- editing in the table ---------------------------------------------
  const CELL_ORDER = ["medicine", "qty", "sig", "money"] as const;
  type CellCol = (typeof CELL_ORDER)[number];

  function editingCell(it: DraftItem, col: CellCol) {
    return cellEdit?.id === it.product.id && cellEdit.col === col;
  }

  function startCellEdit(it: DraftItem, idx: number, col: CellCol) {
    setTip(null);
    setOpenItem(idx);
    // The amount column is typed as the AMOUNT, not as a price each: rounding a
    // line off to twelve dollars is what people are actually doing, and making
    // them divide by thirty in their head to do it is why they reach for a
    // calculator. Margin and "keep it for good" are the two answers a bare cell
    // cannot hold, and they live behind the pencil.
    if (col === "money") setPriceDraft((lineEach(it) * (it.quantity || 0)).toFixed(2));
    const next = { id: it.product.id, col,
      orig: col === "qty" ? it.quantity : col === "sig" ? it.dosage_instructions
        : col === "money" ? lineEach(it) * (it.quantity || 0) : "" };
    cellEditRef.current = next;
    setCellEdit(next);
  }

  /** Enter, blur, or moving on: keep what was typed. A quantity that is not a
   *  number of at least one goes back to one rather than onto a label. */
  function finishCellEdit(idx: number, col: CellCol) {
    const cur = cellEditRef.current;
    if (!cur || cur.col !== col) return;
    if (col === "qty" && !(items[idx]?.quantity >= 1)) updateItem(idx, { quantity: 1 });
    cellEditRef.current = null;
    setCellEdit(null);
    if (col === "money") commitTypedAmount(idx);
  }

  /** The amount typed into the money cell, turned into a price each and sent
   *  for authorisation. The cell closes first, so the code is asked for over a
   *  table that is still legible rather than behind a cell held open in a way
   *  that reads as the edit having failed. */
  function commitTypedAmount(idx: number) {
    const it = items[idx];
    const amount = Number(priceDraft);
    const qty = Math.max(1, it?.quantity || 1);
    if (it && priceDraft.trim() !== "" && Number.isFinite(amount)) {
      void setLinePrice(idx, { each: amount / qty, keep: false,
                               reason: "Rounded at the counter" });
    }
    setPriceDraft("");
  }

  /** Double-clicking a money figure on the line editor's rail.
   *
   *  `which` decides what the number means, because the rail shows both and a
   *  box that silently took one or the other would be a box you have to guess
   *  at: Each is a price a unit, Line is what the whole line comes to. They are
   *  the two figures a dispenser actually says out loud, and either can now be
   *  typed where it is shown.
   */
  function startRailEdit(which: "each" | "line" | "claim", value: number,
                         quantity: number) {
    setRailEdit(which);
    setRailDraft((which === "line" ? value * Math.max(1, quantity) : value).toFixed(2));
  }

  /** Keep what was typed on the rail, as a price each, and ask for the code.
   *
   *  Closed before the authorisation is asked for, so the prompt comes up over
   *  a legible editor rather than behind a field held open in a way that reads
   *  as the edit having failed — the same order the table's cells use.
   */
  function commitRailEdit(idx: number, quantity: number) {
    const which = railEdit;
    const typed = Number(railDraft);
    setRailEdit(null);
    setRailDraft("");
    if (which === null || railDraft.trim() === "" || !Number.isFinite(typed)) return;
    if (typed < 0) return;
    const qty = Math.max(1, quantity || 1);
    // Which figure was double-clicked decides what the number means, and the
    // claim is a different act entirely: it moves what the funder is asked for
    // and leaves the price alone.
    if (which === "claim") { void setLineClaim(idx, typed); return; }
    void setLinePrice(idx, {
      each: which === "each" ? typed : typed / qty,
      keep: false,
      reason: "Changed at the counter",
    });
  }

  /** Escape: put back what was there before the double-click. */
  function cancelCellEdit(idx: number) {
    const cur = cellEditRef.current;
    if (!cur) return;
    cellEditRef.current = null;
    if (cur.col === "qty") updateItem(idx, { quantity: Number(cur.orig) || 1 });
    if (cur.col === "sig") updateItem(idx, { dosage_instructions: String(cur.orig) });
    if (cur.col === "money") setPriceDraft("");
    setCellEdit(null);
  }

  function moveCellEdit(it: DraftItem, idx: number, col: CellCol, dir: 1 | -1) {
    if (col === "qty" && !(items[idx]?.quantity >= 1)) updateItem(idx, { quantity: 1 });
    if (col === "money") commitTypedAmount(idx);
    const at = CELL_ORDER.indexOf(col) + dir;
    if (at < 0 || at >= CELL_ORDER.length) {
      cellEditRef.current = null;
      setCellEdit(null);
      return;
    }
    startCellEdit(it, idx, CELL_ORDER[at]);
  }

  function cellKeys(e: ReactKeyboardEvent<HTMLInputElement>, it: DraftItem, idx: number, col: CellCol) {
    // Handled here and marked used, so the page's Escape (which clears the
    // script when nothing is open) never sees it.
    if (e.key === "Enter") { e.preventDefault(); finishCellEdit(idx, col); return; }
    if (e.key === "Escape") { e.preventDefault(); cancelCellEdit(idx); return; }
    if (e.key === "Tab") { e.preventDefault(); moveCellEdit(it, idx, col, e.shiftKey ? -1 : 1); }
  }

  /** A different medicine on the same line, keeping everything else about it. */
  function swapProduct(idx: number, p: Product) {
    const cur = items[idx];
    if (!cur) return;
    if (items.some((x, j) => j !== idx && x.product.id === p.id)) {
      toast.warn(`${p.name} is already on this script.`);
      return;
    }
    setItems(items.map((x, j) => (j === idx ? { ...x, product: p } : x)));
    setLineChecks((m) => { const next = { ...m }; delete next[cur.product.id]; return next; });
    cellEditRef.current = null;
    setCellEdit(null);
  }

  /** Show a cell's full text, only when the cell is actually cutting it off. */
  function showTip(e: ReactMouseEvent<HTMLElement>, full: string, editable: boolean) {
    if (cellEditRef.current) return;
    const shown = e.currentTarget.querySelector<HTMLElement>(".cell-text");
    // A run can be cut as a whole, or one part of it can give way inside it —
    // the ID before the name, in a picked box. Either is text somebody cannot read.
    const cut = (el: Element) =>
      el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
    if (!shown || !(cut(shown) || [...shown.children].some(cut))) { setTip(null); return; }
    const r = e.currentTarget.getBoundingClientRect();
    setTip({ text: full, sub: editable ? "Double-click to edit" : undefined,
             x: r.left, y: r.top, below: r.top < 90 });
  }

  function openFinish(section?: string) {
    if (!patient || items.length === 0) return;
    setEditing(null); setChecking(null); setLaneOpen(null);
    // The warnings first whenever this basket has not been through them, or
    // something in them still has to be acknowledged.
    const settle = needsSettling() && (section === "finish-warnings"
      || settledFor !== basketSig || !!settleBlocks());
    setFinishStage(settle ? "settle" : "pay");
    setFinishing(section ?? "top");
  }

  /** Go to whatever `blockedBecause` names — the field if it is on the page,
   *  the section of Finish if it lives there. Same order of conditions. */
  /** Save the prescriber and put them on this script. */
  async function saveDoctor() {
    if (!newDoctor || !newDoctor.name.trim()) return;
    try {
      const saved = await api.post<Doctor>("/api/doctors", {
        name: newDoctor.name.trim(),
        practice_number: newDoctor.practice_number.trim(),
        ahfoz_number: newDoctor.ahfoz_number.trim(),
        phone: newDoctor.phone.trim(),
      });
      setDoctors((current) => [saved, ...current]);
      setDoctorId(saved.id);
      setDoctorQ("");
      setNewDoctor(null);
      toast.ok(`${saved.name} is on file and on this script.`);
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  function takeMeThere() {
    const focus = (sel: string) => window.setTimeout(
      () => document.querySelector<HTMLElement>(sel)?.focus(), 30);
    // Held: there is nowhere to take anybody. The bar already says why, and the
    // release is beside it.
    if (hold) return;
    if (!patient) return focus("[data-hk='patient']");
    if (doctorId === "") return focus("#step-patient .disp-doctor button, #step-patient .disp-doctor input");
    if (items.length === 0) return focus("[data-hk='product']");
    // The counter's own gate, which the pack sets per medicine. The server
    // refuses the sale without it, so the button has to say so first.
    if (!needsScript && counsellingWanted && !counselled)
      return "Confirm the patient was counselled before handing this over.";
    if (needsCompliance && !complianceDone)
      return openFinish("finish-compliance");
    if (blocked) return openFinish("finish-warnings");
    if (scanMissing) return focus("[data-hk='product']");
    if (needsInitials && !initials.trim()) return focus("#disp-initials");
    if (counsellingMissing) return openFinish("finish-counselling");
    return openFinish(ixMajor > 0 && !ixAcknowledged ? "finish-warnings" : undefined);
  }

  // Finish closes itself when the dispensing lands: the outcome is on the bar.
  useEffect(() => { if (doneSale) setFinishing(null); }, [doneSale]);

  // Wherever Finish opens, the cursor goes where the work is. Settling: the first
  // thing to acknowledge, else Proceed. Paying: the section asked for, else the
  // initials if they are missing, else Dispense — so the common case is F12, F12.
  useEffect(() => {
    if (finishing === null) return;
    const t = window.setTimeout(() => {
      const box = document.querySelector<HTMLElement>(".disp-finish");
      if (!box) return;
      box.scrollTop = 0;
      if (box.classList.contains("is-settle")) {
        (box.querySelector<HTMLElement>(".fin-item-act .btn:not([disabled])")
          ?? box.querySelector<HTMLElement>(".fin-proceed:not([disabled])")
          ?? box.querySelector<HTMLElement>(".finish-foot button"))?.focus();
        return;
      }
      const section = finishing === "top" || finishing === "finish-warnings"
        ? null : document.getElementById(finishing);
      const initialsBox = box.querySelector<HTMLInputElement>("#finish-initials");
      const target = section?.querySelector<HTMLElement>("input, button")
        ?? (initialsBox && !initialsBox.value ? initialsBox : null)
        ?? box.querySelector<HTMLElement>(".fin-dispense:not([disabled])")
        ?? box.querySelector<HTMLElement>(".finish-foot button");
      target?.focus();
    }, 40);
    return () => window.clearTimeout(t);
  }, [finishing, finishStage]);

  const hotkeys: Hotkey[] = [
    // Mix — a preparation made up here rather than dispensed from a box.
    // Made up here, onto the script in front of us — not a different screen
    // with the patient left waiting on this one.
    { combo: "F1", label: "Mix", group: "Capture",
      run: () => setMixing(true) },
    { combo: "F2", label: "Find patient", group: "Capture",
      run: () => document.querySelector<HTMLInputElement>("[data-hk='patient']")?.focus() },
    { combo: "F3", label: "Add medicine", group: "Capture",
      run: () => document.querySelector<HTMLInputElement>("[data-hk='product']")?.focus() },
    // Opens the line being worked on with the cursor in its diagnosis. It used
    // to focus `[data-hk='dx']`, which nothing on the page carried, so F4 did
    // nothing at all.
    { combo: "F4", label: "Diagnosis", group: "Capture",
      disabled: items.length === 0,
      run: () => {
        const at = openItem < items.length ? openItem : 0;
        setChecking(null); setFinishing(null); setEditing(at);
        window.setTimeout(() => document
          .querySelector<HTMLElement>("#ed-dx input, #ed-dx button")?.focus(), 60);
      } },
    // WayBill — who is driving this one, where to, and what the fee is. It is a
    // section of this script rather than another screen, so the key opens it
    // and puts the cursor in it.
    { combo: "F5", label: "WayBill", group: "Capture",
      disabled: items.length === 0,
      run: () => {
        // The waybill section is what appears when this script is going out
        // with a driver, so the key sets that rather than revealing a panel
        // whose condition is somewhere else.
        setPayHow("delivery");
        openFinish("finish-pay");
      } },
    // Auth — the scheme's authorisation number, without which the claim is
    // raised and refused.
    { combo: "F6", label: "Auth", group: "Safety",
      run: () => navigate("/authorisations") },
    { combo: "F8", label: "Repts", group: "Lists",
      run: () => setWorklistPanel("due") },
    { combo: "F9", label: "Hist", group: "Lists",
      run: () => navigate("/dispensing-history") },
    // Finish opens the dialog; pressed again inside it, it dispenses. Two presses
    // of one key for the common case, and between them is where how it is paid
    // and who checked it are settled.
    { combo: "F12", label: "Finish", group: "Finish",
      disabled: busy || !patient || items.length === 0,
      run: () => {
        if (busy || !patient || !items.length) return;
        if (finishing === null) { openFinish(); return; }
        if (finishStage === "settle" && needsSettling()) { proceedToPay(); return; }
        if (complianceReadyRef() && !blockedBecause()) createAndDispense();
      } },
    // Closes the dialog that is open before it touches the script. Escape is what
    // everybody presses to close a dialog, and bound only to "clear" it would
    // empty the script behind the dialog being closed.
    { combo: "Escape", label: "Close, or clear the script", group: "Finish",
      disabled: items.length === 0 && finishing === null && editing === null
        && checking === null && laneOpen === null && !holding && !cancelTarget,
      run: () => {
        if (cancelTarget) return setCancelTarget(null);
        if (holding) return setHolding(false);
        if (laneOpen !== null) return setLaneOpen(null);
        if (finishing !== null) return setFinishing(null);
        if (checking !== null) return setChecking(null);
        if (editing !== null) return setEditing(null);
        if (newPatient || altering || showKeys) return;
        setItems([]);
      } },
    { combo: "?", label: "Show this key map", group: "Finish", run: () => setShowKeys(true) },
  ];
  useHotkeys(hotkeys);

  const complianceReady =
    (!needsInitials || initials.trim() !== "") &&
    (!needsCompliance || (items.length > 0 && complianceDone)) &&
    !counsellingMissing && !hold && !scanMissing &&
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
    // First, because nothing below it matters until it is released.
    if (hold) {
      return `On hold: ${hold.reason.toLowerCase()}`
        + (hold.placed_by ? `, placed by ${hold.placed_by}` : "")
        + ". A pharmacist or a manager releases it.";
    }
    if (items.length === 0) return "Add a medicine.";
    // Asked only where there is a script. A counter sale has no prescriber and
    // needs no patient on file: somebody buying a cough syrup is not
    // registered first, and demanding it was what made the counter its own
    // separate lane in the first place.
    if (needsScript) {
      if (!patient) return "Find the patient first.";
      // The server refuses without one and this never said so: the button went
      // grey with no sentence beside it.
      if (doctorId === "") return "Choose the prescriber.";
    }
    if (needsCompliance && !complianceDone)
      return `Complete the compliance record for ${activePolicy?.label ?? "this controlled substance"}.`;
    if (blocked) return "Acknowledge the blocking warning first.";
    // Before the initials: the packs are picked and scanned, then checked and
    // signed for. Named after them, the count of unscanned packs stayed hidden
    // behind a request for initials until somebody had already signed.
    if (scanMissing)
      return `Scan each pack against the script: ${unscannedLines} not yet scanned.`;
    if (needsInitials && !initials.trim())
      return "Enter the checking pharmacist's initials.";
    if (counsellingMissing)
      return "Record what the patient was told. Tick the points covered.";
    if (ixMajor > 0 && !ixAcknowledged)
      return "A dose is over the maximum and has to be acknowledged.";
    if (payHow === "aid") {
      if (aidScheme === "") return "Choose the medical aid scheme on the card.";
      if (!aidMember.trim()) return "Enter the member number from the card.";
      if (aidHold && aidHoldReason.trim().length < 3) return "Say why the claim is being held.";
      const world = currencyWorld(currencyState);
      const took = tenders.reduce((n, t) => n + inBase(t, world.rates, world.base), 0);
      if (dueNow > 0.005 && took + 0.005 < dueNow)
        return `Take the patient's ${money(dueNow)}: ${money(took)} entered so far.`;
    }
    return "";
  };

  /** The card holding whatever `blockedBecause` just named.
   *
   *  Naming the missing thing beside the button that will not go was half the
   *  fix. The other half is that on a screen this long the field being named is
   *  usually off the top of it, so the sentence sends somebody scrolling to
   *  look for a tickbox they have to find by eye. Same order of conditions, so
   *  the two can never point at different things.
   */
  const blockedAt = (): string => {
    if (!patient) return "step-patient";
    if (items.length === 0) return "step-items";
    if (needsCompliance && !complianceDone)
      return "step-compliance";
    if (needsInitials && !initials.trim())
      return needsCompliance ? "step-compliance" : "step-dispense";
    return "step-dispense";
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
      // treats one condition, so re-typing it on every item is wasted
      // keystrokes. The first line starts on the unspecified-contact code
      // rather than empty.
      icd10_code: items.length
        ? items[items.length - 1].icd10_code : DEFAULT_DIAGNOSIS,
    }]);
    setOpenItem(items.length);   // the line just added is the one being worked on
    setEditing(items.length);    // and it opens, because it has no directions yet
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
    setLastRxId(rxId);
    try {
      // A label that cannot name its batch and expiry does not print, on any
      // route — and the dispenser is told which box is still without one.
      const { printable: labels, refused } = splitPrintable(
        await api.get<Label[]>(`/api/prescriptions/${rxId}/labels`));
      if (refused.length) toast.warn(refusedSummary(refused));
      if (labels.length === 0) return;
      if (roll.labelsGoStraightToRoll()) {
        try {
          // However this till is set up: a PDF through the printer's own
          // driver, which works on anything Windows can see, or ESC/POS bytes
          // where the pharmacy has said it has a receipt-style roll. The
          // choice is `shellPrinter`'s, so no screen has its own opinion.
          await roll.printLabelsDirect(labels);
          toast.ok(`${labels.length} label(s) printed.`);
          return;
        } catch (e) {
          // The medicine is already in the bag. A roll that will not take the
          // job must not cost the label, so the dialog is the fallback rather
          // than the error being the end of it.
          toast.error(errorText(e, "The label printer did not take it. Using the print dialog."));
        }
      }
      printLabels(labels);
    } catch (e: any) { toast.error(errorText(e)); }
  }


  /** One roll label, on whichever printer that kind is routed to.
   *
   *  Shared by the price and delivery labels because the only thing that
   *  differs between them is the lines and the destination — and a second copy
   *  of the fallback logic is a second place for it to be wrong.
   */
  async function printRoll(kind: "price" | "delivery", lines: Line[]) {
    if (!roll.goesStraightToPrinter(kind)) {
      toast.warn("No printer is set for this on this till. This till > Printers.");
      return;
    }
    setPrinting(true);
    try {
      await roll.printLines(lines, 1, kind);
      toast.ok("Printed.");
    } catch (e) {
      toast.error(errorText(e, "The printer did not take it."));
    } finally { setPrinting(false); }
  }

  /** What the basket on screen would cost, before anything is dispensed.
   *
   *  Deliberately reads the lines being built rather than a dispensed script:
   *  the person asking is deciding whether to go ahead, which is a question
   *  asked BEFORE the medicine leaves the shelf, not after. */
  async function printPriceQuote() {
    const width = roll.printerWidth();
    const lines: Line[] = [];
    for (const it of items) {
      const each = lineEach(it);
      lines.push(...priceLabelLines({
        product_name: it.product.name,
        strength: it.product.strength ?? "",
        pack_size: it.product.pack_size ?? "",
        quantity: it.quantity,
        unit_price: each,
        line_total: each * it.quantity,
      }, width));
    }
    if (!lines.length) { toast.warn("Nothing on the script to price."); return; }
    await printRoll("price", lines);
  }

  async function printDeliveryLabel(rxNumber?: string) {
    if (!patient) { toast.warn("No patient on this script."); return; }
    await printRoll("delivery", deliveryLabelLines({
      patient_name: `${patient.first_name} ${patient.last_name}`.trim(),
      address: patient.address ?? "",
      phone: patient.phone ?? "",
      rx_number: rxNumber || fromRx?.number || "(not yet dispensed)",
      items: items.length,
    }, roll.printerWidth()));
  }

  /** The claim copy, on paper.
   *
   *  A page rather than a roll, so it takes the other path entirely: the server
   *  renders a PDF and the shell hands the FILE to the printer's driver. Sent
   *  as RAW bytes the way a label is, a laser prints the PDF source as text or
   *  ejects blank pages until somebody switches it off.
   */
  async function printClaimCopy(rxId?: number) {
    // Given the script just dispensed: `lastRxId` is state, and in the same
    // pass as the dispense it still holds the previous script's id.
    const id = rxId ?? lastRxId;
    if (!id) { toast.warn("Dispense the script first."); return; }
    setPrinting(true);
    try {
      const file = await api.blob(`/api/prescriptions/${id}/claim-copy.pdf`);
      const bytes = new Uint8Array(await file.body.arrayBuffer());
      if (roll.goesStraightToPrinter("claim")) {
        await roll.printPage(bytes, "claim");
        toast.ok("Claim copy printed.");
      } else {
        // No printer chosen for pages, or a browser tab. Opened instead, which
        // is one keystroke from the operating system's own print dialogue.
        const url = URL.createObjectURL(file.body);
        window.open(url, "_blank", "noopener");
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (e) {
      toast.error(errorText(e, "The claim copy could not be produced."));
    } finally { setPrinting(false); }
  }

  /** The menu beside Dispense. Letters are the previous system's own. */
  const printActions: PrintAction[] = [
    { key: "l", label: "Re-print dispensing label",
      hint: "The stickers for the box, again.",
      unavailable: lastRxId ? undefined : "Nothing dispensed on this screen yet",
      run: () => { if (lastRxId) void printRxLabels(lastRxId); } },
    { key: "c", label: "Claim copy (A4)",
      hint: "For the file, or for the funder.",
      unavailable: lastRxId ? undefined : "Nothing dispensed on this screen yet",
      run: () => printClaimCopy() },
    { key: "p", label: "Price label",
      hint: "A quote for somebody deciding. Prints from the script on screen.",
      unavailable: items.length ? undefined : "Nothing on the script to price",
      run: printPriceQuote },
    { key: "v", label: "Delivery label",
      hint: "Name, address and script number, for the driver.",
      unavailable: patient ? undefined : "No patient on this script",
      run: () => printDeliveryLabel(), separated: true },
  ];

  function compliancePayload() {
    // The initial is sent whenever there is one, on every route.
    //
    // It used to belong to the controlled-substance block and nothing else, so
    // on an ordinary prescription a pharmacist could type their initials into a
    // field that existed and still have the dispensing refused for not having
    // them: the value was collected and then dropped. Three places held an
    // opinion about when an initial is needed: this function, the field's
    // visibility, and a server setting. Only the server's counted.
    const initial = initials.trim();
    return {
      ...(initial ? { pharmacist_initial: initial } : {}),
      // Sent on every dispensing: recorded whenever it was given, whether or
      // not this pharmacy requires it.
      counselling_points: counselPoints,
      counselling_notes: counselNotes.trim(),
      // Sent when the *lines* call for it. Keyed to the route tab, a Schedule 5
      // line captured on the Prescription tab had these dropped here and was
      // refused by the server for missing exactly what this screen had chosen
      // not to send.
      ...(needsCompliance
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
   *  directions, diagnosis and repeats already captured, so pressing Dispense
   *  satisfies that script rather than writing a new one beside it.
   */
  /** Arriving from another screen with a script to work on.
   *
   *  The repeats book can supply a line in one press, which is right for the
   *  common case and cannot express the others: a fortnight instead of a
   *  month, something added, a dose the prescriber has changed. Those need the
   *  capture screen, and the only route to it was to abandon the repeat and
   *  start the script again from the patient.
   *
   *  `?rx=` loads it here instead, using the same function the worklist uses,
   *  so a script opened from a repeat behaves exactly like one opened from the
   *  queue. The parameter is cleared once it has been read, or a refresh
   *  reloads a script the pharmacist has since changed on screen.
   */
  /** Arriving with a patient, to write them a new script.
   *
   *  "New Script" on a patient's record was a bare link to /dispense. It
   *  opened an empty dispensary — the patient whose record you were reading
   *  did not travel, so the first thing you did was search for them by name,
   *  having just been looking at them. The record has to go with the link or
   *  it is not a handover, it is a menu item.
   */
  const openedPatient = useRef(0);
  useEffect(() => {
    const patientId = Number(params.get("patient"));
    if (!Number.isFinite(patientId) || patientId <= 0
        || openedPatient.current === patientId) return;
    openedPatient.current = patientId;

    api.get<Patient>(`/api/patients/${patientId}`)
      .then((p) => {
        setPatient(p);
        setPatientQ("");
        setPatients([]);
      })
      .catch(() => toast.error("That patient could not be opened."))
      .finally(() => {
        const next = new URLSearchParams(params);
        next.delete("patient");
        setParams(next, { replace: true });
      });
  }, [params]);

  const openedRx = useRef(0);
  useEffect(() => {
    const rxId = Number(params.get("rx"));
    if (!Number.isFinite(rxId) || rxId <= 0 || openedRx.current === rxId) return;
    openedRx.current = rxId;

    (async () => {
      try {
        const rx = await api.get<any>(`/api/prescriptions/${rxId}`);
        await openQueued({
          patient_id: rx.patient_id,
          prescription_id: rx.id,
          schedule: Math.max(0, ...(rx.items ?? [])
            .map((i: any) => i.product?.schedule ?? 0)),
        });
      } catch (e) {
        toast.error(errorText(e, "That script could not be opened."));
      } finally {
        const next = new URLSearchParams(params);
        next.delete("rx");
        next.delete("item");
        setParams(next, { replace: true });
      }
    })();
  }, [params]);

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
          icd10_code: i.icd10_code || DEFAULT_DIAGNOSIS,
          item_id: i.id,
        }));
      if (!ready.length) {
        toast.warn("Nothing is outstanding on that script.");
        return;
      }
      setItems(ready);
      // Whether it is a draft governs what can be done with it. A draft has
      // no Rx number and the server refuses to dispense one, so if this is not
      // carried, opening a draft leads to a button that cannot work.
      setFromRx({ id: rx.id, date: (rx as any).date_prescribed, number: rx.rx_number || rx.draft_ref || `#${rx.id}`,
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
        toast.ok(`${r.product} added: ${money(r.value)} of theirs that was waiting.`);
      })
      .catch(() => toast.error("That repeat could not be added to the script."));
  }

  /** Take the server's item ids onto the lines on screen.
   *
   *  Saving a draft replaces its items wholesale, so they come back with new
   *  ids every time. Anything on this screen still holding the old ones is
   *  holding rows that no longer exist.
   */
  function adoptIds(rx: any) {
    const byProduct = new Map<number, number>(
      (rx?.items ?? []).map((i: any) => [i.product_id, i.id]));
    setItems((rows) => rows.map((r) => ({
      ...r, item_id: byProduct.get(r.product.id) ?? r.item_id,
    })));
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
        price_override_id: i.priceOverrideId ?? null,
        claim_override_id: i.claimOverrideId ?? null,
      })),
    };
  }

  /** Put a half-captured script down and come back to it.
   *
   *  A pharmacist gets interrupted — the telephone, a query at the till, a
   *  delivery, and until now the only ways out of a part-typed script were to
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
        // The worklist is the thing the message points at, so it has to have
        // moved by the time somebody looks. It reloaded on a dispensing and on
        // nothing else, so a draft saved a second ago was not on the tab that
        // counts drafts, and the toast read as a promise the screen had not
        // kept.
        setWorklistNonce((n) => n + 1);
      } else {
        const rx = await api.post<any>("/api/prescriptions",
                                       { ...scriptPayload(), draft: true });
        setFromRx({ id: rx.id, date: (rx as any).date_prescribed, number: rx.rx_number || rx.draft_ref || `#${rx.id}`,
                    draft: true });
        adoptIds(rx);
        toast.ok(`Saved for later. It is on the worklist as a ${DRAFT_SCRIPT.toLowerCase()}.`);
        setWorklistNonce((n) => n + 1);
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
      setFromRx({ id: rx.id, date: (rx as any).date_prescribed, number: rx.rx_number || `#${rx.id}`, draft: false });
      adoptIds(rx);
      toast.ok(`${rx.rx_number} finished. It can be dispensed now.`);
      // It has just stopped being a draft, so the drafts tab is now wrong by
      // one in the other direction.
      setWorklistNonce((n) => n + 1);
    } catch (e) {
      // The server refuses a script with no prescriber, no items, or a
      // prohibited schedule, and names which. Shown as written.
      toast.error(errorText(e, "That draft could not be finished."));
    } finally {
      setBusy(false);
    }
  }

  /** Dispense, and let the counter get on with the next patient.
   *
   *  Everything below this point is bookkeeping the dispenser has already
   *  decided: the packs are picked, the initials are in, the money is settled
   *  or on its way to the till. Standing in front of a spinner while a hosted
   *  database in another city writes eleven rows is time taken from the person
   *  next in the queue.
   *
   *  So the screen clears on the keystroke and the work goes to the tray, where
   *  it is visible, named, and answered — in a toast and on the chip — whichever
   *  way it lands. A refusal puts the whole script back exactly as it was,
   *  including the packs scanned and the expiry dates read off them, and offers
   *  Try again rather than retrying anything by itself.
   */
  /** Sell the basket over the counter, as one sale and one consultation.
   *
   *  The counter used to be a separate lane holding one medicine, so a
   *  customer buying paracetamol and a cough syrup was two sales seconds
   *  apart: two rows in the register reading as two consultations, and two
   *  transactions in the cash-up. It is one basket now, and the server takes
   *  it as one.
   *
   *  Every line is checked against the jurisdiction pack before anything
   *  moves, so a basket that should never have reached here is refused whole
   *  rather than half sold.
   */
  async function sellOverTheCounter() {
    const lines = items.map((i) => ({
      product_id: i.product.id,
      quantity: i.quantity || 0,
      ...(packExpiry[i.product.id]
        ? { pack_expiry: packExpiry[i.product.id] } : {}),
    }));
    const world = currencyWorld(currencyState);
    const took = tenders.reduce((n, t) => n + inBase(t, world.rates, world.base), 0);
    const gross = items.reduce((n, i) => n + lineEach(i) * (i.quantity || 0), 0);
    const said = items.length === 1
      ? lineName(items[0].product)
      : `${items.length} items`;
    try {
      const out = await api.post<{ sale_id: number; total: number;
                                   change_due: number }>(
        "/api/dispensing/otc", {
          lines,
          patient_id: patient?.id ?? null,
          customer_name: customerName,
          indication,
          counselling_given: counselled,
          referred_to_doctor: referred,
          notes: otcNotes,
          payment_method: "cash",
          // The server refuses a cash sale tendered short. Where the finish
          // panel collected nothing the sale is settled exactly, which is what
          // a counter sale at the marked price is.
          amount_tendered: took > 0.005 ? took : Math.round(gross * 100) / 100,
        });
      toast.ok(`${said} sold and recorded.`
        + (out.change_due > 0.005 ? ` Change ${money(out.change_due)}.` : ""));
      // The counter is given back, and the consultation with it.
      setItems([]); aiCheck.reset();
      setIndication(""); setCustomerName(""); setCounselled(false);
      setReferred(false); setOtcNotes(""); setTenders([]);
      clearScriptDraft();
      loadLists();
      if (out.sale_id) {
        try {
          const sale = await api.get<Sale>(`/api/pos/sales/${out.sale_id}`);
          printReceipt(sale, pharmacy.name, pharmacy.regNo);
        } catch {
          // A receipt that will not print is not a sale that did not happen.
        }
      }
    } catch (e) {
      toast.error(errorText(e, "That sale could not be recorded."));
    }
  }

  function createAndDispense() {
    if (items.length === 0) {
      toast.error("Add a medicine first.");
      return;
    }
    // THE SCREEN PICKS THE PATH, NOT THE DISPENSER.
    //
    // A basket with nothing in it that needs a prescription is a counter sale,
    // and a counter sale is a different transaction: no script record, no
    // prescriber, its own endpoint, and a row in the pharmacy-medicine
    // register rather than a dispensing. That used to be chosen by which tab
    // somebody had clicked before they looked anything up.
    if (!needsScript) {
      sellOverTheCounter();
      return;
    }
    if (!patient || doctorId === "") {
      toast.error("Select a patient and a prescriber.");
      return;
    }

    // What the screen would have to become again, if this does not happen.
    const before = {
      patient, doctorId, items, fromRx, initials, idNumber, complianceNotes,
      idVerified, scriptSighted, prescriberVerified, counselPoints, counselNotes,
      scanChecks, packExpiry, payHow, tenders, driverId, deliverTo, deliveryFee,
      printPick, aidScheme, aidMember, aidDep, aidHold, aidHoldReason,
    };
    const said = `${fromRx?.number ?? "This script"} for ${patient.first_name} ${patient.last_name}`;

    // Cleared here, once, rather than on the way out of the request: by the time
    // the server answers, the dispenser may be three lines into the next script
    // and clearing then would take it off them.
    setFinishing(null);
    clearScriptDraft();
    refreshNextNumber();
    setItems([]); aiCheck.reset(); setFromRx(null);
    setIdVerified(false); setScriptSighted(false); setPrescriberVerified(false);
    setInitials(myInitials); setIdNumber(""); setComplianceNotes("");
    setCounselPoints([]); setCounselNotes(""); setScanChecks({}); setPackExpiry({});
    setPrintPick({});
    setTenders([{ method: "cash", currency_code: currencyState?.base ?? "USD", amount: "" }]);
    loadLists();
    setWorklistNonce((n) => n + 1);

    // A script created by a first attempt is dispensed by the second, never
    // created twice: three tries at a line with no dated stock used to make
    // three identical scripts and spend three numbers.
    let already: { id: number; rx: any } | null = fromRx ? { id: fromRx.id, rx: null } : null;

    doing.run({
      label: `Dispensing ${said}`,
      said: `${said}. Dispensed.`,
      run: () => dispenseTheScript(before, already, (made) => { already = made; }),
      // Where it goes next is the answer to "how it is paid", which was decided
      // in Finish a moment ago:
      //
      //   to the till       the sale is waiting there for the patient's share
      //   out for delivery  it is on a driver's run, and that is the screen
      //   taken here        the money is already in; there is nowhere to go
      //
      // Offered rather than taken. By the time this lands the dispenser may be
      // half way through the next patient, and moving their screen then is the
      // very thing that made them wait for a spinner in the first place.
      next: (sale: any) => {
        if (before.payHow === "till" && sale?.id) {
          // Offered, because the answer is about the shop rather than the
          // software: with a cashier at the front, the sale is already on their
          // pending list and this dispenser should stay where they are. Working
          // alone, this is how they finish it — and the sale then records that
          // they took the money, so nobody at the till answers for a drawer
          // they never touched.
          return { label: "Nobody at the till? Take it yourself →",
                   go: () => navigate(`/pos?settle=${sale.id}&tab=pending`) };
        }
        if (before.payHow === "delivery") {
          return { label: "Deliveries →", go: () => navigate("/deliveries") };
        }
        return null;
      },
      undo: () => {
        // Back exactly as it was, down to the packs already scanned.
        setPatient(before.patient); setDoctorId(before.doctorId); setItems(before.items);
        setFromRx(already ? { id: already.id, number: already.rx?.rx_number ?? before.fromRx?.number ?? `#${already.id}`,
                              draft: false } : before.fromRx);
        setInitials(before.initials); setIdNumber(before.idNumber);
        setComplianceNotes(before.complianceNotes); setIdVerified(before.idVerified);
        setScriptSighted(before.scriptSighted); setPrescriberVerified(before.prescriberVerified);
        setCounselPoints(before.counselPoints); setCounselNotes(before.counselNotes);
        setScanChecks(before.scanChecks); setPackExpiry(before.packExpiry);
        payHowSet.current = true;
        setPayHow(before.payHow); setTenders(before.tenders); setDriverId(before.driverId);
        setDeliverTo(before.deliverTo); setDeliveryFee(before.deliveryFee);
        setPrintPick(before.printPick); setAidScheme(before.aidScheme);
        setAidMember(before.aidMember); setAidDep(before.aidDep);
        setAidHold(before.aidHold); setAidHoldReason(before.aidHoldReason);
        setWorklistNonce((n) => n + 1);
      },
    });
  }

  /** The dispensing itself, run from the tray. */
  async function dispenseTheScript(
    before: any,
    already: { id: number; rx: any } | null,
    remember: (made: { id: number; rx: any }) => void,
  ) {
    const { patient, doctorId, items, scanChecks, packExpiry, payHow, tenders } = before as {
      patient: Patient; doctorId: number | ""; items: DraftItem[];
      scanChecks: Record<number, string>; packExpiry: Record<number, string>;
      payHow: string; tenders: TenderLine[];
    };
    {
      // A queued script is dispensed as itself. Capturing it again would leave
      // the original waiting in the queue for ever, which is exactly what used
      // to happen: the worklist never went down however many people you served.
      const rx = already
        ? await api.get<Prescription>(`/api/prescriptions/${already.id}`)
        : await api.post<Prescription>("/api/prescriptions", {
          patient_id: patient.id, doctor_id: doctorId,
          items: items.map((i) => ({
            product_id: i.product.id, quantity: i.quantity,
            dosage_instructions: i.dosage_instructions, repeats_allowed: i.repeats_allowed,
            repeat_interval_days: i.repeat_interval_days, auto_refill: i.auto_refill,
            icd10_code: i.icd10_code,
            price_override_id: i.priceOverrideId ?? null,
            claim_override_id: i.claimOverrideId ?? null,
          })),
        });
      // Which of the script's lines to dispense, resolved against the server's
      // OWN item ids rather than against ids this screen is holding.
      //
      // It used to send `i.item_id`, captured when the script was opened. Every
      // save of a draft replaces its items wholesale — the endpoint deletes and
      // re-adds them, so they come back with new ids — and finishing a draft
      // goes through that same save. So the moment somebody pressed "Save for
      // later" or "Finish capturing", every id on this screen was stale, the
      // `.filter(Boolean)` quietly dropped the lot, and the dispense posted an
      // empty list. The server answered "No valid items selected", which is
      // true and reads as though the dispenser had chosen nothing.
      //
      // Matching on the product is stable across all of that, and still honours
      // a line the dispenser took off the screen. Products are unique on a
      // script here: `addItem` refuses a second line for the same one.
      // The script exists from here on, whatever happens to the dispensing.
      //
      // It was created and then dispensed as two steps, and a refusal in the
      // second left the first behind: a saved, undispensed script, on the
      // worklist, with a number taken. Pressing Dispense again created another.
      // Three tries at a line with no dated stock made three identical scripts
      // for one patient and spent three numbers. The screen now takes the saved
      // script as its own, so a retry dispenses that one, and the worklist
      // shows the one script that is genuinely still waiting.
      if (!already) {
        // Remembered, so a Try again dispenses this script rather than making
        // another one for the same patient.
        remember({ id: rx.id, rx });
      }
      const onScreen = new Set(items.map((i) => i.product.id));
      const selected = (rx.items ?? [])
        .filter((i: any) => onScreen.has(i.product_id))
        .map((i: any) => i.id);
      if (!selected.length) {
        throw new Error("None of the lines on screen are on that script any more. "
                        + "Reopen it and try again.");
      }
      // THROUGH `guarded`, BECAUSE A LOT TAKEN OUT OF TURN NEEDS A SUPERVISOR.
      //
      // The server answers 428 to ask for one, and this is the call that
      // carries the chosen lots. Without this the dispensing would fail with
      // a raw error at the Finish button — the point at which somebody has
      // done all the work and a patient is waiting.
      //
      // An ordinary dispensing never sees the dialog: with no lot named, or
      // one naming the lot the rotation would have taken anyway, the server
      // does not ask.
      const dispensed = await guarded<Sale>(
        "stock.batch_override",
        (token) => api.post<Sale>(`/api/prescriptions/${rx.id}/dispense`, {
        item_ids: selected,
        receipt_private: receiptPrivate,
        // The code scanned for each line, keyed by the script's own item ids,
        // which only exist once the script has been written.
        scanned_codes: Object.fromEntries(
          (rx.items ?? [])
            .filter((i: any) => onScreen.has(i.product_id) && scanChecks[i.product_id])
            .map((i: any) => [i.id, scanChecks[i.product_id]])),
        // The date read off each pack whose stock had none recorded.
        pack_expiries: Object.fromEntries(
          expiryNeeded.filter((l) => packExpiry[l.product_id])
            .map((l) => [l.product_id, packExpiry[l.product_id]])),
        // A lot taken ahead of the rotation, per line. Only lines where
        // somebody actually chose one: naming the lot the rotation would have
        // taken anyway is not an override and the server says so by not
        // asking for a password.
        batch_choice: Object.fromEntries(
          Object.entries(scriptLots)
            .filter(([, choice]) => choice.batch_id)
            .map(([itemId, choice]) => [Number(itemId), choice.batch_id])),
        batch_reason: Object.values(scriptLots).find((c) => c.batch_id)?.reason ?? "",
        batch_note: Object.values(scriptLots).find((c) => c.batch_id)?.note ?? "",
        ...compliancePayload(),
        // The warnings acknowledged at the counter, recorded against this
        // script by the server as it is dispensed.
        acknowledged_message_ids: [...counter.acked],
        // Paid by medical aid: the card, and whether the claim goes now.
        ...(payHow === "aid" && aidScheme !== "" ? {
          claim: {
            medical_aid_id: aidScheme, member_number: aidMember.trim(),
            dependent_code: aidDep.trim() || "00",
            hold: aidHold, hold_reason: aidHold ? aidHoldReason.trim() : "",
          },
        } : {}),
      }, token),
        `${rx.rx_number ?? "this script"} · lot taken out of turn`);
      if (dispensed === CANCELLED) {
        // A decision, not a failure. Nothing has left the shelf and the
        // script is untouched, so there is nothing to undo.
        toast.warn("Nothing was dispensed. That lot needs a supervisor.");
        return;
      }
      const sale = dispensed;
      // Take the money here when that is what was asked for. The sale is
      // raised pending either way; settling it is the same call the till makes,
      // so there is one payment path in the system rather than two that can
      // disagree about what a scheme has already covered.
      let finished = sale;
      if (payHow === "now" || payHow === "aid") {
        try {
          const due = patientPortion(sale);
          const lines = tenders.filter((t) => Number(t.amount) > 0);
          // The scheme's share, as adjudicated, settles as a medical aid tender
          // exactly as the till does it. Without it the sale was asked for its
          // gross against the patient's share alone and refused as short, so
          // "Take payment now" never settled a scheme member's script.
          const covered = Math.round((sale.total - due) * 100) / 100;
          finished = await api.post<Sale>(`/api/pos/sales/${sale.id}/pay`, {
            payment_method: "split",
            // Each piece kept separate, with what it needs to be matched to a
            // statement later: the wallet and number, or the bank and last four.
            tenders: [
              ...(covered > 0.005 ? [{ method: "medical_aid",
                currency_code: currencyState?.base ?? "USD", amount: covered, reference: "" }] : []),
              ...lines.map((t) => ({
              method: t.method,
              currency_code: t.currency_code || (currencyState?.base ?? "USD"),
              amount: Number(t.amount),
              reference: [t.wallet, t.phone, t.scheme, t.last4 && `••${t.last4}`, t.auth]
                .filter(Boolean).join(" "),
            })),
            ],
          });
          // What was actually collected, against what the scheme actually
          // allowed. `due` is the server's figure after adjudication, and the
          // tenders were typed against the estimate shown while the script was
          // being built. Those agree almost always, and when they do not, it
          // is because the scheme allowed less than its terms suggested, which
          // is precisely the case somebody has to be told about rather than
          // congratulated on. Saying "settled" over a sale that is short is how
          // a patient walks out owing money nobody mentioned.
          const took = lines.reduce((n, t) => n + Number(t.amount || 0), 0);
          const short = Math.round((due - took) * 100) / 100;
          toast.ok(
            short > 0.005
              // "The scheme" starts a sentence here, so it is capitalised.
              // Interpolating the fallback in lower case produced "still
              // owed. the scheme allowed less…" on every patient without a
              // named aid, which is most walk-ins.
              ? `${money(took)} taken, ${money(short)} still owed. `
                + `${patient?.medical_aid?.name ?? "The scheme"} allowed less `
                + `than its terms suggested. It is on the till as `
                + `${sale.sale_number}.`
              : due < sale.total - 0.005
                ? `${money(due)} taken from the patient, `
                  + `${money(sale.total - due)} on the scheme.`
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
      // Out for delivery: raise the waybill and put it on the driver's
      // account. Done after the sale exists, because the waybill has to carry
      // its number and the amount to collect at the door.
      if (payHow === "delivery" && driverId !== "") {
        try {
          const fee = Number(deliveryFee) || 0;
          const wb = await api.post<{ id: number; waybill_number: string }>(
            "/api/waybills", {
              sale_id: sale.id,
              patient_id: patient?.id ?? null,
              address: deliverTo,
              delivery_fee: fee,
              driver_profile_id: driverId,
              // What the driver is to collect. The patient's share plus the
              // fee — never the gross, which would be asking the member for
              // the scheme's money at their own front door.
              cod_amount: Math.round((patientPortion(sale) + fee) * 100) / 100,
            });
          await api.post(`/api/waybills/${wb.id}/dispatch`,
                         { driver_id: driverId });
          const who = drivers.find((d) => d.id === driverId)?.full_name ?? "the driver";
          toast.ok(`${wb.waybill_number} is out with ${who}, collecting `
                   + `${money(patientPortion(sale) + fee)} at the door. `
                   + `It is on their account until they hand it in.`);
        } catch (err) {
          // The medicine has gone out and the sale exists. A waybill that
          // could not be raised is a delivery that has to be arranged by hand,
          // which is worth saying plainly rather than failing the dispense.
          toast.error(errorText(err,
            "Dispensed, but the delivery note could not be raised. Raise it "
            + "from Deliveries before the driver leaves."));
        }
      }

      // The screen was cleared when the button was pressed. What is left is
      // the outcome — and it is only put on the bar if the dispenser has not
      // already started the next script, because taking their screen over to
      // report on the last one is the thing this change exists to stop.
      if (!itemsRef.current.length && !patientRef.current) {
        setDoneSale(finished); setDoneRxId(rx.id);
      }
      loadLists();
      // The queue is why anybody is on this screen. It refreshed itself every
      // two minutes and not on dispensing, so the count sat unchanged after the
      // very act that should have moved it, which reads as the dispensing not
      // having registered at all.
      setWorklistNonce((n) => n + 1);
      // Labels first, then the screen moves. Printing is fire-and-forget — the
      // browser dialog or the roll takes it from here, so it must be started
      // before navigating away rather than left to a component that is about
      // to unmount.
      // What Finish said would print, printed — one after another, so two
      // labels bound for the same roll cannot interleave. Labels first: they go
      // on the box being handed over. The price label reads the lines from this
      // pass, before the cleared script reaches the screen.
      const prints = { label: !!before.printPick.label || printDefault("label"),
                       receipt: before.printPick.receipt ?? printDefault("receipt"),
                       claim: before.printPick.claim ?? printDefault("claim"),
                       delivery: before.printPick.delivery ?? printDefault("delivery"),
                       price: before.printPick.price ?? printDefault("price"),
                       barcode: before.printPick.barcode ?? printDefault("barcode") };
      const rxNumber = (rx as any).rx_number as string | undefined;
      void (async () => {
        if (prints.label) await printRxLabels(rx.id);
        // The receipt for money taken here, off the sale the dispensing raised.
        if (prints.receipt && sale) {
          try {
            // The till's own receipt printer where one is set, exactly as the
            // POS does it, so a receipt raised at the dispensary and one taken
            // at the counter come off the same roll.
            if (roll.goesStraightToPrinter("receipt")) {
              await roll.printReceiptDirect(sale, pharmacy.name, pharmacy.regNo);
            } else {
              printReceipt(sale, pharmacy.name, pharmacy.regNo);
            }
          } catch { /* a receipt that will not print must not undo a dispensing */ }
        }
        // The script's barcode, on its own sticker. Never fatal: the medicine
        // has gone out, and a barcode that would not print is reprinted from
        // the script rather than being a reason the dispensing failed.
        if (prints.barcode && rxNumber) {
          try {
            await roll.printBarcodeDirect(rxNumber, rxNumber);
          } catch (e) {
            toast.warn(errorText(e, "The script barcode did not print."));
          }
        }
        if (prints.delivery) await printDeliveryLabel(rxNumber);
        if (prints.price) await printPriceQuote();
        if (prints.claim) await printClaimCopy(rx.id);
      })();
      setPrintPick({});
      // "Send to till" is an instruction, so the screen follows it. It used to
      // raise the invoice and stay put with a banner, leaving the dispenser to
      // find the front shop and search for the sale they had just made — two
      // screens for one act, and the commonest way a pending sale is forgotten.
      // Where one person does both jobs, the till is where they were going
      // anyway — but only if this screen is still free. Somebody who has
      // started the next patient is not asking to be taken anywhere.
      if (goToTillRef.current && before.payHow === "till" && finished?.id
          && !itemsRef.current.length && !patientRef.current) {
        navigate(`/pos?settle=${finished.id}&tab=pending`);
      }
      setWorklistNonce((n) => n + 1);
      return finished;
    }
  }

  /** Sell it, and give the counter back before the server has answered.
   *
   *  This held the screen on `busy` while a hosted database wrote a sale, its
   *  line, its stock movement and its register entry — the same wait the till
   *  was rebuilt to stop paying. A front shop is a queue like any other: the
   *  counter clears on the click, the work is named while it runs, and a
   *  refusal hands everything back exactly as it was, because the one thing
   *  worse than a slow sale is a sale that loses what somebody just typed.
   */

  /** What each line on the script makes, priced as the totals bar prices it.
   *
   *  Read here rather than inside each row so the basket is priced once. The
   *  figure is per line and it is on the line, because a discount is granted
   *  against one medicine and the margin that decides it used to be two
   *  scrolls down behind a toggle.
   */
  //
  //  `no_claim` used to be passed here as `(i as any).no_claim`. `DraftItem`
  //  has no such field and nothing on this screen sets one, so it was always
  //  undefined — a cast that stopped the compiler asking and hid the fact that
  //  the flag does not exist. Dropped rather than left looking supported.
  const pricedItems = items.map((i) => ({
    product_id: i.product.id, quantity: i.quantity,
    // A price set by hand goes into the sums, so the footer under the table
    // adds up the figures the rows are showing. It is sent for arithmetic only
    // — what the patient is actually charged comes off the authorised record.
    ...(i.price !== undefined ? { unit_price: i.price } : {}),
    // Sent for arithmetic only. What the funder is actually asked for comes off
    // the authorised record, never off this.
    ...(i.claim !== undefined ? { claim: i.claim } : {}),
  }));
  const pricing = useScriptPricing(pricedItems, patient?.medical_aid_id ?? null);

  /** Which funder this script will be claimed against, if any.
   *
   *  The scheme chosen on the Finish dialog wins over the one on the patient's
   *  record, because the card in the dispenser's hand is the current fact and
   *  the record may be a year old. Null on a cash script — and on a cash script
   *  nothing about NAPPI codes appears anywhere on this screen.
   */
  const claimingAgainst = (payHow === "aid" && aidScheme !== "")
    ? Number(aidScheme)
    : (patient?.medical_aid_id ?? null);
  const schemeName = schemes.find((m) => m.id === claimingAgainst)?.name || "the scheme";
  const { codes: schemeCodes, reload: reloadSchemeCodes } =
    useSchemeCodes(claimingAgainst, items.map((i) => i.product.id));
  const marginFor = (productId: number) =>
    pricing?.lines.find((l) => l.product_id === productId);

  /** What the scheme will carry and what the patient will owe.
   *
   *  Asked of the server, from the same rule the adjudication uses, so the
   *  figure quoted here is the figure the till collects. Two implementations
   *  of "what does the scheme cover" would disagree eventually, and the day
   *  they disagreed somebody would be asked for the wrong amount.
   *
   *  It is emphatically NOT `pricing.totals.patient_pays`, which was the
   *  obvious source and would have been a bad bug. That service models the
   *  scheme's *regulated* price — fee model, professional fee, levy, MMAP cap
   *  — while the sale a claim is raised against is billed at shelf price. Two
   *  coherent calculations of two different things; showing one as the other
   *  is arithmetic on mismatched data, wrong by a plausible-looking margin on
   *  every scheme line.
   */
  const [split, setSplit] = useState<{
    total: number; scheme_pays: number; patient_pays: number;
    covered: boolean; scheme?: string; why?: string;
  } | null>(null);

  // On the medical aid choice the estimate is made against the card, which may
  // not be on the patient's record yet.
  const aidCard = payHow === "aid" && aidScheme !== ""
    ? { medical_aid_id: aidScheme, member_number: aidMember } : {};
  /** Whether the bill should show the scheme carrying part of it. */
  const claimHeld = payHow === "aid" && aidHold;
  const schemeCarries = !!split?.covered && !claimHeld;
  const splitKey = JSON.stringify(pricedItems) + `|${patient?.id ?? ""}|${JSON.stringify(aidCard)}`;
  useEffect(() => {
    if (!items.length) { setSplit(null); return; }
    let live = true;
    api.post<typeof split>("/api/claim-estimate", {
      patient_id: patient?.id ?? null, items: pricedItems, ...aidCard,
    })
      .then((d) => { if (live) setSplit(d); })
      // A figure that cannot be worked out must not stop anybody dispensing.
      // The split simply does not appear and the till does what it always did.
      .catch(() => { if (live) setSplit(null); });
    return () => { live = false; };
  }, [splitKey]);

  // What the tender rows are settling: the SHORTFALL, not the gross.
  //
  //  This used to be the basket at shelf prices. Choosing "Take payment now"
  //  for a scheme member therefore put the gross in front of the dispenser as
  //  the amount owed. Collecting it takes the funder's money out of the
  //  member's pocket while the claim for that same money is raised half a
  //  second later — the patient pays twice and the pharmacy is paid twice,
  //  which is the worst thing a till can do to somebody unwell and queueing.
  useEffect(() => {
    const gross = items.reduce(
      (n, i) => n + lineEach(i) * (i.quantity || 0), 0);
    // A held claim has not been sent, so nothing is promised on the scheme's
    // behalf: the patient settles the whole of it, as the server records.
    setDueNow(payHow === "aid" && aidHold ? gross : split ? split.patient_pays : gross);
  }, [items, split, payHow, aidHold]);

  /** The same conditions again, as a trail across the top of the screen.
   *
   *  Read from the live state on every render rather than stored, so a card
   *  edited after its step went green turns amber again. A stored cursor is
   *  the thing that makes a wizard lie.
   *
   *  Derived from the same expressions the dispense button is disabled on —
   *  `complianceReady`, `needsInitials`, `blockedBecause` — because a progress
   *  display that can disagree with the button is worse than none: it tells
   *  somebody they are finished while the one control they want stays grey.
   */
  /* THE MEDICINE IS ALWAYS FIRST NOW.
   *
   *  There were two trails, chosen by the tab. The script one opened on
   *  "Patient & prescriber" and the counter one on "Medicine", which is the
   *  same disagreement the tabs had: the screen could not know which it was
   *  until it knew what was being supplied, and it was asking the dispenser to
   *  say so before they had looked anything up.
   *
   *  So the medicine comes first and the rest of the trail grows from it. A
   *  counter sale never grows a patient step; a script grows one the moment a
   *  line calls for it. */
  const steps: Step[] = [
    { n: 1, title: "Medicine", anchor: "step-items", tone: "items",
      done: items.length > 0,
      needs: "Search for what is being supplied." },
    ...(needsScript ? ([{
      n: 2, title: "Patient & prescriber", anchor: "step-patient", tone: "patient",
      done: !!patient && doctorId !== "",
      needs: !patient ? "Find the patient, or add them if they are new."
        : "Choose the prescribing doctor.",
    }] as Step[]) : []),
    // Typed as `Step[]` rather than inferred: inside a conditional spread
    // TypeScript widens `tone` to `string`, and a tone that is not one of
    // the four does nothing at all, silently, which is the same failure
    // as a class the stylesheet has never heard of.
    ...(needsCompliance ? ([{
      n: needsScript ? 3 : 2, title: "Compliance record",
      anchor: "step-compliance", tone: "check",
      done: items.length > 0 && complianceDone
        && (!needsInitials || initials.trim() !== ""),
      needs: items.length === 0
        ? "Add a medicine first. The record is about what is being supplied."
        : "Tick the script, the prescriber and the patient's identity, and "
          + "initial it.",
    }] as Step[]) : []),
    ...(!needsScript && items.length > 0 ? ([{
      n: 2, title: "Consultation", anchor: "step-counter", tone: "patient",
      done: !counsellingWanted || counselled,
      needs: counsellingWanted && !counselled
        ? "Confirm the patient was counselled before this can be handed over."
        : "Record who it is for and what it is for.",
    }] as Step[]) : []),
    { n: steps_last_number(needsScript, needsCompliance),
      title: needsScript ? "Safety check & dispense" : "Hand it over",
      anchor: "step-dispense", tone: "go",
      // Never "done" until it has happened; the screen clears when it does.
      done: false,
      needs: blockedBecause() || (needsScript ? "Ready to dispense."
                                              : "Ready to hand over.") },
  ];

  /** The quote, as something a patient can take away and think about.
   *
   *  A quote is the one thing on this screen that leaves the building without
   *  any medicine attached to it. It is read at a kitchen table, compared
   *  against another pharmacy's, and brought back a week later, so it needs
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
      // the dispensing fee, and the shelf price where there is not. Quoting
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
          directions: line.dosage_instructions || "none",
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

  /* Nothing here is available to this person, so the screen says that instead
     of performing a dispensary that refuses every control one at a time.

     Only once the server has answered. `can` is false while the session loads,
     and a dispensary that flashes "you may not dispense" every morning before
     drawing itself is one nobody believes the second time. */
  if (session.known && !mayDispense) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>Dispensary</h1>
            <div className="sub">Nothing on this screen is yours to use</div>
          </div>
        </div>
        <div className="card empty-state">
          <p>
            Your account carries none of the dispensing permissions, so there
            is nothing here you could hand over. That is a setting, not a
            fault: whoever administers this pharmacy can add one on the role
            matrix, or grant it to you by name.
          </p>
          <p className="muted">
            If you came here to serve somebody at the counter, the till is on
            the Point of Sale screen.
          </p>
          <Link className="btn" to="/pos">Go to Point of Sale</Link>
        </div>
      </>
    );
  }

  return (
    <div className="disp-dense">
      <KeyMap keys={hotkeys} open={showKeys} onClose={() => setShowKeys(false)} />
      {/* One line: what this screen is, which route is open, the routes you may
          switch to, and the four ways in. Hard right where they already were.
          It was a title, a sentence beneath it, a border and a margin: 98
          vertical pixels to say one word and one hint, on a screen that then
          had to scroll to reach the script. */}
      {/* The bar is what you can DO, and nothing else.

          The title said "Dispensary" on the dispensary screen, under a sidebar
          item called Dispensary that was already highlighted. Three statements
          of the same fact. Beside it the route hint described the tab that was
          already selected and visibly labelled.

          Between them they took about 330px of the bar, which is why the four
          buttons had to shrink to icons to fit. With the words gone the buttons
          keep their names, and a button that says "Alter script" needs no
          learning. */}
      <div className="disp-head">
        {/* What has already gone out. A dispensary is asked about yesterday's
            script several times a day: "did she collect it", "was that one
            paid for", "print that label again", and the only way to answer
            was to know the patient and open their record. */}
        {/* The three things somebody starts on this screen, where the hand
            already is. Everything below is the work; these are the ways in. */}
        {/* On the head line rather than a strip of its own. Still only where
            there is something to choose between: a bar with one tab in it
            offers a click that does nothing and hints at a door that is not
            there. */}
        {/* The script this is: its number on top, its date beneath. A new
            script has no number until it is dispensed, and says so rather than
            showing one that might not be the one it gets. */}
        <div className="disp-scriptid" aria-live="polite">
          <span className={`disp-scriptid-no${fromRx || (!quoting && nextNumber) ? " is-number" : ""}`}>
            {fromRx ? fromRx.number : quoting ? "Quote" : nextNumber ?? "New script"}
          </span>
          <span className="disp-scriptid-date">
            {fmtDate(fromRx?.date ?? new Date().toISOString().slice(0, 10))}
            {fromRx?.draft ? " · N-Repeat" : fromRx ? "" : quoting ? " · not a script"
              : nextNumber ? " · taken on dispensing" : " · numbered on dispensing"}
          </span>
        </div>
        <span className="spacer" />
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
          {/* Beside Alter script, because they answer the same question. This
              script is wrong. For the two cases: part of it (alter) and all of
              it, before anything has gone out (cancel). Only on a saved script;
              a new capture is cleared with New script. */}
          {fromRx && !fromRx.draft && (
            <button className="btn secondary disp-cancel-open"
                    disabled={!mayCancelScript}
                    title={mayCancelScript
                      ? "Take this script off the worklist, with the reason"
                      : "A pharmacist or a manager cancels a script"}
                    onClick={() => openCancel({ id: fromRx.id, number: fromRx.number,
                                                patient: patient ? `${patient.first_name} ${patient.last_name}` : undefined,
                                                lines: items.length })}>
              <XCircle size={14} /> Cancel script
            </button>
          )}
          <Link className="btn secondary" to="/dispensing-history">
            <ClockCounterClockwise size={17} /> History
          </Link>
        </div>
      </div>

      {/* Work on the left, worklist on the right. The queue has to be in view
          while dispensing happens. A panel you navigate to is a panel checked
          twice a day. It stacks below laptop width, where a 320px column would
          leave no room for the work itself. */}
      <div className="disp-with-worklist">
      <div>
      {reprintRx !== null && (
        <LabelSheet rxId={reprintRx} onClose={closeReprint} />
      )}

      {/* Entered here, used here. The new driver is selected the moment it
          saves, because somebody who has just typed a name into this dialog
          has already chosen them. */}
      {addingDriver && (
        <DriverForm
          onClose={() => setAddingDriver(false)}
          onSaved={(d: any) => {
            setDrivers((all) => [...all.filter((x) => x.id !== d.id), d]);
            setDriverId(d.id);
            setAddingDriver(false);
          }}
        />
      )}


      {/* Nothing on this screen commits while it is a quote, so it says so
          once, plainly, at the top. A mode you cannot see is a mode somebody
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



      {/* Where you are, and what the step you are on is waiting for.
          In the flow rather than pinned: the route strip above was sticky once
          and taken down for eating the top of the screen on the one page that
          is long by nature. The same objection applies here, and the reason it
          costs nothing is that the bottom of the page already carries the
          missing condition beside the button that will not go. */}
      {/* The step trail is hidden where the screen is being fitted to one
          height. It costs 76px to name three sections that name themselves
          twelve pixels lower. The headings below are numbered for the same
          reason it was. It comes back on a tall screen, where the space is
          free and the overview is worth having. */}
      <div className="disp-steps"><StepTrail steps={steps} /></div>

        <div className="rx-split">
          <div>
            {/* The controlled-substance notice, in the colour this product
                already uses for a schedule, rather than an orange written into
                the element that stayed the same in both themes. */}
            {/* ONE FACT, NOT A PARAGRAPH.
                Three sentences of regulation stood here, and anybody allowed
                on this tab already knows that controlled medicines need a
                pharmacist and go in the register: it is why they are on this
                tab. What changes what they do next is the repeat rule, so
                that is what it says. */}
            {/* Shown when the SCRIPT calls for it, not when a tab is open.
                On the tab it asserted a rule about the strictest schedule over
                every script captured there, including the ones with no
                controlled line on them at all. */}
            {needsCompliance && (
              <div className="card sec sec-check dd-rule">
                <Warning size={15} weight="fill" />
                <span>
                  <b>{schedCode(highestSchedule)}</b>
                  {activePolicy?.max_repeats === 0 ? " permits no repeats and" : ""}
                  {" "}needs the checking pharmacist's initials.
                </span>
              </div>
            )}

            <div className="card sec sec-patient" id="step-patient">
              {/* No heading. The lane is three labelled fields. Patient,
                  Prescriber, Medicine. And a heading over them said nothing
                  the labels do not. The schedule badge stays, because THAT is not
                  obvious from anything else on the row. */}
              {needsCompliance && (
                <div className="disp-lane-badge">
                  <span className="badge sched">{schedCode(highestSchedule)}</span>
                </div>
              )}
              {/* FIRST, BECAUSE IT IS WHAT SOMEBODY TYPES FIRST.
                  The patient and the prescriber only appear once the basket
                  holds something that needs a script, so this used to be the
                  third field along with nothing beside it, and then two
                  fields arrived to its LEFT and moved the screen under the
                  dispenser's hand. All three are the same act — saying what
                  this script is for and what is on it — and they now run in
                  the order the work does. The heading went with them: a
                  table under a search box labelled "Medicine" does not need
                  telling it holds script items. */}
              <div className="lane-field disp-medicine">
                <input data-hk="product" id="disp-product" type="search"
                  // One box, one sentence. It named the tab's schedules, which
                  // was a promise about what the search would offer; it now
                  // offers whatever this person may dispense, and the badge on
                  // each result says which schedule that one is.
                  aria-label="Medicine: search by name"
                  placeholder={laneFocus === "product" ? MEDICINE_HINT : "Medicine"}
                  value={productQ}
                  onFocus={() => setLaneFocus("product")}
                  onBlur={() => setLaneFocus(null)}
                  onChange={(e) => setProductQ(e.target.value)}
                  onKeyDown={(e) => {
                    // A scanner's Enter, not a person's: check the pack.
                    if (e.key === "Enter" && looksLikeCode(productQ)) {
                      e.preventDefault();
                      const code = productQ.trim();
                      setProductQ("");
                      scanPack(code);
                    }
                  }} />
                {/* The camera, for a counter that has no scanner on it. A
                    phone or a laptop is the scanner instead, and the pack is
                    checked against the script exactly as a scanner's would be.
                    Hidden where the browser has no camera to offer. */}
                {cameraSupported() && (
                  <button type="button" className="lane-icon-btn lane-scan"
                          title="Scan the pack with the camera"
                          aria-label="Scan the pack with the camera"
                          onClick={() => setCameraOpen(true)}>
                    <Camera size={16} />
                  </button>
                )}
                <MagnifyingGlass className="lane-icon" size={15} weight="bold" aria-hidden="true" />
              </div>
              {/* Patient: asked for when a line needs a script.
                  Somebody buying a cough syrup is not registered
                  first, and the counter section below takes a
                  walk-in name where one is wanted. */}
              {needsScript && (
              <>
              {patient ? (
                <div className="lane-field is-picked disp-patient-picked">
                  <span className="dpp-who"
                        onMouseEnter={(e) => showTip(e,
                          `${patient.first_name} ${patient.last_name} · ID ${patient.id_number || "Not on file"}`, false)}
                        onMouseLeave={() => setTip(null)}>
                    <span className="cell-text">
                      <b>{patient.first_name} {patient.last_name}</b>
                      <span className="muted"> · ID {patient.id_number || "not on file"}</span>
                    </span>
                  </span>
                  {/* What the counter reaches for about this person, in one place
                      and always in the same order. Muted when a tool has nothing
                      to say, so a hand learns where each one is. The chip row that
                      used to sit under the lane is three of these. */}
                  <span className="lane-tools" role="toolbar" aria-label="About this patient">
                    {(() => {
                      const list = (patient.allergies || "").split(/[,;]+/)
                        .map((x) => x.trim()).filter(Boolean);
                      const label = list.length ? `Allergic to ${list.join(", ")}` : "No allergies recorded";
                      return (
                        <button type="button"
                                className={`lane-tool is-allergies${list.length ? " is-alert" : ""}`}
                                title={label} aria-label={label}
                                onClick={() => setLaneOpen("details")}>
                          <FirstAidKit size={17} weight={list.length ? "fill" : "regular"} />
                          {list.length > 0 && <span className="lane-tool-count">{list.length}</span>}
                        </button>
                      );
                    })()}
                    <InsuranceStanding patientId={patient.id} variant="icon"
                                       onOpen={() => setLaneOpen("insurance")} />
                    {!quoting && (
                      <RepeatsDue patientId={patient.id}
                                  alreadyOn={items.map((i) => i.product.id)}
                                  onAdd={addDueRepeat} variant="icon"
                                  onOpen={() => setLaneOpen("repeats")} />
                    )}
                    <button type="button" className="lane-tool is-history"
                            title="Prescription history" aria-label="Prescription history"
                            onClick={() => setLaneOpen("history")}>
                      <ClockCounterClockwise size={17} />
                    </button>
                    <button type="button" className="lane-tool is-details"
                            title="Patient details" aria-label="Patient details"
                            onClick={() => setLaneOpen("details")}>
                      <IdentificationCard size={17} />
                    </button>
                  </span>
                  <button type="button" className="lane-icon-btn dpp-change" onClick={() => setPatient(null)}
                          title="Change patient" aria-label="Change patient">
                    <X size={14} weight="bold" />
                  </button>
                </div>
              ) : (
                <>
                  {/* Labelled, like every other field. Without one this input
                      started 170px to the left of the prescriber directly
                      below it, and two adjacent rows with two different left
                      edges is what the whole band was being judged on. */}
                  {/* The field's name where the placeholder goes, and what to
                      type only once the cursor is in it. A label beside a narrow
                      field spent a fifth of its width on one word. */}
                  <div className="lane-field disp-patient-field">
                    <input id="disp-patient" data-hk="patient" type="search"
                      aria-label="Patient: search by name, ID number, phone or medical aid number"
                      placeholder={laneFocus === "patient" ? PATIENT_HINT : "Patient"}
                      value={patientQ}
                      onFocus={() => setLaneFocus("patient")}
                      onBlur={() => setLaneFocus(null)}
                      onChange={(e) => setPatientQ(e.target.value)} />
                    <MagnifyingGlass className="lane-icon" size={15} weight="bold" aria-hidden="true" />
                  </div>
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
                      <span>
                        <b>{p.last_name}, {p.first_name}</b>
                        {p.profile_number && <span className="muted mono"> {p.profile_number}</span>}
                        <span className="muted"> {p.id_number}</span>
                      </span>
                      <span className="muted">{p.medical_aid?.name ?? "Private"}</span>
                    </div>
                  ))}
                </>
              )}
              </>
              )}
              {/* Read before the first medicine goes on the script, not after
                  the basket is built. Whether the scheme is paying changes
                  whether this should be supplied on credit at all. */}

              {/* The two halves of one question. Who is this for, and who
                  wrote it. A script has never had one without the other, and
                  they were taking a row each. */}
              {/* Prescriber: only where there is a prescription.
                  A counter sale has no prescriber, and asking for
                  one was half the reason it needed a lane of its
                  own. */}
              {needsScript && (
              <>
              {/* The prescriber, searched and listed like the patient and the
                  medicine. It was a dropdown whose list was a popover as narrow
                  as its own field, the one field on the lane that behaved
                  differently from the two beside it. */}
              {(() => {
                const doctor = doctors.find((d) => d.id === doctorId) ?? null;
                if (doctor) {
                  return (
                    <div className="lane-field is-picked disp-doctor"
                         title={`${doctor.name} · practice ${doctor.practice_number || "Not on file"}`
                           + (doctor.phone ? ` · ${doctor.phone}` : "")}>
                      <span className="dpp-who"
                            onMouseEnter={(e) => showTip(e,
                              `${doctor.name} · practice ${doctor.practice_number || "Not on file"}`, false)}
                            onMouseLeave={() => setTip(null)}>
                        <span className="cell-text">
                          <b>{doctor.name}</b>
                          <span className="muted">
                            {" · "}
                            {doctor.practice_number || "no practice no."}
                            {doctor.ahfoz_number ? ` · AHFoZ ${doctor.ahfoz_number}` : ""}
                          </span>
                        </span>
                      </span>
                      <button type="button" className="lane-icon-btn" onClick={() => setDoctorId("")}
                              title="Change prescriber" aria-label="Change prescriber">
                        <X size={14} weight="bold" />
                      </button>
                    </div>
                  );
                }
                return (
                  <div className="lane-field disp-doctor">
                    <input id="disp-doctor" data-hk="doctor" type="search"
                      aria-label="Prescriber: search by name or practice number"
                      placeholder={laneFocus === "doctor" ? PRESCRIBER_HINT : "Prescriber"}
                      value={doctorQ}
                      onFocus={() => setLaneFocus("doctor")}
                      onBlur={() => setLaneFocus(null)}
                      onChange={(e) => setDoctorQ(e.target.value)} />
                    <MagnifyingGlass className="lane-icon" size={15} weight="bold" aria-hidden="true" />
                  </div>
                );
              })()}
              {doctorId === "" && doctorQ.trim().length >= 2 && (() => {
                const q = doctorQ.trim().toLowerCase();
                const hits = doctors
                  .filter((d) => `${d.name} ${d.practice_number ?? ""} ${d.ahfoz_number ?? ""}`
                    .toLowerCase().includes(q))
                  .slice(0, 8);
                if (hits.length === 0) {
                  return (
                    <div className="pick-none">
                      <span>No prescriber on file matches &ldquo;{doctorQ.trim()}&rdquo;.</span>
                      <button type="button" className="linkish"
                              onClick={() => setNewDoctor({
                                name: doctorQ.trim(), practice_number: "",
                                ahfoz_number: "", phone: "" })}>
                        Add them
                      </button>
                    </div>
                  );
                }
                return hits.map((d) => (
                  <div key={d.id} className="product-pick doc-pick"
                       onClick={() => { setDoctorId(d.id); setDoctorQ(""); }}>
                    <span>
                      <b>{d.name}</b>
                      {d.phone && <span className="muted"> · {d.phone}</span>}
                    </span>
                    {/* The numbers a claim is paid on, where the medicine
                        search puts its price: the thing being chosen between
                        when two prescribers share a surname, and the thing a
                        funder rejects the claim for when it is missing. */}
                    <span className="doc-nums">
                      {d.practice_number
                        ? <span className="doc-num"><span>Prac</span><b>{d.practice_number}</b></span>
                        : <span className="doc-num is-missing"><span>Prac</span><b>none</b></span>}
                      {d.ahfoz_number && d.ahfoz_number !== d.practice_number && (
                        <span className="doc-num"><span>AHFoZ</span><b>{d.ahfoz_number}</b></span>
                      )}
                    </span>
                  </div>
                ));
              })()}
              </>
              )}
            </div>

            {/* THE CONSULTATION, WHERE THE PATIENT AND PRESCRIBER WOULD BE.
                Same slot, because it answers the same question: who is this
                for, and on what authority. A script answers it with a doctor;
                a counter sale answers it with a pharmacist's own record of
                what was asked and what was said.

                It was a separate lane behind a tab, which meant a dispenser
                had to know before they started which kind of supply this was
                going to be. It appears now because the basket has nothing in
                it that needs a script. */}
            {!needsScript && items.length > 0 && (
              <div className="card sec sec-patient" id="step-counter">
                <div className="otc-consult">
                  <div className="otc-consult-head">The consultation</div>
                  <div className="lane-field">
                    <input value={indication} aria-label="Complaint"
                      onChange={(e) => setIndication(e.target.value)}
                      placeholder="What did they come in for?" />
                  </div>
                  {/* Who it is for, where somebody wants it recorded. A name
                      rather than a patient record, because a walk-in is not
                      registered and being made to register them is what sent
                      counter sales to the till instead. */}
                  <div className="lane-field">
                    <input value={customerName} aria-label="Who it is for"
                      onChange={(e) => setCustomerName(e.target.value)}
                      placeholder="Who it is for, if they gave a name" />
                  </div>
                  {/* The tick claims a conversation happened. The points say
                      what that conversation should cover, so it is a tick
                      about the medicine rather than about somebody's memory. */}
                  {items.length === 1 && (
                    <CounsellingPoints productId={items[0].product.id}
                      name={lineName(items[0].product)} compact />
                  )}
                  <div className="otc-ticks">
                    <Checkbox checked={counselled} onChange={setCounselled}>
                      Counselled on dose, duration and side effects
                    </Checkbox>
                    <Checkbox checked={referred} onChange={setReferred}>
                      Referred to a doctor
                    </Checkbox>
                  </div>
                  <textarea rows={2} value={otcNotes} aria-label="Notes"
                    className="otc-notes"
                    placeholder="Anything else worth recording"
                    onChange={(e) => setOtcNotes(e.target.value)} />
                </div>
              </div>
            )}

            <div className="card sec sec-items" id="step-items">
              {/* The end of the search is the beginning of the work, the same
                  as it is for a patient and a prescriber. A dispenser holding
                  a script for something not in the catalogue had to leave for
                  the stock screens, create the line, book in what arrived and
                  start the script again. What happens instead is that the
                  medicine goes out on a handwritten note. */}
              {productQ.trim().length >= 2 && productResults.length === 0 && (
                <div className="pick-none">
                  <span>No medicine on file matches &ldquo;{productQ.trim()}&rdquo;.</span>
                  <button type="button" className="btn small"
                          onClick={() => setNewMedicine({
                            name: productQ.trim(), strength: "",
                            dosage_form: "Tablet", schedule: "3", pack_size: "",
                            units_per_pack: 1, unit_price: 0, cost_price: 0,
                            quantity: "", batch: "", expiry: "" })}>
                    Add it
                  </button>
                </div>
              )}
              {productResults.map((p) => (
                <div key={p.id} className="product-pick" onClick={() => addItem(p)}>
                  <span>
                    <b>{p.name}</b> {p.strength} <span className="muted">{p.dosage_form}</span>
                    <span className={`badge ${routeForSchedule(p.schedule) === "controlled" ? "danger" : "muted"}`} style={{ marginLeft: 6 }}>{schedCode(p.schedule)}</span>
                  </span>
                  <span className="muted">
                    {money(p.unit_price)}
                    {(p.units_per_pack ?? 1) > 1
                      && <> / {p.units_per_pack} = <b>{money(perUnit(p))}</b> each</>}
                    {/* What this branch can hand over, not the group total.
                        A dispenser reading "5 in stock" and then being told
                        "not enough stock at this branch" is the software
                        contradicting itself, and the number it showed was the
                        wrong one. Undated stock is real and is said separately,
                        because it is one date away from being usable. */}
                    {/* The count, and the way to correct it. A dispenser finds
                        out the shelf is wrong at the moment they reach for the
                        box, and the figure they are looking at is the obvious
                        place to say so. */}
                    {" · "}
                    <button type="button" className="stock-fix"
                            title={`This branch holds ${p.here ?? p.quantity_on_hand}. `
                              + "Click to correct the count."}
                            onClick={(e) => { e.stopPropagation(); setAdjusting(p); }}>
                      {p.here ?? p.quantity_on_hand} here
                    </button>
                    {(p.here_undated ?? 0) > 0 && (
                      <span className="stock-undated"
                            title={`${p.here_undated} more here with no expiry recorded. `
                              + "Dispensing asks for the date off the pack."}>
                        {" "}+{p.here_undated} undated
                      </span>
                    )}
                    {/* The cash margin, before anything is on the script. This
                        is where a substitution is decided. The generic beside
                        the brand, and deciding it needs the two margins side
                        by side, not a report afterwards. */}
                    {(() => {
                      const m = shelfMargin(p.unit_price, p.cost_price);
                      return m === null ? null
                        : <MarginTag percent={m} compact />;
                    })()}
                  </span>
                </div>
              ))}
              {/* The editor, out of the grid and above it.

                  It used to sit inside the selected row, so selecting a line
                  pushed every line below it down the page. On a five-item
                  script the line being edited was the only one visible, which
                  defeats the point of a grid.

                  Fixed here, the grid never reflows and a row is one height
                  whether it is selected or not. A field that moves depending on
                  what is selected cannot be typed into without looking, and
                  somebody dispensing forty scripts a morning is not looking.

                  It names the line it is editing, because it is no longer
                  attached to one. */}
              {/* The line editor. Everything about one line in one place, laid
                  out in the order it is settled: how much, what the label says,
                  what the claim is raised on, what is written in the book. Beside
                  it, the facts the decisions rest on. Stock, price, margin, the
                  dose finding, what it could be swapped for. */}
              {editing !== null && items[editing] && (() => {
                const it = items[editing];
                const idx = editing;
                const pol = policyFor(it.product.schedule || 0);
                const maxRepeats = pol && pol.max_repeats >= 0 ? pol.max_repeats : 6;
                const each = lineEach(it);
                const shelf = perUnit(it.product);
                const perPack = it.product.units_per_pack ?? 1;
                const priced = marginFor(it.product.id);
                const dose = doseScreen.byProduct.get(it.product.id);
                // What this counter can hand over. The group total told a
                // dispenser there was plenty while the shelf beside them was
                // empty, which the FEFO walk then refused with the patient
                // already waiting.
                const onHand = Number(it.product.here ?? it.product.quantity_on_hand ?? 0);
                const go = (to: number) => { setOpenItem(to); setEditing(to); };
                return (
                  <div className="modal-backdrop" role="dialog" aria-modal="true"
                       aria-label={`Edit ${lineName(it.product)}`}
                       onClick={(e) => { if (e.target === e.currentTarget) setEditing(null); }}>
                    <div className="modal disp-edit">
                      <h2>
                        {it.product.name} {it.product.strength}
                        <span className={`badge ${routeForSchedule(it.product.schedule) === "controlled" ? "danger" : "muted"}`}>
                          {schedCode(it.product.schedule)}{pol?.register_entry ? " · register" : ""}
                        </span>
                        <span className="disp-entry-of">line {idx + 1} of {items.length}</span>
                      </h2>
                      <div className="ed-body">
                        <div className="ed-main">
                          <section className="ed-sec">
                            <h4>Supply</h4>
                            <div className="field">
                              <label htmlFor="ed-qty">Quantity</label>
                              <input id="ed-qty" type="number" min={1} value={it.quantity}
                                onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })} />
                              <span className="hint">
                                units{perPack > 1 ? ` · ${perPack} to a pack` : ""} · {money(each)} each ·{" "}
                                <b>{money(each * (it.quantity || 0))}</b>
                              </span>
                            </div>
                            {/* The price. One way in, and it opens the dialog
                                that holds the whole decision: the figure, or the
                                margin it should make, and whether it outlives
                                this script. A field here and a dialog on the
                                table would be two rules for one act. */}
                            <div className="field ed-price">
                              <label>Price each</label>
                              <div className="ed-price-row">
                                <button type="button" className="btn secondary small"
                                        disabled={authorisingPrice === it.product.id}
                                        onClick={() => { setEditing(null); setPricingLine(idx); }}>
                                  {authorisingPrice === it.product.id
                                    ? <><CircleNotch size={14} className="spin" /> Authorising…</>
                                    : <><Tag size={14} /> {money(each)} each · change</>}
                                </button>
                                {priced && (
                                  <MarginTag percent={priced.margin_percent} compact />
                                )}
                                {it.price !== undefined && authorisingPrice !== it.product.id && (
                                  <button type="button" className="linkish"
                                          onClick={() => clearLinePrice(idx)}>
                                    Back to {money(shelf)}
                                  </button>
                                )}
                              </div>
                              <span className="hint">
                                {it.price !== undefined
                                  ? <>Set by hand for this script. The shelf price is {money(shelf)}.</>
                                  : <>From the catalogue. Changing it needs a code, and is recorded.</>}
                              </span>
                            </div>
                          </section>
                          <section className="ed-sec">
                            <h4>Label</h4>
                            <div className="field">
                              <label>Directions</label>
                              {/* Shorthand in, sentence out. `1 t tds pc` becomes the
                                  line the patient reads on the label. */}
                              <SigInput
                                value={it.dosage_instructions}
                                onChange={(next) => updateItem(idx, { dosage_instructions: next })}
                              />
                            </div>
                          </section>
                          <section className="ed-sec">
                            <h4>Claim</h4>
                            <div className="field" id="ed-dx">
                              <label>Diagnosis</label>
                              <DiagnosisPicker autoFocus={false} value={it.icd10_code}
                                onChange={(code) => updateItem(idx, { icd10_code: code })} />
                              {!it.icd10_code
                                ? <span className="hint warn">Required to claim</span>
                                : it.icd10_code === DEFAULT_DIAGNOSIS
                                  ? <span className="hint">Default. Change it if the script gives one</span>
                                  : null}
                            </div>
                            {/* What the funder calls it. Here because this is
                                where the dispenser lands with the box in their
                                hand, and the code is printed on the box. Absent
                                entirely on a cash script. */}
                            {claimingAgainst && (
                              <SchemeCodeField
                                medicalAidId={claimingAgainst}
                                scheme={schemeName}
                                productId={it.product.id}
                                productName={it.product.name}
                                known={schemeCodes[it.product.id]}
                                onSaved={reloadSchemeCodes}
                              />
                            )}
                            {(() => {
                      const cov = coverageFor(it.product.id);
                      if (!cov || cov.status === "unknown") return null;
                      const tone = cov.status === "covered" ? "ok"
                        : cov.status === "excluded" ? "danger" : "warn";
                      return (
                        <div className={`coverage coverage-${tone}`}>
                          <div className="coverage-head">
                            <span className={`badge ${tone}`}>
                              {cov.status === "covered" ? "On benefit"
                                : cov.status === "reference" ? "Reference priced"
                                : cov.status === "authorisation" ? "Authorisation required"
                                : "Not on benefit"}
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
                          </section>
                          <section className="ed-sec">
                            <h4>Repeats</h4>
                            <div className="field">
                              <label htmlFor="ed-repeats">Repeats</label>
                              <input id="ed-repeats" type="number" min={0} max={maxRepeats}
                                value={it.repeats_allowed} disabled={maxRepeats === 0}
                                onChange={(e) => updateItem(idx, {
                                  repeats_allowed: Math.min(maxRepeats, Math.max(0, Number(e.target.value))),
                                })} />
                              {/* Future business the shop is agreeing to, priced at
                                  the moment it is agreed. */}
                              {it.repeats_allowed > 0 && (
                                <span className="hint">
                                  <RepeatValue
                                    value={each * (it.quantity ?? 0)}
                                    remaining={each
                                      * (it.quantity ?? 0) * it.repeats_allowed} />
                                  {" "}each, and to come on this script
                                </span>
                              )}
                            </div>
                            <div className="field">
                              <label htmlFor="ed-duration">Duration</label>
                              <input id="ed-duration" type="number" min={1} value={it.repeat_interval_days}
                                onChange={(e) => updateItem(idx, { repeat_interval_days: Number(e.target.value) })} />
                              <span className="hint">days this supply lasts</span>
                            </div>
                            <div className="field">
                              <label>Auto-refill</label>
                              <Select
                                value={String(it.auto_refill ? "yes" : "no")}
                                onChange={(v) => updateItem(idx, { auto_refill: v === "yes" })}
                                options={[{ value: "no", label: "No, remind patient" },
                                          { value: "yes", label: "Yes, prepare automatically" }]}
                                disabled={maxRepeats === 0}
                              />
                            </div>
                            {maxRepeats === 0 && (
                              <p className="chk-coverage">
                                Schedule {it.product.schedule}: no repeats permitted. A fresh
                                script is required each time.
                              </p>
                            )}
                          </section>
                        </div>
                        <aside className="ed-rail">
                          <section className="ed-sec">
                            <h4>This line</h4>
                            <dl className="ed-facts">
                              <dt>In stock</dt>
                              <dd className={onHand < (it.quantity || 0) ? "is-bad" : ""}>
                                <button type="button" className="ed-stock"
                                        title="Correct what this branch holds"
                                        onClick={() => { setEditing(null); setAdjusting(it.product); }}>
                                  {onHand}
                                </button>
                              </dd>
                              {/* Both typed where they are shown. A price is
                                  changed far more often than it is explained,
                                  and the explanation — margin, and whether it
                                  outlives this script — is still behind
                                  "change" below. */}
                              <dt>Each</dt>
                              <dd className="ed-money"
                                  onDoubleClick={() => startRailEdit("each", each, it.quantity || 1)}
                                  title="Double-click to change the price">
                                {railEdit === "each" ? (
                                  <input className="ed-money-input" autoFocus
                                         inputMode="decimal"
                                         aria-label={`Price each for ${it.product.name}`}
                                         value={railDraft}
                                         onChange={(e) => setRailDraft(e.target.value)}
                                         onBlur={() => commitRailEdit(idx, it.quantity || 1)}
                                         onKeyDown={(e) => {
                                           if (e.key === "Enter") { e.preventDefault(); commitRailEdit(idx, it.quantity || 1); }
                                           if (e.key === "Escape") { e.preventDefault(); setRailEdit(null); setRailDraft(""); }
                                         }} />
                                ) : money(each)}
                              </dd>
                              {/* WHAT THIS LINE COMES TO: the price each,
                                  times the quantity. Not an average of
                                  anything — the incumbent's "Avg Retail" is a
                                  property of the stock item and lives on the
                                  product, where a buyer reads it; this is one
                                  line of one script.

                                  Shown only when there is more than one unit,
                                  because at a quantity of one it repeats Each
                                  exactly, and two identical figures under two
                                  different labels read as one of them being
                                  wrong. That is what it was taken for. */}
                              {(it.quantity || 0) > 1 && (
                              <>
                              <dt>Line total</dt>
                              <dd className="ed-money"
                                  onDoubleClick={() => startRailEdit("line", each, it.quantity || 1)}
                                  title="Double-click to change what this line comes to">
                                {railEdit === "line" ? (
                                  <input className="ed-money-input" autoFocus
                                         inputMode="decimal"
                                         aria-label={`Total for this line of ${it.product.name}`}
                                         value={railDraft}
                                         onChange={(e) => setRailDraft(e.target.value)}
                                         onBlur={() => commitRailEdit(idx, it.quantity || 1)}
                                         onKeyDown={(e) => {
                                           if (e.key === "Enter") { e.preventDefault(); commitRailEdit(idx, it.quantity || 1); }
                                           if (e.key === "Escape") { e.preventDefault(); setRailEdit(null); setRailDraft(""); }
                                         }} />
                                ) : money(each * (it.quantity || 0))}
                              </dd>
                              </>
                              )}
                              {priced && (
                                <>
                                  <dt>Cost</dt><dd>{money(priced.cost)}</dd>
                                  {/* WHAT THE SCHEME IS ASKED FOR, typed where
                                      it is shown. The cover rule works off a
                                      category and a percentage and a dispenser
                                      often knows better. Setting it costs a
                                      code, and the patient covers the
                                      difference, so the line total does not
                                      move and the shortfall does. */}
                                  {(priced.claim > 0.005 || it.claim !== undefined) && (
                                    <>
                                      <dt>Claimed</dt>
                                      <dd className={`ed-money${it.claim !== undefined ? " is-hand-set" : ""}`}
                                          onDoubleClick={() => startRailEdit("claim", priced.claim, 1)}
                                          title={it.claim !== undefined
                                            ? `Set by hand. ${schemeName} normally covers more; `
                                              + "the patient is paying the difference."
                                            : "Double-click to change what the scheme is asked for"}>
                                        {railEdit === "claim" ? (
                                          <input className="ed-money-input" autoFocus
                                                 inputMode="decimal"
                                                 aria-label={`What ${schemeName} is asked for on ${it.product.name}`}
                                                 value={railDraft}
                                                 onChange={(e) => setRailDraft(e.target.value)}
                                                 onBlur={() => commitRailEdit(idx, it.quantity || 1)}
                                                 onKeyDown={(e) => {
                                                   if (e.key === "Enter") { e.preventDefault(); commitRailEdit(idx, it.quantity || 1); }
                                                   if (e.key === "Escape") { e.preventDefault(); setRailEdit(null); setRailDraft(""); }
                                                 }} />
                                        ) : money(priced.claim)}
                                      </dd>
                                      {/* What the patient is left with. The two
                                          move together the moment one is set by
                                          hand, and a claim shown without its
                                          shortfall invites "so what do they
                                          pay" on every line. */}
                                      {(priced.levy ?? 0) > 0.005 && (
                                        <>
                                          <dt>Patient</dt>
                                          <dd>{money(priced.levy)}</dd>
                                        </>
                                      )}
                                      {it.claim !== undefined && (
                                        <>
                                          <dt />
                                          <dd>
                                            <button type="button" className="linkish"
                                                    onClick={() => clearLineClaim(idx)}>
                                              Back to what {schemeName} covers
                                            </button>
                                          </dd>
                                        </>
                                      )}
                                    </>
                                  )}
                                  <dt>Margin</dt>
                                  <dd><MarginTag percent={priced.margin_percent} compact /></dd>
                                </>
                              )}
                            </dl>
                            {onHand < (it.quantity || 0) && (
                              <p className="ed-dose is-major">
                                <Warning size={14} weight="fill" /> Only {onHand} in stock.
                              </p>
                            )}
                          </section>
                          <section className="ed-sec">
                            <h4>Safety</h4>
                            {dose ? (
                              <p className={`ed-dose is-${dose.severity === "major" ? "major" : "minor"}`}>
                                <Warning size={14} weight="fill" /> {dose.detail}
                              </p>
                            ) : (
                              <p className="chk-coverage">No dose finding on the directions as written.</p>
                            )}
                            <button type="button" className="btn secondary small"
                                    onClick={() => { setEditing(null); runLineCheck(it); setChecking(it.product.id); }}>
                              <ShieldCheck size={14} /> Check this line
                            </button>
                          </section>
                          <details className="ed-sec disp-ref">
                            <summary>Substitutions</summary>
                            <Variants productId={it.product.id} skeleton />
                          </details>
                          <details className="ed-sec disp-ref">
                            <summary>Counselling</summary>
                            <CounsellingPoints productId={it.product.id}
                              name={lineName(it.product)} compact />
                          </details>
                        </aside>
                      </div>
                      {/* No Cancel: the dialog edits the line rather than holding a
                          copy of it, so there is nothing to discard. */}
                      <div className="disp-edit-actions">
                        <button type="button" className="btn secondary" disabled={idx === 0}
                                onClick={() => go(idx - 1)}>
                          ‹ Previous line
                        </button>
                        <button type="button" className="btn secondary"
                                disabled={idx >= items.length - 1} onClick={() => go(idx + 1)}>
                          Next line ›
                        </button>
                        <span className="finish-spacer" />
                        <button type="button" className="btn secondary ed-delete"
                                onClick={() => removeLine(idx)}>
                          <Trash size={14} /> Delete line
                        </button>
                        <button type="button" className="btn primary" onClick={() => setEditing(null)}>
                          Done
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })()}
              {/* The grid scrolls; the strip above it does not.
                  Both were inside one scrolling region, so the strip took
                  the top of it and pushed every row out of sight. The
                  fields have to stay still and the lines have to scroll
                  under them. That is the whole arrangement. */}
              <div className="disp-grid">
              {/* Column headings, always. A grid without them is a list of rows
                  that happen to line up, and they also fix the columns: the
                  header and every row share one template, so a long medicine
                  name cannot push the money column out of true on one line and
                  not the next.

                  Rendered whether or not there is anything on the script,
                  because a table shows where the work GOES as well as where it
                  is. Which is what somebody needs on a new script and why the
                  system we are compared to draws its empty rows. */}
              {/* The header answers the same double-click as the empty rows.
                  It is the top of the Medicine column, and somebody who wants
                  another medicine aims at the word rather than hunting for the
                  first free row, particularly on a script that already has a
                  dozen lines and the free rows are off the bottom. */}
              <div className="rx-item-head rx-item-cols" aria-hidden="true"
                   onDoubleClick={() => setNewLine(true)}>
                <span className="rx-col-edit" title="Double-click to add a medicine">
                  Medicine <PencilSimpleLine size={11} />
                </span>
                <span className="rx-item-qty rx-col-edit" title="Double-click a cell to edit it">
                  Qty <PencilSimpleLine size={11} />
                </span>
                <span className="rx-col-edit" title="Double-click a cell to edit it">
                  Directions <PencilSimpleLine size={11} />
                </span>
                <span className="rx-item-money rx-col-edit" data-hk="amount"
                      title="Double-click an amount to set it. It needs a code.">
                  Amount <PencilSimpleLine size={11} />
                </span>
                <span className="rx-item-margin">Margin</span>
                <span className="rx-item-actions">Action</span>
              </div>
              {items.map((it, idx) => {
                const pol = policyFor(it.product.schedule || 0);
                const maxRepeats = pol && pol.max_repeats >= 0 ? pol.max_repeats : 6;
                const open = openItem === idx;
                const each = lineEach(it);
                return (
                  <div key={it.product.id}
                       className={`rx-item${open ? " is-open" : ""}`}>
                    {/* The row. Five columns, the same five on every line, so
                        they align down the page because they are columns and
                        not because somebody kept them the same width. */}
                    {/* Selecting a row points the strip above at it. It does
                        not expand: a grid whose rows change height under the
                        hand working on them is a grid you cannot aim at. */}
                    <div className="rx-item-head"
                         onClick={() => setOpenItem(idx)}
                         role="button" tabIndex={0}
                         aria-current={open ? "true" : undefined}
                         onKeyDown={(e) => {
                           if (e.key === "Enter" || e.key === " ") {
                             e.preventDefault(); setOpenItem(idx);
                           }
                         }}>
                      {/* Double-click to edit in place; hover to read what the
                          column cuts off. The line editor is still the pencil. */}
                      <span className={`rx-item-name${editingCell(it, "medicine") ? " is-editing" : ""}`}
                            onDoubleClick={() => startCellEdit(it, idx, "medicine")}
                            onMouseEnter={(e) => showTip(e, lineName(it.product), true)}
                            onMouseLeave={() => setTip(null)}>
                        {editingCell(it, "medicine") ? (
                          <CellMedicineSearch
                            route=""
                            current={lineName(it.product)}
                            takenIds={items.map((x) => x.product.id)}
                            onPick={(p) => swapProduct(idx, p)}
                            onCancel={() => { cellEditRef.current = null; setCellEdit(null); }}
                            onTab={(dir) => moveCellEdit(it, idx, "medicine", dir)}
                          />
                        ) : (<>
                        {/* The dose finding, on the row it is about.
                            Costs nothing until there is something to say, which
                            is why it can live on a table the panel could not. */}
                        {(() => {
                          const d = doseScreen.byProduct.get(it.product.id);
                          if (!d) return null;
                          return (
                            <span
                              className={`rx-item-warn is-${d.severity === "major" ? "major" : "minor"}`}
                              role="button" tabIndex={-1}
                              onClick={(e) => { e.stopPropagation(); runLineCheck(it); setChecking(it.product.id); }}
                              title={`${d.detail}

${d.action}`}
                              aria-label={d.detail}
                            >
                              <Warning size={13} weight="fill" />
                            </span>
                          );
                        })()}
                        <span className="cell-text">{it.product.name} {it.product.strength}</span>
                        {/* The pack on the counter was scanned and is this line's
                            medicine. Absent, not red, when it has not been: most
                            tills have no scanner, and a row of warnings nobody can
                            clear would teach everybody to ignore the column. */}
                        {scanChecks[it.product.id] && (
                          <span className="rx-scan-ok" role="img"
                                title={`Pack scanned and matched · ${scanChecks[it.product.id]}`}
                                aria-label="Pack scanned and matched">
                            <Barcode size={13} weight="bold" />
                          </span>
                        )}
                        {/* Only on a scheme script, and only when there is no
                            code at all: this line will be rejected, and it is
                            the one thing on the row worth a mark. A line
                            standing on the pharmacy's own NAPPI is not marked.
                            It has a code and the claim carries it. */}
                        <NoCodeMark
                          known={schemeCodes[it.product.id]}
                          scheme={schemeName}
                          onFix={() => { setOpenItem(idx); setEditing(idx); }}
                        />
                        <span className={`badge ${routeForSchedule(it.product.schedule) === "controlled" ? "danger" : "muted"}`}>
                          {schedCode(it.product.schedule)}{pol?.register_entry ? " · register" : ""}
                        </span>
                        </>)}
                      </span>
                      <span className={`rx-item-qty${editingCell(it, "qty") ? " is-editing" : ""}`}
                            onDoubleClick={() => startCellEdit(it, idx, "qty")}>
                        {editingCell(it, "qty") ? (
                          <input className="cell-input is-num" type="number" min={1} autoFocus
                                 aria-label={`Quantity of ${it.product.name}`}
                                 value={it.quantity || ""}
                                 onFocus={(e) => e.currentTarget.select()}
                                 onChange={(e) => updateItem(idx, { quantity: Number(e.target.value) })}
                                 onKeyDown={(e) => cellKeys(e, it, idx, "qty")}
                                 onBlur={() => finishCellEdit(idx, "qty")} />
                        ) : it.quantity}
                      </span>
                      {/* What the label will say, on the row, so a closed line
                          still shows the thing most likely to be wrong. */}
                      <span className={`rx-item-sig${editingCell(it, "sig") ? " is-editing" : ""}`}
                            onDoubleClick={() => startCellEdit(it, idx, "sig")}
                            onMouseEnter={(e) => { if (it.dosage_instructions) showTip(e, it.dosage_instructions, true); }}
                            onMouseLeave={() => setTip(null)}>
                        {editingCell(it, "sig") ? (
                          <SigInput compact autoFocus
                            value={it.dosage_instructions}
                            placeholder="Directions or codes, e.g. 1a tds"
                            onChange={(next) => {
                              // Ignored once the cell has closed: the field's own
                              // blur can still commit an expansion on its way out,
                              // and must not undo an Escape.
                              const cur = cellEditRef.current;
                              if (cur?.id === it.product.id && cur.col === "sig") {
                                updateItem(idx, { dosage_instructions: next });
                              }
                            }}
                            onKeyDown={(e) => cellKeys(e, it, idx, "sig")}
                            onBlur={() => finishCellEdit(idx, "sig")} />
                        ) : (
                          <span className="cell-text">
                            {it.dosage_instructions || <em>no directions yet</em>}
                          </span>
                        )}
                      </span>
                      {/* The amount, and the one cell on the row that costs a
                          code to change. Rounding a line off is ordinary work;
                          doing it without anybody knowing is not. */}
                      <span className={`rx-item-money${editingCell(it, "money") ? " is-editing" : ""}`
                            + (it.price !== undefined ? " is-hand-set" : "")}
                            onDoubleClick={() => startCellEdit(it, idx, "money")}
                            title={it.price !== undefined
                              ? `Set by hand for this script. The shelf price is `
                                + `${money(perUnit(it.product))} each.`
                              : "Double-click to change this amount. It needs a code."}>
                        {editingCell(it, "money") ? (
                          <input className="cell-input is-num" type="number" min={0} step="0.01"
                                 autoFocus
                                 aria-label={`Amount for ${it.product.name}`}
                                 value={priceDraft}
                                 onFocus={(e) => e.currentTarget.select()}
                                 onChange={(e) => setPriceDraft(e.target.value)}
                                 onKeyDown={(e) => cellKeys(e, it, idx, "money")}
                                 onBlur={() => finishCellEdit(idx, "money")} />
                        ) : authorisingPrice === it.product.id ? (
                          <span className="rx-price-waiting">
                            <CircleNotch size={12} className="spin" />
                            {money(each * (it.quantity || 0))}
                          </span>
                        ) : (<>
                          {money(each * (it.quantity || 0))}
                          {it.price !== undefined && (
                            <span className="rx-hand-set" role="img"
                                  aria-label="Price set by hand and authorised">
                              <PencilSimpleLine size={11} weight="bold" />
                            </span>
                          )}
                        </>)}
                      </span>
                      {/* Always a cell, with or without a figure in it. A column
                          that is only sometimes there moves every column after it. */}
                      <span className="rx-item-margin">
                        {(() => {
                          const l = marginFor(it.product.id);
                          return l ? <MarginTag percent={l.margin_percent} compact /> : null;
                        })()}
                      </span>
                      {/* Action. Icons, because a table that does this much on
                          every line cannot spell each thing out on every line.
                          And each names itself on hover and to a screen reader.

                          The shield checks the line: pressed once it runs, and
                          its colour is the answer; pressed on an answer it
                          opens the detail. */}
                      <span className="rx-item-actions">
                        {(() => {
                          const st = lineState(it);
                          const label = {
                            idle: "Check this line. Dose and interactions",
                            loading: "Checking…",
                            clean: "Checked: nothing found. Open the detail",
                            minor: "Checked: something to look at. Open the detail",
                            major: "Checked: a major finding. Open the detail",
                            error: "The check could not run. Open to see why",
                          }[st];
                          return (
                            <button type="button" className={`rx-icon chk-${st}`}
                                    title={label} aria-label={`${label}. ${it.product.name}`}
                                    aria-busy={st === "loading" || undefined}
                                    onClick={(e) => { e.stopPropagation(); onCheckIcon(it); }}>
                              {st === "loading" ? <CircleNotch size={16} className="spin" />
                                : st === "idle" ? <ShieldCheck size={16} />
                                : st === "clean" ? <ShieldCheck size={16} weight="fill" />
                                : <ShieldWarning size={16} weight="fill" />}
                            </button>
                          );
                        })()}
                        <button type="button" className="rx-icon"
                                title="Edit this line" aria-label={`Edit ${it.product.name}`}
                                onClick={(e) => { e.stopPropagation(); setOpenItem(idx); setEditing(idx); }}>
                          <PencilSimple size={16} />
                        </button>
                        <button type="button" className="rx-icon is-remove"
                                title="Delete this line" aria-label={`Delete ${it.product.name}`}
                                onClick={(e) => { e.stopPropagation(); removeLine(idx); }}>
                          <Trash size={16} />
                        </button>
                      </span>
                    </div>
                  </div>
                );
              })}
              {/* Ruled to the floor. The rows a script has not reached yet are
                  drawn, not left as a void with an apology in the middle of it:
                  a table that stops where the data stops does not show anybody
                  where the next line goes. */}
              {/* The waiting rows fill what is left of the frame and are clipped
                  at its floor. A fixed eight overflowed as soon as the patient's
                  details made the lane above taller, and an empty table grew a
                  scrollbar for rows with nothing in them. */}
              {/* THE FIRST EMPTY ROW IS WHERE THE NEXT MEDICINE IS ASKED FOR.

                  Double-clicking an empty row used to throw focus back up to
                  the Medicine field above the table, which is the one place the
                  eye is not: it is on the row it just aimed at. So the row
                  becomes the search, in the place the line is about to appear,
                  and the same double-click that edits a line already on the
                  script starts the one that is not there yet.

                  It sits between the script's lines and the ruled rows below,
                  so on an empty script it IS the first row and on a script with
                  three lines it is the fourth. One of the ruled rows below
                  stands down while it is open, so the table does not grow a row
                  and shunt everything under it. */}
              {newLine && (
                <div className="rx-item rx-item-new">
                  <div className="rx-item-head">
                    <span className="rx-item-name is-editing">
                      <CellMedicineSearch
                        adding
                        route=""
                        current="Search for a medicine"
                        takenIds={items.map((x) => x.product.id)}
                        onPick={(p) => { setNewLine(false); addItem(p); }}
                        onCancel={() => setNewLine(false)}
                        // Tab out of a line that does not exist yet has nowhere
                        // to go, so it closes rather than moving to a column of
                        // a row nothing has been chosen for.
                        onTab={() => setNewLine(false)}
                      />
                    </span>
                    <span className="rx-item-qty" /><span /><span className="rx-item-money" />
                    <span className="rx-item-margin" /><span className="rx-item-actions" />
                  </div>
                </div>
              )}
              {/* The empty rows are where the next line goes, so double-clicking
                  one starts the work rather than doing nothing. The same gesture
                  that edits a line that is already there. Mouse-only and
                  decorative, so it stays hidden from assistive technology: the
                  keyboard has F3, which is the documented way in. */}
              <div className="rx-waiting" aria-hidden="true"
                   onDoubleClick={() => setNewLine(true)}>
              {Array.from({ length: newLine ? 23 : 24 }).map((_, i) => (
                <div key={`waiting-${i}`} className="rx-item rx-item-waiting"
                     aria-hidden="true">
                  <div className="rx-item-head">
                    <span className="rx-item-name">
                      {i === 0 && items.length === 0 && !newLine && (
                        <em className="rx-item-hint">Double-click here to start, or press F3</em>
                      )}
                    </span>
                    <span /><span /><span /><span /><span />
                  </div>
                </div>
              ))}
              {/* The rules run to the floor of the table. Without this the
                  columns stopped at the eighth row and the rest of the frame was
                  an empty box, which reads as the table ending early. */}
              <div className="rx-item rx-item-waiting rx-item-fill" aria-hidden="true">
                <div className="rx-item-head">
                  <span /><span /><span /><span /><span /><span />
                </div>
              </div>
              </div>
              {/* The table's own last row: what the columns above add up to.
                  Bound to the lines. Delete the last one and it goes with it. */}
              {items.length > 0 && pricing && (
                <ScriptTotals variant="footer" data={pricing} items={pricedItems}
                              medicalAidId={patient?.medical_aid_id ?? null} />
              )}
              </div>
            </div>

            {/* ONE ROW UNDER THE TABLE.

                On the left, the one thing the dispenser needs to know next. What
                is missing, or that it is ready, or what just happened. And how
                many warnings are waiting. On the right, the only three things to
                do from here: who checked it, put it down, or finish it.

                Everything that is only needed at the END of a script. Settling
                warnings, the compliance record, how it is paid, the dispense
                itself. Is in Finish, and not on the page. Stacked under the
                table it pushed itself and the table off the bottom of the
                screen, and it was on screen for the whole of the script while
                being needed for the last ten seconds of it. */}
            <div className="card sec sec-go disp-bar" id="step-dispense">
              <div className="disp-status" aria-live="polite">
                {items.length === 0 && doneSale ? (
                  <p className={`disp-done ${doneSale.status === "paid" ? "is-paid" : "is-owed"}`}>
                    <ShieldCheck size={15} weight="fill" />
                    <span className="disp-done-text">
                      {doneSale.status === "paid" ? (
                        <>Dispensed and paid · <b>{doneSale.sale_number}</b> · {money(doneSale.total)}</>
                      ) : (
                        <>Dispensed · <b>{doneSale.sale_number}</b> ·{" "}
                        <b>{money(patientPortion(doneSale))}</b> to collect from the patient
                        {/* The scheme's share said plainly, so nobody asks a member
                            for the funder's money as well as their own. */}
                        {patientPortion(doneSale) < doneSale.total - 0.005 && (
                          <> · {money(doneSale.total - patientPortion(doneSale))} on the scheme</>
                        )}</>
                      )}
                    </span>
                    {doneRxId && (
                      <button type="button" className="linkish" onClick={() => setReprintRx(doneRxId)}>
                        <Printer size={13} /> Reprint labels
                      </button>
                    )}
                    {doneRxId && (
                      <button type="button" className="linkish" onClick={() => printClaimCopy(doneRxId)}>
                        <FileText size={13} /> Claim copy
                      </button>
                    )}
                    {doneSale.status !== "paid" && (
                      <Link to={`/pos?settle=${doneSale.id}`}>
                        Take payment <ArrowRight size={12} weight="bold" />
                      </Link>
                    )}
                    <button type="button" className="linkish" onClick={() => setDoneSale(null)}>
                      Dismiss
                    </button>
                  </p>
                ) : fromRx?.draft ? (
                  <p className="disp-blocked">
                    <Warning size={14} weight="fill" />
                    <span>
                      <b>{fromRx.number} is a {DRAFT_SCRIPT.toLowerCase()}.</b> It takes an Rx
                      number when capturing is finished.
                    </span>
                  </p>
                ) : blockedBecause() && !(quoting && items.length > 0) ? (
                  // When the blocker IS the blocking warning, the chip beside this
                  // already says so and pressing it goes there — saying it twice
                  // cost the room the sentence needed.
                  blocked && (counter.data?.count ?? 0) > 0 ? null : (
                    // The sentence is the control. A separate "Take me there"
                    // was 85px spent saying "this is clickable".
                    <button type="button" className="disp-say disp-blocked"
                            onClick={takeMeThere}
                            title={`${blockedBecause()} Press to go there.`}>
                      <Warning size={14} weight="fill" />
                      <span>{blockedBecause()}</span>
                      <CaretRight size={12} weight="bold" />
                    </button>
                  )
                ) : (
                  <p className="disp-ready">
                    <ShieldCheck size={14} weight="fill" />
                    <span>{quoting ? "Ready to print the quote." : "Ready. Finish, or press F12."}</span>
                  </p>
                )}
                {items.length > 0 && (counter.data?.count ?? 0) > 0 && (
                  <button type="button"
                          className={`disp-chip${counter.outstanding.length ? " is-stop" : ""}`}
                          onClick={() => openFinish("finish-warnings")}>
                    <Warning size={13} weight="fill" />
                    {counter.data!.count} warning{counter.data!.count === 1 ? "" : "s"}
                    {counter.outstanding.length > 0 && ` · ${counter.outstanding.length} blocking`}
                  </button>
                )}
              </div>
              <div className="disp-commit-row">
                {needsInitials && !quoting && (
                  <div className={`lane-field disp-initials${initials.trim() ? " is-signed" : ""}`}>
                    <input id="disp-initials" value={initials} maxLength={8}
                      aria-label="Checked by: the initials of the pharmacist who checked this dispensing"
                      title={INITIALS_TITLE}
                      placeholder={initialsFocus === "bar" ? INITIALS_HINT : "Checked by"}
                      onFocus={() => setInitialsFocus("bar")}
                      onBlur={() => setInitialsFocus(null)}
                      onChange={(e) => setInitials(e.target.value.toUpperCase())} />
                    {initials.trim()
                      ? <Check className="lane-icon" size={14} weight="bold" aria-hidden="true" />
                      : <Signature className="lane-icon" size={15} aria-hidden="true" />}
                  </div>
                )}
                {/* A saved script can be put down on purpose, with the reason.
                    Held, the same place offers the release. To a pharmacist or
                    a manager, and says so to anybody else. */}
                {fromRx && !fromRx.draft && !quoting && (hold ? (
                  <BusyButton className="btn secondary disp-hold is-held" busyLabel="Releasing…"
                              disabled={!mayReleaseHold}
                              title={mayReleaseHold
                                ? "Release this script so it can be dispensed"
                                : "A pharmacist or a manager releases a hold"}
                              onClick={releaseHold}>
                    Release hold
                  </BusyButton>
                ) : (
                  <button type="button" className="btn secondary disp-hold"
                          title="Put this script down, with the reason, until it can go out"
                          onClick={openHoldDialog}>
                    Hold
                  </button>
                ))}
                {/* Put it down and come back to it. Not while quoting: a quote
                    saved as a draft would put a price enquiry on the worklist. */}
                {!quoting && (
                  <BusyButton className="btn secondary" busyLabel="Saving…"
                              disabled={!patient || items.length === 0}
                              onClick={saveDraft}>
                    {fromRx?.draft ? "Save the draft" : "Save for later"}
                  </BusyButton>
                )}
                {/* A quote commits nothing, so it is a different button rather
                    than the same one in a different mood. */}
                {quoting ? (
                  <button type="button" className="btn primary disp-go"
                          disabled={items.length === 0} onClick={printQuote}>
                    Print the quote
                  </button>
                ) : fromRx?.draft ? (
                  <BusyButton className="btn primary disp-go" busyLabel="Finishing…"
                    disabled={!patient || items.length === 0 || doctorId === ""}
                    onClick={finaliseDraft}>
                    Finish capturing
                  </BusyButton>
                ) : (
                  <button type="button" className="btn primary disp-go"
                          // Finish only opens a dialog, which commits nothing, so it
                          // stays open to a script that is not ready yet. A held one
                          // is different: nothing in that dialog can be done until
                          // somebody releases it, and choosing how to pay for what
                          // cannot go out is time taken from the next patient.
                          disabled={busy || !patient || items.length === 0 || !!hold}
                          title={hold ? "On hold. Release it before finishing" : undefined}
                          onClick={() => openFinish()}>
                    Finish <kbd className="disp-kbd">F12</kbd>
                  </button>
                )}
              </div>
            </div>

            {/* FINISH. Two stages, so neither has to scroll.

                  Before you finish   what must be acknowledged and what is worth
                                      knowing. Proceed is held until the blocking
                                      ones are settled. Skipped when there is none.
                  Pay & dispense      how it is paid beside the bill, the
                                      compliance record on the controlled route,
                                      who checked it, and Dispense.

                Opening it commits nothing. "Back to the script" rather than
                Cancel, because there is nothing held here to discard. */}
            {finishing !== null && patient && items.length > 0 && (() => {
              const doseMajors = [...doseScreen.byProduct.values()]
                .filter((f) => f.severity === "major");
              const msgs = counter.data?.messages ?? [];
              const blockingMsgs = msgs.filter((m) => m.blocking);
              const advisoryMsgs = msgs.filter((m) => !m.blocking);
              const notCovered = !!coverage && !coverage.all_claimable;
              const needsAuth = !!coverage?.authorisation_required && !!coverage?.all_claimable;
              const hasSettle = needsSettling();
              const stage = hasSettle ? finishStage : "pay";
              const toAck = counter.outstanding.length
                + (doseMajors.length > 0 && !ixAcknowledged ? 1 : 0)
                + expiryNeeded.filter((l) => !packExpiry[l.product_id]
                    || packExpiry[l.product_id] < localIsoDate()).length;
              const worthKnowing = advisoryMsgs.length + (notCovered ? 1 : 0) + (needsAuth ? 1 : 0);
              const held = settleBlocks();
              const why = blockedBecause();
              const fee = payHow === "delivery" ? (Number(deliveryFee) || 0) : 0;
              const gross = split?.total ?? pricing?.totals.gross ?? 0;
              return (
                <div className="modal-backdrop" role="dialog" aria-modal="true"
                     aria-label={stage === "settle" ? "Before you finish" : "Pay and dispense"}
                     onClick={(e) => { if (e.target === e.currentTarget) setFinishing(null); }}>
                  <div className={`modal disp-finish is-${stage}${needsCompliance ? " is-controlled" : ""}`}>
                    <h2>
                      {stage === "settle" ? "Before you finish" : "Pay & dispense"}
                      {hasSettle && (
                        <span className="fin-steps">
                          <button type="button"
                                  className={`fin-step ${stage === "settle" ? "is-on" : "is-done"}`}
                                  onClick={() => setFinishStage("settle")}>
                            <span className="fin-step-n">
                              {stage === "settle" ? "1" : <Check size={10} weight="bold" />}
                            </span>
                            Settle
                          </button>
                          <span className="fin-step-rule" aria-hidden="true" />
                          <button type="button"
                                  className={`fin-step${stage === "pay" ? " is-on" : ""}`}
                                  disabled={!!held} onClick={proceedToPay}>
                            <span className="fin-step-n">2</span>
                            Pay
                          </button>
                        </span>
                      )}
                      <span className="disp-entry-of">
                        {patient.first_name} {patient.last_name} · {items.length} line{items.length === 1 ? "" : "s"} · {money(gross)}
                      </span>
                    </h2>

                    {stage === "settle" ? (
                      <div id="finish-warnings">
                        {counter.error && <div className="alert error">{counter.error}</div>}
                        <div className="fin-stats">
                          <div className={`fin-stat${toAck ? " is-stop" : ""}`}>
                            <b>{toAck}</b><span>To acknowledge</span>
                          </div>
                          <div className={`fin-stat${worthKnowing ? " is-warn" : ""}`}>
                            <b>{worthKnowing}</b><span>Worth knowing</span>
                          </div>
                          <div className="fin-stat">
                            <b>{items.length}</b><span>line{items.length === 1 ? "" : "s"} screened</span>
                          </div>
                        </div>

                        {/* Stock with no expiry recorded. Asked here, before
                            paying, of the person holding the pack. Rather than
                            refused after, as "expired", which it was not. */}
                        {/* WHICH LOT IS GOING OUT.
                            Here, beside the expiry read off the pack, because
                            it is the same moment and the same act: confirming
                            what is actually being handed over. Each line says
                            which lot the rotation will take, which is worth
                            stating on its own; choosing a different one asks
                            why and then asks for a supervisor.

                            The picker draws nothing for a line whose shelf
                            holds one lot, so an ordinary script shows an
                            ordinary list and nobody is asked anything. */}
                        {items.length > 0 && (
                          <section className="fin-group" id="finish-lots">
                            <h4>Which lot is going out</h4>
                            <p className="fin-note">
                              First expiry first out, unless somebody says
                              otherwise. Taking a lot out of turn needs a
                              reason and a supervisor.
                            </p>
                            <ul className="fin-list">
                              {items.filter((it) => it.item_id).map((it) => (
                                <li key={it.item_id} className="fin-item">
                                  <div className="fin-item-body">
                                    <p><b>{lineName(it.product)}</b></p>
                                    <LotPicker
                                      productId={it.product.id}
                                      productName={it.product.name}
                                      value={scriptLots[it.item_id!] ?? ROTATION}
                                      onChange={(next) => setScriptLots((cur) => ({
                                        ...cur, [it.item_id!]: next }))}
                                    />
                                  </div>
                                </li>
                              ))}
                            </ul>
                          </section>
                        )}

                        {expiryNeeded.length > 0 && (
                          <section className="fin-group fin-expiry" id="finish-expiry">
                            <h4>Expiry from the pack</h4>
                            <p className="fin-note">
                              This stock came in with no expiry date recorded. Enter the date
                              printed on the pack you are handing over. It is saved to the
                              stock, and printed on the label.
                            </p>
                            <ul className="fin-list">
                              {expiryNeeded.map((l) => {
                                const value = packExpiry[l.product_id] ?? "";
                                const past = !!value && value < localIsoDate();
                                return (
                                  <li key={l.product_id}
                                      className={`fin-item ${!value || past ? "is-stop" : "is-done"}`}>
                                    <span className="fin-item-icon"><CalendarBlank size={16} /></span>
                                    <div className="fin-item-body">
                                      <p><b>{l.name}</b></p>
                                      <p className="muted small">
                                        {l.undated_units} on the shelf with no expiry recorded
                                        {l.dated_units ? `, ${l.dated_units} dated` : ""}
                                      </p>
                                      {past && (
                                        <p className="fin-note is-bad">
                                          <Warning size={13} weight="fill" />
                                          <span>That pack has expired. Take another from the shelf.</span>
                                        </p>
                                      )}
                                    </div>
                                    <div className="fin-item-act">
                                      <input type="date" id={`pack-expiry-${l.product_id}`}
                                             aria-label={`Expiry printed on the pack of ${l.name}`}
                                             value={value}
                                             onChange={(e) => setPackExpiry((cur) => ({
                                               ...cur, [l.product_id]: e.target.value }))} />
                                    </div>
                                  </li>
                                );
                              })}
                            </ul>
                          </section>
                        )}

                        {(doseMajors.length > 0 || blockingMsgs.length > 0) && (
                          <section className="fin-group">
                            <h4>Must be acknowledged</h4>
                            <ul className="fin-list">
                              {doseMajors.length > 0 && (
                                <li className={`fin-item ${ixAcknowledged ? "is-done" : "is-stop"}`}>
                                  <span className="fin-item-icon"><Warning size={16} weight="fill" /></span>
                                  <div className="fin-item-body">
                                    <div className="fin-item-meta">
                                      <span className="badge">Dose check</span>
                                      <span className="badge muted">Over the maximum</span>
                                    </div>
                                    {doseMajors.map((f) => (
                                      <p key={f.product}><b>{f.product}</b>: {f.detail}</p>
                                    ))}
                                  </div>
                                  <div className="fin-item-act">
                                    {ixAcknowledged ? (
                                      <button type="button" className="fin-ack" title="Undo"
                                              onClick={() => setIxAcknowledged(false)}>
                                        <Check size={13} weight="bold" /> Checked
                                      </button>
                                    ) : (
                                      <button type="button" className="btn danger small"
                                              onClick={() => setIxAcknowledged(true)}>
                                        I have checked this
                                      </button>
                                    )}
                                  </div>
                                </li>
                              )}
                              {blockingMsgs.map((m, i) => {
                                const done = m.id !== null && counter.acked.has(m.id);
                                return (
                                  <li key={m.id ?? `b${i}`} className={`fin-item ${done ? "is-done" : "is-stop"}`}>
                                    <span className="fin-item-icon"><Warning size={16} weight="fill" /></span>
                                    <div className="fin-item-body">
                                      <div className="fin-item-meta">
                                        <span className="badge">{m.source}</span>
                                        {m.category && <span className="badge muted">{m.category}</span>}
                                      </div>
                                      <p>{m.body}</p>
                                    </div>
                                    <div className="fin-item-act">
                                      {done ? (
                                        <span className="fin-ack" title="Recorded against the script, in your name, when it is dispensed"><Check size={13} weight="bold" /> Acknowledged</span>
                                      ) : (
                                        <button type="button" className="btn danger small"
                                                disabled={counter.busy === m.id}
                                                onClick={() => counter.acknowledge(m)}>
                                          {counter.busy === m.id ? "Recording…" : "I have checked this"}
                                        </button>
                                      )}
                                    </div>
                                  </li>
                                );
                              })}
                            </ul>
                          </section>
                        )}

                        {worthKnowing > 0 && (
                          <section className="fin-group">
                            <h4>Worth knowing</h4>
                            <ul className="fin-list">
                              {advisoryMsgs.map((m, i) => (
                                <li key={m.id ?? `a${i}`}
                                    className={`fin-item ${m.severity === "info" ? "is-info" : "is-warn"}`}>
                                  <span className="fin-item-icon">
                                    {m.severity === "info"
                                      ? <Info size={16} weight="fill" />
                                      : <Warning size={16} weight="fill" />}
                                  </span>
                                  <div className="fin-item-body">
                                    <div className="fin-item-meta">
                                      <span className="badge">{m.source}</span>
                                      {m.category && <span className="badge muted">{m.category}</span>}
                                    </div>
                                    <p>{m.body}</p>
                                  </div>
                                  <div className="fin-item-act"><span className="fin-item-note">Advisory</span></div>
                                </li>
                              ))}
                              {notCovered && (
                                <li className="fin-item is-warn">
                                  <span className="fin-item-icon"><Warning size={16} weight="fill" /></span>
                                  <div className="fin-item-body">
                                    <div className="fin-item-meta">
                                      <span className="badge">Scheme</span>
                                      <span className="badge muted">Not covered</span>
                                    </div>
                                    <p>
                                      {coverage!.blocked_count} line{coverage!.blocked_count === 1 ? " is" : "s are"} not
                                      covered by {coverage!.formulary}. Dispensing is allowed; the patient pays
                                      for {coverage!.blocked_count === 1 ? "it" : "them"} and the scheme will not.
                                    </p>
                                  </div>
                                  <div className="fin-item-act"><span className="fin-item-note">Advisory</span></div>
                                </li>
                              )}
                              {needsAuth && (
                                <li className="fin-item is-warn">
                                  <span className="fin-item-icon"><Warning size={16} weight="fill" /></span>
                                  <div className="fin-item-body">
                                    <div className="fin-item-meta">
                                      <span className="badge">Scheme</span>
                                      <span className="badge muted">Authorisation</span>
                                    </div>
                                    <p>
                                      One or more lines need an authorisation number from the scheme
                                      before the claim will be paid.
                                    </p>
                                  </div>
                                  <div className="fin-item-act"><span className="fin-item-note">Advisory</span></div>
                                </li>
                              )}
                            </ul>
                          </section>
                        )}
                      </div>
                    ) : (
                      <div className={`fin-grid${needsCompliance ? " is-three" : ""}`}>
                        <section className="finish-sec fin-pay" id="finish-pay">
                          <h4>How it is paid</h4>
                          <div className="seg fin-seg" role="radiogroup" aria-label="How this is paid for">
                            {PAY_CHOICES.map((c) => (
                              <button key={c.key} type="button" role="radio"
                                      aria-checked={payHow === c.key}
                                      className={payHow === c.key ? "on" : ""}
                                      onClick={() => choosePayHow(c.key)}>
                                {c.label}
                              </button>
                            ))}
                          </div>
                          <p className="fin-hint">{PAY_CHOICES.find((c) => c.key === payHow)?.hint}</p>

                          {payHow === "till" && (
                            <div className="fin-panel">
                              <Receipt size={18} />
                              <span>
                                An invoice for <b>{money(dueNow)}</b> is raised now and waits at the
                                till, where the patient settles it.
                              </span>
                            </div>
                          )}

                          {payHow === "now" && (
                            <div className="fin-panel is-form">
                              <Tenders
                                lines={tenders}
                                onChange={setTenders}
                                owed={dueNow}
                                allowAid={false}
                                {...currencyWorld(currencyState)}
                              />
                              <p className="fin-note">
                                The patient&rsquo;s share only. The claim is raised by the dispensing
                                itself, so the scheme&rsquo;s part is never collected here.
                              </p>
                            </div>
                          )}

                          {payHow === "aid" && (
                            <div className="fin-panel is-form fin-aid" id="finish-aid">
                              <div className="fin-aid-card">
                                <div className="field">
                                  <label htmlFor="aid-scheme">Scheme</label>
                                  <Select
                                    id="aid-scheme" ariaLabel="Scheme"
                                    value={String(aidScheme)}
                                    onChange={(v) => setAidScheme(v === "" ? "" : Number(v))}
                                    options={[
                                      { value: "", label: schemes.length ? "Choose the scheme…" : "Loading schemes…" },
                                      ...schemes.map((m) => ({ value: String(m.id), label: m.name })),
                                    ]}
                                  />
                                </div>
                                <div className="field">
                                  <label htmlFor="aid-member">Member no.</label>
                                  <input id="aid-member" value={aidMember} maxLength={40}
                                         placeholder="From the card"
                                         onChange={(e) => setAidMember(e.target.value)} />
                                </div>
                                <div className="field fin-aid-dep">
                                  <label htmlFor="aid-dep">Dep.</label>
                                  <input id="aid-dep" value={aidDep} maxLength={10} placeholder="00"
                                         title="Dependant code. 00 for the principal member"
                                         onChange={(e) => setAidDep(e.target.value)} />
                                </div>
                              </div>
                              <div className="fin-aid-row">
                              <div className="seg fin-aid-when" role="radiogroup" aria-label="When the claim is sent">
                                <button type="button" role="radio" aria-checked={!aidHold}
                                        className={!aidHold ? "on" : ""} onClick={() => setAidHold(false)}>
                                  Claim now
                                </button>
                                <button type="button" role="radio" aria-checked={aidHold}
                                        className={aidHold ? "on" : ""} onClick={() => setAidHold(true)}>
                                  Hold the claim
                                </button>
                              </div>
                              {aidHold && (
                                <input id="aid-hold-reason" className="fin-aid-reason" value={aidHoldReason}
                                       maxLength={200}
                                       placeholder="Why. Scheme offline, authorisation pending, card not here…"
                                       aria-label="Why the claim is held"
                                       onChange={(e) => setAidHoldReason(e.target.value)} />
                              )}
                              </div>
                              {/* What the funder will actually be sent.
                                  The claim is adjudicated on the code, not the
                                  name: a line with none is rejected, and the
                                  pharmacy learns that weeks later in a
                                  remittance. This is the last moment anybody
                                  can do anything about it, so it is said here
                                  rather than discovered there. It does not
                                  block. A pharmacy may well claim anyway and
                                  chase the code afterwards. */}
                              {aidScheme !== "" && items.length > 0 && (
                                <div className="fin-panel fin-codes">
                                  <h4>
                                    What {schemeName} will be billed
                                    {(() => {
                                      const short = items.filter(
                                        (i) => schemeCodes[i.product.id]?.origin === "none").length;
                                      return short ? (
                                        <span className="badge warn">
                                          {short} line{short === 1 ? "" : "s"} it cannot identify
                                        </span>
                                      ) : null;
                                    })()}
                                  </h4>
                                  <ul className="fin-code-list">
                                    {items.map((i, at) => (
                                      <li key={i.product.id}>
                                        <SchemeCodeField
                                          compact
                                          medicalAidId={Number(aidScheme)}
                                          scheme={schemeName}
                                          productId={i.product.id}
                                          productName={i.product.name}
                                          known={schemeCodes[i.product.id]}
                                          onSaved={reloadSchemeCodes}
                                        />
                                        <span className="fin-code-name">
                                          {i.product.name} {i.product.strength}
                                        </span>
                                        <span className="fin-code-qty">×{i.quantity}</span>
                                        <span className="fin-code-money">
                                          {money(lineEach(i) * (i.quantity || 0))}
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                  <p className="fin-note">
                                    A code typed here is kept against the medicine, so the
                                    next script carrying it is already right.
                                  </p>
                                </div>
                              )}
                              {patient && aidScheme !== "" && aidMember.trim()
                                && (patient.medical_aid_id !== aidScheme
                                  || (patient.medical_aid_number ?? "") !== aidMember.trim()) && (
                                <p className="fin-note fin-aid-record">
                                  {patient.medical_aid_id
                                    ? "Differs from the patient's record, which is updated to this card."
                                    : "Saved to the patient's record when dispensed."}
                                </p>
                              )}
                              {dueNow > 0.005 ? (
                                <Tenders
                                  lines={tenders}
                                  onChange={setTenders}
                                  owed={dueNow}
                                  allowAid={false}
                                  {...currencyWorld(currencyState)}
                                />
                              ) : (
                                <p className="fin-note">
                                  Fully covered. Nothing to collect from the patient.
                                </p>
                              )}
                            </div>
                          )}

                          {payHow === "delivery" && (
                            <div className="fin-panel is-form" id="step-delivery">
                              <div className="field">
                                <label>Driver</label>
                                <Select
                                  value={String(driverId ?? "")}
                                  onChange={(v) => setDriverId(v === "" ? "" : Number(v))}
                                  options={[
                                    { value: "", label: "Choose a driver…" },
                                    ...drivers.filter((d) => d.active).map((d) => ({
                                      value: String(d.id),
                                      // What they already carry, where they are chosen.
                                      label: d.full_name
                                        + (d.cash_holding ? `. Holding ${money(d.cash_holding)}` : "")
                                        + (d.over_cod_limit ? " · over limit" : "")
                                        + (d.licence_expired ? " · licence expired" : ""),
                                    })),
                                  ]}
                                />
                                <button type="button" className="linkish fin-field-link"
                                        onClick={() => setAddingDriver(true)}>
                                  {drivers.filter((d) => d.active).length === 0
                                    ? "No driver on file yet. Add one"
                                    : "Add a driver"}
                                </button>
                              </div>
                              <div className="field">
                                <label>Fee</label>
                                <input type="number" step="0.01" value={deliveryFee}
                                       placeholder="0.00"
                                       onChange={(e) => setDeliveryFee(e.target.value)} />
                              </div>
                              <div className="field">
                                <label>Deliver to</label>
                                <input value={deliverTo}
                                       placeholder="Street, suburb, and anything the driver needs"
                                       onChange={(e) => setDeliverTo(e.target.value)} />
                              </div>
                              <p className="fin-note">
                                The driver collects <b>{money(dueNow + fee)}</b> at the door and holds
                                it until they hand it in; the sale settles then.
                              </p>
                              {(() => {
                                const d = drivers.find((x) => x.id === driverId);
                                if (!d) return null;
                                if (d.licence_expired) {
                                  return (
                                    <p className="fin-note is-bad">
                                      <Warning size={13} weight="fill" />
                                      <span>{d.full_name}&rsquo;s licence has expired. Dispatch will be refused.</span>
                                    </p>
                                  );
                                }
                                if (d.over_cod_limit) {
                                  return (
                                    <p className="fin-note is-warn">
                                      <Warning size={13} weight="fill" />
                                      <span>
                                        {d.full_name} already carries {money(d.cash_holding ?? 0)} against a
                                        limit of {money(d.cod_limit ?? 0)}. Dispatch will be refused until it
                                        is handed in.
                                      </span>
                                    </p>
                                  );
                                }
                                return null;
                              })()}
                            </div>
                          )}

                          {/* What the patient was told, as it is handed over.
                              The points, not a box to type "counselled" into:
                              a box records that a key was pressed, the points
                              record what was said. Chips, so it costs one row
                              in a dialog that must not scroll. */}
                          <div className={`fin-counsel${counsellingMissing ? " is-needed" : ""}`}
                               id="finish-counselling">
                            <div className="fin-counsel-head">
                              <h4>Counselling</h4>
                              <span className="fin-counsel-state">
                                {counselPoints.length
                                  ? `${counselPoints.length} covered`
                                  : counsellingRequired ? "Required" : "Optional"}
                              </span>
                            </div>
                            <div className="fin-counsel-points" role="group"
                                 aria-label="Points the patient was told">
                              {COUNSELLING_POINTS.map((p) => {
                                const on = counselPoints.includes(p.key);
                                return (
                                  <button key={p.key} type="button" role="checkbox" aria-checked={on}
                                          className={`fin-chip${on ? " is-on" : ""}`}
                                          onClick={() => setCounselPoints((cur) =>
                                            on ? cur.filter((k) => k !== p.key) : [...cur, p.key])}>
                                    {on && <Check size={11} weight="bold" />}
                                    {p.short}
                                  </button>
                                );
                              })}
                            </div>
                            <input id="finish-counsel-notes" className="fin-counsel-notes"
                                   value={counselNotes} maxLength={500}
                                   onChange={(e) => setCounselNotes(e.target.value)}
                                   placeholder="Anything else they were told"
                                   aria-label="Counselling notes" />
                          </div>
                        </section>

                        <aside className="fin-side">
                          <section className="finish-sec fin-bill">
                            <h4>The bill</h4>
                            <dl className="ed-facts fin-facts">
                              <dt>Lines</dt><dd>{items.length}</dd>
                              <dt>Gross</dt><dd>{pricing || split ? money(gross) : <span className="skel" style={{ width: 56 }} />}</dd>
                              {schemeCarries && (
                                <><dt>{split!.scheme || "Scheme"} pays</dt><dd>{money(split.scheme_pays)}</dd></>
                              )}
                              {fee > 0 && (<><dt>Delivery</dt><dd>{money(fee)}</dd></>)}
                            </dl>
                            <div className="fin-due">
                              <span>{schemeCarries ? TERMS.shortfall : "Patient pays"}</span>
                              <b>{pricing || split ? money(dueNow + fee) : <span className="skel skel-num is-big" />}</b>
                              <small>
                                {payHow === "till" ? "at the till"
                                  : payHow === "now" || payHow === "aid" ? "here, now"
                                    : "to the driver, at the door"}
                              </small>
                            </div>
                            {claimHeld && (
                              <p className="fin-note">
                                The claim is held, so nothing is on {split?.scheme || "the scheme"} yet:
                                the patient pays in full and is refunded when it pays.
                              </p>
                            )}
                            {schemeCarries && (
                              <p className="fin-note">
                                Estimated on {split.scheme || "the scheme"}&rsquo;s terms; the
                                claim&rsquo;s adjudication settles it.
                              </p>
                            )}
                            {split && !split.covered && split.why && (
                              <p className="fin-note is-warn">
                                <Warning size={13} weight="fill" /><span>{split.why}</span>
                              </p>
                            )}
                          </section>

                          {/* What prints on dispense, as switches. Each says where
                              it goes; the defaults follow the script, and one
                              press changes one. */}
                          <section className="finish-sec fin-prints" aria-label="What prints on dispense">
                            <h4>
                              Prints on dispense
                              <span className="fin-prints-count">
                                {roll.DOC_KINDS.filter((d) => willPrint(d.kind)).length} of {roll.DOC_KINDS.length}
                              </span>
                            </h4>
                            <div className="fin-print-grid">
                              {roll.DOC_KINDS.map((d) => {
                                const on = willPrint(d.kind);
                                const Icon = d.kind === "label" ? Sticker : d.kind === "claim" ? FileText
                                  : d.kind === "delivery" ? Truck
                                  : d.kind === "barcode" ? Barcode
                                  : d.kind === "receipt" ? Receipt : Tag;
                                const where = roll.goesStraightToPrinter(d.kind)
                                  ? (roll.printerFor(d.kind) || "Label printer")
                                  : d.paper === "page" ? "Opens as a PDF" : "Print dialog";
                                // One word each. Five tiles across a dialog that
                                // may not grow, and the icon and tooltip say the
                                // rest.
                                const short = d.kind === "label" ? "Labels" : d.kind === "claim" ? "Claim"
                                  : d.kind === "delivery" ? "Delivery"
                                  : d.kind === "barcode" ? "Barcode"
                                  : d.kind === "receipt" ? "Receipt" : "Price";
                                return (
                                  <button key={d.kind} type="button" role="switch" aria-checked={on}
                                          className={`fin-print is-${d.kind}${on ? " is-on" : ""}`}
                                          title={`${d.hint} ${on ? "Prints" : "Does not print"} · ${where}`}
                                          onClick={() => setPrintPick((p) => ({ ...p, [d.kind]: !on }))}>
                                    <span className="fin-print-icon"><Icon size={16} weight={on ? "fill" : "regular"} /></span>
                                    {/* The name only. Where it comes out is on
                                        the control: five documents each carrying
                                        a second line of small print is two rows
                                        of dialog height spent saying "Print
                                        dialog" five times. */}
                                    <span className="fin-print-name">{short}</span>
                                    <span className="fin-print-tick" aria-hidden="true">
                                      {on && <Check size={10} weight="bold" />}
                                    </span>
                                  </button>
                                );
                              })}
                            </div>
                            {/* Why the defaults are what they are, in a line. */}
                            <p className="fin-note">
                              {[
                                "Labels always, each carrying the script barcode",
                                printPick.claim === undefined && printDefault("claim")
                                  ? `claim copy because ${split?.scheme || "the scheme"} pays` : "",
                                printPick.delivery === undefined && printDefault("delivery")
                                  ? "delivery label because it goes with a driver" : "",
                                printPick.receipt === undefined && printDefault("receipt")
                                  ? "a receipt because the money is taken here" : "",
                              ].filter(Boolean).join(" · ")}.
                              {/* Whether the receipt names the medicines on it.
                                  Asked here because here is before it prints, and
                                  because the patient who needs it discreet is the
                                  one who will not ask in front of a queue. Kept on
                                  the sale, so a receipt printed later at the till
                                  honours it too. It rides this line rather than
                                  taking a row: on a controlled script being
                                  claimed, a row of its own is what pushes this
                                  dialog past the height of a short screen. */}
                              {willPrint("receipt") && (
                                <span className="fin-privacy">
                                  <span className="seg" role="radiogroup"
                                        aria-label="What the receipt shows">
                                    <button type="button" role="radio" aria-checked={!receiptPrivate}
                                            className={!receiptPrivate ? "on" : ""}
                                            title="Each medicine by name, quantity and price."
                                            onClick={() => setReceiptPrivate(false)}>
                                      Itemised
                                    </button>
                                    <button type="button" role="radio" aria-checked={receiptPrivate}
                                            className={receiptPrivate ? "on" : ""}
                                            title={"Totals, tax and the invoice number only. No medicine "
                                              + "is named on the slip. For a patient who would rather "
                                              + "the queue did not read it."}
                                            onClick={() => setReceiptPrivate(true)}>
                                      <EyeSlash size={12} /> Private
                                    </button>
                                  </span>
                                </span>
                              )}
                            </p>
                          </section>
                        </aside>
                          {needsCompliance && (
                            <section className="finish-sec fin-compliance" id="finish-compliance">
                              <h4>
                                Compliance record
                                {activePolicy && <span className="badge danger">{activePolicy.label}</span>}
                              </h4>
                              {/* Each tick is one the server will ask for, and only
                                  those: the pack decides what this schedule needs. */}
                              {needsScriptSighted && (
                                <Checkbox checked={scriptSighted} onChange={setScriptSighted}>Original prescription sighted and retained</Checkbox>
                              )}
                              {needsPrescriberVerified && (
                                <Checkbox checked={prescriberVerified} onChange={setPrescriberVerified}>Prescriber and practice number verified</Checkbox>
                              )}
                              {needsIdVerified && (
                                <Checkbox checked={idVerified} onChange={setIdVerified}>Patient identity document verified</Checkbox>
                              )}
                              <div className="field">
                                <label>ID sighted</label>
                                <input value={idNumber} onChange={(e) => setIdNumber(e.target.value)}
                                       placeholder="As per identity document" />
                              </div>
                              <div className="field">
                                <label>Notes</label>
                                <textarea rows={2} value={complianceNotes}
                                  onChange={(e) => setComplianceNotes(e.target.value)}
                                  placeholder={`e.g. Filed in the ${schedCode(6)} register folder, ref 2026/044`} />
                              </div>
                            </section>
                          )}
                      </div>
                    )}

                    {stage === "settle" ? (
                      <div className="finish-foot">
                        {held && (
                          <p className="disp-blocked">
                            <Warning size={14} weight="fill" /><span>{held}</span>
                          </p>
                        )}
                        <span className="finish-spacer" />
                        <button type="button" className="btn secondary" onClick={() => setFinishing(null)}>
                          Back to the script
                        </button>
                        <button type="button" className="btn primary fin-proceed"
                                disabled={!!held} onClick={proceedToPay}>
                          Proceed to payment <ArrowRight size={14} weight="bold" />
                        </button>
                      </div>
                    ) : (
                      <div className="finish-foot">
                        {needsInitials && (
                          <div className={`lane-field finish-initials${initials.trim() ? " is-signed" : ""}`}>
                            <input id="finish-initials" value={initials} maxLength={8}
                              aria-label="Checked by: the initials of the pharmacist who checked this dispensing"
                              title={INITIALS_TITLE}
                              placeholder={initialsFocus === "finish" ? INITIALS_HINT : "Checked by"}
                              onFocus={() => setInitialsFocus("finish")}
                              onBlur={() => setInitialsFocus(null)}
                              onChange={(e) => setInitials(e.target.value.toUpperCase())} />
                            {initials.trim()
                              ? <Check className="lane-icon" size={14} weight="bold" aria-hidden="true" />
                              : <Signature className="lane-icon" size={15} aria-hidden="true" />}
                          </div>
                        )}
                        {why && (
                          <p className="disp-blocked">
                            <Warning size={14} weight="fill" /><span>{why}</span>
                          </p>
                        )}
                        <span className="finish-spacer" />
                        <button type="button" className="btn secondary" onClick={() => setFinishing(null)}>
                          Back to the script
                        </button>
                        {/* One press: dispense, and print what is lit above. And it
                            says how many, so what comes off the printers is never a
                            surprise. */}
                        <button type="button" className="btn primary fin-dispense"
                                disabled={busy || printing || !!why || !complianceReady}
                                title="Dispense, and print what is switched on (F12)"
                                onClick={createAndDispense}>
                          <span className="fin-dispense-main">
                            {busy || printing ? "Working…"
                              : `Dispense ${items.length} item${items.length === 1 ? "" : "s"}`}
                          </span>
                          <span className="fin-dispense-sub">
                            {(() => {
                              const n = roll.DOC_KINDS.filter((d) => willPrint(d.kind)).length;
                              return n ? `and print ${n}` : "print nothing";
                            })()}
                          </span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* A prescriber who is not on file yet, written down at the counter
                where the script is being captured. Both numbers are asked for
                because a funder pays on them; neither is demanded, because a
                pharmacy holding a paper script cannot invent one it was not
                given, and a script with no prescriber at all is worse. */}
            {newDoctor && (
              <div className="modal-backdrop" role="dialog" aria-modal="true"
                   aria-labelledby="new-doc-title" onClick={() => setNewDoctor(null)}>
                <div className="modal disp-doctor-modal" onClick={(e) => e.stopPropagation()}>
                  <h2 id="new-doc-title">Add a prescriber</h2>
                  <p className="muted">
                    They go on file for this script and every one after it. The numbers can
                    be filled in later from the prescriber&rsquo;s own page.
                  </p>
                  <div className="field">
                    <label htmlFor="new-doc-name">Name</label>
                    <input id="new-doc-name" value={newDoctor.name} maxLength={120} autoFocus
                           placeholder="As it appears on the script"
                           onChange={(e) => setNewDoctor({ ...newDoctor, name: e.target.value })} />
                  </div>
                  <div className="disp-doctor-nums">
                    <div className="field">
                      <label htmlFor="new-doc-practice">Practice number</label>
                      <input id="new-doc-practice" value={newDoctor.practice_number} maxLength={30}
                             placeholder="From their stationery"
                             onChange={(e) => setNewDoctor({ ...newDoctor, practice_number: e.target.value })} />
                    </div>
                    <div className="field">
                      <label htmlFor="new-doc-ahfoz">AHFoZ number</label>
                      <input id="new-doc-ahfoz" value={newDoctor.ahfoz_number} maxLength={40}
                             placeholder="What the funder pays on"
                             onChange={(e) => setNewDoctor({ ...newDoctor, ahfoz_number: e.target.value })} />
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="new-doc-phone">Phone</label>
                    <input id="new-doc-phone" value={newDoctor.phone} maxLength={30}
                           placeholder="For queries about their scripts"
                           onChange={(e) => setNewDoctor({ ...newDoctor, phone: e.target.value })} />
                  </div>
                  {!newDoctor.ahfoz_number.trim() && (
                    <p className="fin-note is-warn">
                      <Warning size={13} weight="fill" />
                      <span>
                        Without an AHFoZ number a claim for this script may come back
                        unpaid. Add it when you have it.
                      </span>
                    </p>
                  )}
                  <div className="modal-actions">
                    <button type="button" className="btn ghost" onClick={() => setNewDoctor(null)}>
                      Never mind
                    </button>
                    <BusyButton className="btn primary" busyLabel="Saving…"
                                disabled={newDoctor.name.trim().length < 2} onClick={saveDoctor}>
                      Add prescriber
                    </BusyButton>
                  </div>
                </div>
              </div>
            )}

            {unknownCode && (
              <AttachBarcode
                code={unknownCode}
                route=""
                onClose={() => setUnknownCode("")}
                onAttached={(product) => {
                  // Straight onto the script, as though it had been recognised:
                  // that is what the dispenser was doing when they scanned it.
                  void scanPack(unknownCode);
                }}
              />
            )}

            {/* The step-up prompt used to be rendered here. It is now at the
                foot of the component, because this subtree belongs to the
                prescription route and does not exist on the counter. See
                there. */}

            {/* Setting a price: the figure or the margin, and whether it
                outlives this script. Asked before the code, because a code
                typed before anybody has said what they want is a code typed
                for nothing. */}
            {pricingLine !== null && items[pricingLine] && (() => {
              const at = pricingLine;
              const line = items[at];
              return (
                <SetThePrice
                  name={line.product.name}
                  strength={line.product.strength}
                  quantity={line.quantity}
                  shelf={perUnit(line.product)}
                  cost={(line.product.cost_price ?? 0)
                    / Math.max(1, line.product.units_per_pack ?? 1)}
                  current={lineEach(line)}
                  busy={authorisingPrice === line.product.id}
                  onCancel={() => setPricingLine(null)}
                  onSet={(asked) => { setPricingLine(null); void setLinePrice(at, asked); }}
                />
              );
            })()}

            {cameraOpen && (
              <ScanCamera
                title="Scan the pack"
                onClose={() => setCameraOpen(false)}
                onScan={(code) => { setCameraOpen(false); void scanPack(code); }}
              />
            )}

            {/* Made up at the counter: the ingredients come off stock, and what
                comes back is an ordinary line on this script. */}
            <MixAtTheCounter
              open={mixing}
              onClose={() => setMixing(false)}
              onMade={(made: MadeUp) => {
                addItem({
                  id: made.product_id, name: made.name, strength: "",
                  dosage_form: "", schedule: made.schedule,
                  unit_price: made.unit_price, quantity_on_hand: made.quantity,
                } as any);
                // The directions it was made up with, and how much of it there
                // is: both were typed a moment ago and neither should be typed
                // again.
                window.setTimeout(() => {
                  setItems((current) => current.map((it) => (
                    it.product.id === made.product_id
                      ? { ...it, quantity: made.quantity,
                          dosage_instructions: made.directions || it.dosage_instructions }
                      : it)));
                }, 0);
              }}
            />

            {/* Cancelling a saved script: why, in a word or a sentence, and what
                happens. Said before the button, not discovered after it. */}
            {cancelTarget && (
              <div className="modal-backdrop" role="dialog" aria-modal="true"
                   aria-labelledby="cancel-title" onClick={() => setCancelTarget(null)}>
                <div className="modal disp-cancel-modal" onClick={(e) => e.stopPropagation()}>
                  <h2 id="cancel-title">Cancel {cancelTarget.number}</h2>
                  {/* Which script, in words. From the worklist it has not been
                      opened, and a row is one line of it. */}
                  {(cancelTarget.patient || cancelTarget.lines) && (
                    <p className="cancel-which">
                      {cancelTarget.patient && <b>{cancelTarget.patient}</b>}
                      {cancelTarget.product && <> · {cancelTarget.product}</>}
                      {cancelTarget.lines && cancelTarget.lines > 1 && (
                        <> · the whole script, all {cancelTarget.lines} lines</>
                      )}
                    </p>
                  )}
                  <p className="muted">
                    It comes off the worklist and can&rsquo;t be dispensed. Nothing on it has
                    gone out, so no stock, sale or claim is touched. The reason is kept on
                    the script&rsquo;s history.
                  </p>
                  <div className="cancel-reasons" role="group" aria-label="Common reasons">
                    {["Captured twice by mistake", "Patient no longer wants it",
                      "Prescriber changed the script"].map((r) => (
                      <button key={r} type="button"
                              className={`hold-reason${cancelReason === r ? " is-on" : ""}`}
                              onClick={() => setCancelReason(r)}>
                        {r}
                      </button>
                    ))}
                  </div>
                  <div className="field">
                    <label htmlFor="cancel-reason">Why it is being cancelled</label>
                    <input id="cancel-reason" value={cancelReason} maxLength={240} autoFocus
                           onChange={(e) => setCancelReason(e.target.value)}
                           placeholder="Pick one above, or say it in your own words" />
                  </div>
                  <div className="modal-actions">
                    <button type="button" className="btn ghost" onClick={() => setCancelTarget(null)}>
                      Keep the script
                    </button>
                    <BusyButton className="btn danger" busyLabel="Cancelling…"
                                disabled={cancelReason.trim().length < 3} onClick={cancelScript}>
                      Cancel script
                    </BusyButton>
                  </div>
                </div>
              </div>
            )}

            {/* Putting a script on hold: why, and a note. Short on purpose. The
                person holding it has just found a problem and is at the counter. */}
            {holding && fromRx && (
              <div className="modal-backdrop" role="dialog" aria-modal="true"
                   aria-labelledby="hold-title" onClick={() => setHolding(false)}>
                <div className="modal disp-hold-modal" onClick={(e) => e.stopPropagation()}>
                  <h2 id="hold-title">Hold {fromRx.number}</h2>
                  <p className="muted">
                    It stays on the worklist, marked, and can&rsquo;t be dispensed until a
                    pharmacist or a manager releases it.
                  </p>
                  <div className="hold-reasons" role="radiogroup" aria-label="Why it is being held">
                    {holdReasons.map((r) => (
                      <button key={r.code} type="button" role="radio"
                              aria-checked={holdReason === r.code}
                              className={`hold-reason${holdReason === r.code ? " is-on" : ""}`}
                              onClick={() => setHoldReason(r.code)}>
                        {r.label}
                      </button>
                    ))}
                  </div>
                  <div className="field">
                    <label htmlFor="hold-note">Note</label>
                    <input id="hold-note" value={holdNote} maxLength={300}
                           onChange={(e) => setHoldNote(e.target.value)}
                           placeholder="e.g. Calling Dr Moyo about the dose" />
                  </div>
                  <div className="modal-actions">
                    <button type="button" className="btn ghost" onClick={() => setHolding(false)}>
                      Cancel
                    </button>
                    <BusyButton className="btn primary" busyLabel="Holding…"
                                disabled={!holdReason} onClick={placeHold}>
                      Put on hold
                    </BusyButton>
                  </div>
                </div>
              </div>
            )}

            {/* A line's check, opened from its shield. */}
            {checking !== null && (() => {
              const idx = items.findIndex((i) => i.product.id === checking);
              if (idx < 0) return null;
              const it = items[idx];
              const c = lineChecks[it.product.id];
              const current = !!c && c.sig === basketSig;
              return (
                <LineCheckModal
                  name={lineName(it.product)}
                  schedule={it.product.schedule || 0}
                  loading={!current || c!.status === "loading"}
                  screen={current ? c!.screen ?? null : null}
                  error={current ? c!.error : undefined}
                  coverage={coverageFor(it.product.id)}
                  otherLines={items.length - 1}
                  hasPatient={!!patient}
                  ai={aiCheck}
                  aiShown={aiShown}
                  onAskAi={aiCheck.streaming ? aiCheck.stop : checkInteractions}
                  onRecheck={() => runLineCheck(it)}
                  onEdit={() => { setChecking(null); setOpenItem(idx); setEditing(idx); }}
                  onClose={() => setChecking(null)}
                />
              );
            })()}

            {/* The full text of a truncated cell. */}
            {tip && (
              <div className={`cell-tip${tip.below ? " is-below" : ""}`} role="tooltip"
                   style={{ left: tip.x, top: tip.below ? tip.y + 34 : tip.y - 6 }}>
                <span>{tip.text}</span>
                {tip.sub && <small>{tip.sub}</small>}
              </div>
            )}

            {/* The patient box's history and details. */}
            {laneOpen === "history" && patient && (
              <PatientHistoryModal patient={patient} onClose={() => setLaneOpen(null)} />
            )}
            {laneOpen === "details" && patient && (
              <PatientCardModal patient={patient} canLeave={items.length === 0}
                                onClose={() => setLaneOpen(null)} />
            )}

            {/* What a lane chip stands for, in full. */}
            {(laneOpen === "repeats" || laneOpen === "insurance") && patient && (
              <div className="modal-backdrop" role="dialog" aria-modal="true"
                   aria-label={laneOpen === "repeats" ? "Repeats due" : "Medical aid standing"}
                   onClick={(e) => { if (e.target === e.currentTarget) setLaneOpen(null); }}>
                <div className="modal disp-lane-modal">
                  <h2>
                    {laneOpen === "repeats" ? "Repeats due" : "Medical aid standing"}
                    <span className="disp-entry-of">{patient.first_name} {patient.last_name}</span>
                  </h2>
                  {laneOpen === "repeats" ? (
                    <RepeatsDue patientId={patient.id} skeleton
                                alreadyOn={items.map((i) => i.product.id)}
                                onAdd={addDueRepeat} />
                  ) : (
                    <InsuranceStanding patientId={patient.id} skeleton />
                  )}
                  <div className="disp-edit-actions">
                    <span className="finish-spacer" />
                    <button type="button" className="btn primary" onClick={() => setLaneOpen(null)}>
                      Done
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* The third column is gone.
              It held three unrelated things because there was space for them: a
              second repeats list that asked the same question as the worklist
              and answered it differently (53 against 0, from a 14-day horizon
              against a 7-day one), a recent-scripts list whose "See all" linked
              to a route that does not exist, and a page of schedule rules.
              Reference material occupying a third of a console.

              None of it was actionable. Its one button posted a dispensing
              without the checking pharmacist's initials, which the server
              requires, so it returned 400 every single time it was pressed.

              Repeats now live in the worklist, which is where "what needs doing"
              already lived, and clicking one loads it into the form on the left
. Through the safety check, where the initials are captured. */}
        </div>

      {/* THE REGISTER LIVES ON ITS OWN SCREEN.
          A ninety-day copy of the dangerous drugs register used to sit here
          and take the whole middle of the tab, pushing the three steps this
          screen exists for into a strip at the top. It was also the lesser of
          two: Controlled Register in the sidebar is the same record with date
          ranges, a schedule filter, running balances and a printable document
          an inspector can be handed.

          Two screens showing one statutory record is one of them going stale.
          The link goes where the work is finished rather than duplicating it
          under the form. */}
      {needsCompliance && (
        <p className="muted small dd-register-link">
          Every hand-over is entered in the register as it is dispensed.{" "}
          <Link to="/register">Open the Controlled Register</Link> to read it,
          filter it by date or schedule, or print it.
        </p>
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

      {/* Correcting the shelf, from the search row or from the line editor.
          The new figure is written back into whatever is on screen — the search
          results and the basket both hold their own copy of the product — so
          nothing has to be looked up again and the dispenser carries on from
          where they were. */}
      {newMedicine && (
        <NewMedicine
          draft={newMedicine}
          onClose={() => setNewMedicine(null)}
          // Straight onto the script that is already open, which is the whole
          // point of adding it from here.
          onAdded={(product) => { setProductQ(""); setProductResults([]); addItem(product); }}
          onRefused={(draft) => setNewMedicine(draft)}
        />
      )}

      {adjusting && (
        <AdjustStock
          product={adjusting}
          // Which script was on screen. A correction made while dispensing is
          // recorded against it, so the history can say so afterwards.
          prescriptionId={fromRx?.id ?? null}
          onClose={() => setAdjusting(null)}
          onAdjusted={(onHand) => {
            const id = adjusting.id;
            const put = (p: Product): Product =>
              p.id === id ? { ...p, quantity_on_hand: onHand, here: onHand } : p;
            setProductResults((all) => all.map(put));
            setItems((all) => all.map((i) =>
              (i.product.id === id ? { ...i, product: put(i.product) } : i)));
          }}
        />
      )}

      <DispensaryWorklist
        reloadOn={worklistNonce}
        // Cancel straight from the queue, where the script is sitting — for
        // those who may; nobody else sees the control.
        leaving={cancelling}
        onCancel={mayCancelScript
          ? (row, lines) => openCancel({ id: row.prescription_id, number: row.rx_number,
                                         patient: row.patient, product: row.product, lines })
          : undefined}
        panel={worklistPanel}
        onPanelChange={setWorklistPanel}
        onPickRepeat={(row) => {
          // Load the repeat into the form rather than dispensing it behind the
          // dispenser's back. A repeat still needs a safety check and a
          // pharmacist's initials; the shortcut this replaces skipped both and
          // was rejected by the server for exactly that reason.
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
                      auto_refill: false, icd10_code: DEFAULT_DIAGNOSIS,
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
      {/* The function keys, along the foot of the window.

          They were at the bottom of the safety band, inside a region that
          scrolls. So the strip a dispenser looks down at was wherever the
          warnings had pushed it, or off the screen entirely. The system this
          competes with runs F1 to F12 across the bottom of the window and it
          does not move; a key strip that moves is one nobody learns.

          The numbers are theirs: Mix, WayBill, Auth, Repts, Hist, Finish. */}
      <KeyBar keys={hotkeys} />

      {/* THE PASSWORD PROMPT, AT THE TOP LEVEL, FOR EVERY ROUTE.
          It lived inside the prescription route's own subtree, which does not
          exist while the counter is open. So a counter sale that needed a
          supervisor asked the server, got its 428, and rendered the dialog
          into a tree nobody was looking at: the request simply hung with no
          way to answer it. Here it belongs to the screen rather than to one
          tab of it, and nothing that opens it unmounts while it is open, so
          whatever was being typed is still there afterwards. */}
      {stepUpPrompt}
    </div>
  );
}
