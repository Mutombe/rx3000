import { useEffect, useRef, useState } from "react";
import { useScheduleCodes } from "../schedules";
import { useToast } from "../components/Toast";
import { Hotkey, useHotkeys } from "../hooks/useHotkeys";
import { api, fmtDate, fmtDateTime, money, errorText, prefetchRoute, Refused } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { ScanBar, ScanResult } from "../components/Scanner";
import { useScanFeed } from "../components/ScannerHub";
import { useConnection } from "../components/Connection";
import * as queue from "../offline/queue";
import * as deviceAgent from "../deviceAgent";
import { printReceipt } from "../print";
import { usePharmacy } from "../hooks/usePharmacy";
import { CurrencyState, Patient, Product, Sale } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import MobileMoney from "../components/MobileMoney";
import { ClockCounterClockwise, Printer, Truck, Warning } from "@phosphor-icons/react";
import { KeyBar } from "../components/KeyMap";
import * as roll from "../shellPrinter";
import BusyButton from "../components/BusyButton";
import RowLink from "../components/RowLink";
import { Link, useSearchParams } from "react-router-dom";
import { EntityLink } from "../components/Filters";
import PartPayment, { PartPaymentChoice } from "../components/PartPayment";
import Tenders, { TenderLine, currencyWorld, inBase } from "../components/Tenders";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import SettleSale from "../components/SettleSale";
import { useDoing } from "../components/Doing";
import Th from "../components/Th";

type Tab = "till" | "pending" | "history";

const EMPTY_CARD = { auth: "", reference: "", last4: "", scheme: "", terminal: "" };

/* The local three-field TenderLine used to live here — method, currency,
   amount, which is why the till's own split panel could not say which wallet
   or which bank, while the part-payment modal beside it could. It is the
   shared one now: one definition, one set of questions, wherever money is
   taken. */

const round2 = (n: number) => Math.round(n * 100) / 100;

/** What a basket line charges for one unit: the hand-set price, or the shelf's.
 *  In one place, because four sites multiply a price by a quantity here and a
 *  price somebody got a code for, honoured in three of them, is a discount that
 *  reappears on the receipt. */
const lineEach = (l: CartLine) => l.price ?? l.product.unit_price;

interface CartLine {
  product: Product;
  quantity: number;
  /** A price set by hand at the counter, per unit. Undefined means "whatever
   *  the shelf says", which is almost every line. */
  price?: number;
  /** The authorisation behind it — the record written when a code was
   *  accepted. The sale quotes this id and never the figure. */
  priceOverrideId?: number;
}

export default function POS() {
  const sched = useScheduleCodes();
  const pharmacy = usePharmacy();
  const [scan, setScan] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [payMethod, setPayMethod] = useState("cash");
  const [tendered, setTendered] = useState("");
  const [redeem, setRedeem] = useState("0");
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const [pending, setPending] = useState<Sale[]>([]);
  const [history, setHistory] = useState<Sale[]>([]);
  const [historyQ, setHistoryQ] = useState("");
  /** The sale the dispensary sent over, so the till opens on it. */
  const [params, setParams] = useSearchParams();
  const settleId = Number(params.get("settle")) || 0;

  /* The three states this page can be in. Kept as a list so the tab lives in
     the address — a cashier who reloads mid-settlement lands back where they
     were — even though the page now switches with a button rather than a tab
     bar. */
  const TABS: TabDef<Tab>[] = [
    { key: "till", label: "Till" },
    { key: "pending", label: "Awaiting payment", count: pending.length },
    { key: "history", label: "History" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "till");
  const toast = useToast();
  // Scans from whichever scanner this workstation has, phone or wedge.
  useScanFeed("Till", (code, _format, source) => void fromPhone(code, source));
  const doing = useDoing();
  /* SALES BEING SETTLED RIGHT NOW.
     Held as a set of ids rather than a single "busy" flag, because the point
     of settling without waiting is that a cashier can take the money on three
     sales in a row while the first is still going. One flag would make the
     second press look like it did nothing. */
  const [settlingNow, setSettlingNow] = useState<Set<number>>(new Set());
  const markSettling = (id: number, on: boolean) =>
    setSettlingNow((all) => {
      const next = new Set(all);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  const { guarded, prompt: stepUpPrompt } = useStepUp();
  /** The sale a cashier is taking part of, if any. */
  const [partOf, setPartOf] = useState<Sale | null>(null);
  /** What this customer already owes from a previous visit. */
  const [owes, setOwes] = useState<{ balance: number; oldest: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [agent, setAgent] = useState<deviceAgent.AgentStatus | null>(null);
  const [terminalState, setTerminalState] = useState("");
  const [card, setCard] = useState(EMPTY_CARD);
  const [currencyState, setCurrencyState] = useState<CurrencyState | null>(null);
  const [splitMode, setSplitMode] = useState(false);
  const [tenderLines, setTenderLines] = useState<TenderLine[]>([{ method: "cash", currency_code: "", amount: "" }]);
  const [changeCurrency, setChangeCurrency] = useState("");
  const [mobilePhone, setMobilePhone] = useState("");
  /* Which wallet, and in which currency. EcoCash first because it is most of
     the traffic; the currency follows whatever that wallet can actually settle
     in, so the till never offers a combination that would be declined. */
  const [wallet, setWallet] = useState("ecocash");
  const [walletCurrency, setWalletCurrency] = useState("USD");
  const [walletReference, setWalletReference] = useState("");
  const [mobileState, setMobileState] = useState("");
  /** The basket line whose price is being typed, and what has been typed. */
  const [priceEdit, setPriceEdit] = useState<number | null>(null);
  const [priceDraft, setPriceDraft] = useState("");
  /** The line whose new price is being authorised. */
  const [tillPricing, setTillPricing] = useState<number | null>(null);
  const scanRef = useRef<HTMLInputElement>(null);
  const { online } = useConnection();

  useEffect(() => { loadPending(); }, []);
  // Optional hardware — absent agent simply means manual capture and browser printing
  useEffect(() => { deviceAgent.probe().then(setAgent); }, []);
  useEffect(() => {
    api.get<CurrencyState>("/api/currency").then((c) => {
      setCurrencyState(c);
      setChangeCurrency(c.base);
      setTenderLines([{ method: "cash", currency_code: c.base, amount: "" }]);
    }).catch((e) => toast.error(errorText(e,
      "The till could not read this pharmacy's currencies. Reload before "
      + "taking money, or the tender lines will be wrong.")));
  }, []);

  /* Two lists, two flags. The till's own tab is built from what the cashier
     is typing and has nothing to wait for; these two are fetched, and until
     now they rendered an empty table while the answer was in flight, which on
     the awaiting-payment tab reads as "nobody owes anything", the single most
     misleading thing this screen could say. */
  /** A waiting sale about to be settled, and the button that was pressed. */
  const [settling, setSettling] = useState<{ sale: Sale; method: string } | null>(null);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);

  /** Sales a driver is out with, keyed by sale id.
   *
   *  A sale on a driver's account looks exactly like one where the patient is
   *  standing at the counter, and taking payment for it collects money
   *  somebody else is also collecting: the patient pays twice, or the driver
   *  returns with cash for a sale the books already show as settled.
   *
   *  One request for the whole list rather than a lookup per row.
   */
  const [outWith, setOutWith] = useState<Record<string, {
    waybill_number: string; driver: string; driver_id: number | null;
    cod_amount: number; status: string;
  }>>({});

  function loadPending() {
    api.get<Sale[]>("/api/pos/sales?status=pending&limit=20")
      .then(setPending)
      .finally(() => setPendingLoading(false));
    api.get<typeof outWith>("/api/deliveries/out-sales")
      .then(setOutWith)
      // The list still renders. A delivery marker that cannot be fetched must
      // not stop a cashier settling the sales that are genuinely at the
      // counter.
      .catch(() => setOutWith({}));
  }

  function loadHistory() {
    setHistoryLoading(true);
    api.get<Sale[]>(`/api/pos/sales?status=paid&limit=50`
      + (historyQ ? `&q=${encodeURIComponent(historyQ)}` : ""))
      .then(setHistory).catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }

  useEffect(() => { if (tab === "history") loadHistory(); }, [tab, historyQ]);

  /* Arriving from the dispensary with a sale to settle.
   *
   *  The dispensary handed over with a bare link to /pos, which passed nothing:
   *  the cashier landed on an empty till and had to find the invoice by hand,
   *  with the patient standing there. The sale now travels in the address, the
   *  till opens on the list it is in, and the row says which one it is. */
  useEffect(() => {
    if (!settleId) return;
    setTab("pending");
    loadPending();
  }, [settleId]);

  useEffect(() => {
    if (scan.length < 2) { setResults([]); return; }
    // Only what a till may lawfully sell. This searched the whole catalogue,
    // so a cashier could find a prescription medicine, basket it and be
    // refused at the end, or before the server learned to refuse it, not be
    // refused at all. The sale is guarded server-side either way; this is what
    // keeps the medicine out of the basket in the first place.
    api.get<Product[]>(
      `/api/products?q=${encodeURIComponent(scan)}&limit=8&counter_only=true`)
      .then(setResults);
  }, [scan]);

  // What they owe, looked up when they are linked.
  //
  // Shown, never enforced. A debt is not a clinical reason to refuse somebody
  // their medicine, and a till that blocks a sale over one turns a cashier
  // into a debt collector at the moment they are least able to be one. The
  // figure is put in front of them and the decision stays theirs.
  useEffect(() => {
    if (!patient) { setOwes(null); return; }
    let dropped = false;
    api.get<{ items: { balance: number; created_at: string }[]; total_owed: number }>(
      `/api/pos/owed?patient_id=${patient.id}`)
      .then((d) => {
        if (dropped) return;
        setOwes(d.total_owed > 0.005
          ? { balance: d.total_owed,
              oldest: d.items[0]?.created_at ?? "" }
          : null);
      })
      .catch(() => { if (!dropped) setOwes(null); });
    return () => { dropped = true; };
  }, [patient]);

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`).then(setPatients);
  }, [patientQ]);

  /** A scan came back resolved. Warnings are already on screen as toasts. */
  /** A code that arrived from a phone rather than from the box in this page.
   *
   *  The phone sends a string; everything below here wants a resolved scan.
   *  So it is resolved the same way the scan box resolves one, through the
   *  same endpoint with the same context, and handed to the same function —
   *  which is why nothing downstream needs to know a phone was involved.
   */
  async function fromPhone(code: string, source?: string) {
    setScan("");
    try {
      const result = await api.post<ScanResult>(
        "/api/scan", { code, context: "pos", source });
      onScanned(result);
    } catch (e) {
      // Said out loud. A scan that vanishes is the complaint this whole
      // feature exists to answer.
      toast.error(errorText(e, "That scan could not be read."));
    }
  }

  function onScanned(result: ScanResult) {
    if (!result.found || !result.product) {
      // Exactly one candidate is not a guess, it is the answer.
      if (result.suggestions.length === 1) {
        api.get<Product>(`/api/products/${result.suggestions[0].id}`).then(addToCart);
      }
      return;
    }
    // The scan carries what the product page carries; the extra fields the cart
    // never reads are left off rather than fetched again for nothing.
    addToCart(result.product as unknown as Product, result.quantity_multiplier);
  }

  /** Settle a line the till added from its own catalogue, once the server
   *  has answered.
   *
   *  A scan against the hosted API takes over two seconds, so the basket
   *  cannot wait for it: the line goes in on the beep from the catalogue the
   *  browser already syncs. This is the other half of that bargain. Usually
   *  the server agrees and the only thing to settle is a pack size the
   *  catalogue could not know, because alternate barcodes — the outer carton
   *  that means a case of twelve — are not cached. Where it disagrees the
   *  line is taken out again and the right one put in, which is the whole
   *  reason an optimistic line has to be reversible.
   */
  function onCorrected({ was, applied, result, agreed }: {
    was: number; applied: number; result: ScanResult; agreed: boolean;
  }) {
    const real = Math.max(1, result.quantity_multiplier || 1);
    if (agreed) {
      if (real === applied) return;              // nothing to settle
      setCart((prev) => prev.map((l) => (l.product.id === was
        ? { ...l, quantity: l.quantity - applied + real } : l)));
      return;
    }
    // Wrong product, or no product. Remove exactly what was added: the line
    // if this scan put it there, a unit if it was already in the basket.
    setCart((prev) => prev.flatMap((l) => {
      if (l.product.id !== was) return [l];
      const left = l.quantity - applied;
      return left > 0 ? [{ ...l, quantity: left }] : [];
    }));
    if (result.found && result.product) {
      addToCart(result.product as unknown as Product, real);
    }
  }

  function addToCart(p: Product, units = 1) {
    // An outer carton scans as one code and means a case. `quantity_multiplier`
    // is where that pack size arrives.
    const step = Math.max(1, units);
    setCart((prev) => {
      const existing = prev.find((l) => l.product.id === p.id);
      if (existing) return prev.map((l) => (l.product.id === p.id ? { ...l, quantity: l.quantity + step } : l));
      return [...prev, { product: p, quantity: step }];
    });
    setScan("");
    setResults([]);
    scanRef.current?.focus();
  }

  const total = cart.reduce((s, l) => s + lineEach(l) * l.quantity, 0);
  const redeemValue = Math.min(Number(redeem) || 0, patient?.loyalty_points ?? 0);
  const payable = Math.max(0, total - redeemValue);

  const rateFor = (code: string) =>
    currencyState?.currencies.find((c) => c.code === code)?.rate ?? 0;

  // Each line is converted to base at its own rate; a line whose currency has
  // no rate on record contributes nothing rather than a wrong number. Through
  // the shared converter so the till and the modals cannot disagree about what
  // a ZiG line is worth.
  const world = currencyWorld(currencyState);
  const collectedInBase = round2(
    tenderLines.reduce((sum, line) => sum + inBase(line, world.rates, world.base), 0));
  const shortfall = Math.max(0, round2(payable - collectedInBase));
  const changeInBase = Math.max(0, round2(collectedInBase - payable));

  /* updateTender / addTender / removeTender used to live here. The shared
     Tenders component owns adding, removing and patching a line now, so three
     more copies of that logic in the one screen that already had the deepest
     version is exactly the duplication this change removes. */

  /** Card tender: drive the terminal when one is connected, otherwise use the
   *  slip detail the cashier keyed off a standalone machine. Either way the
   *  same fields land on the sale so it can be reconciled. */
  async function resolveCardTender(amount: number, reference: string) {
    if (agent?.terminal.ready) {
      setTerminalState("Waiting for the customer to tap or insert…");
      try {
        const res = await deviceAgent.takePayment(amount, reference);
        if (!res.approved) throw new Refused(res.message || "Card declined");
        setTerminalState("");
        return {
          card_auth_code: res.auth_code ?? "", card_reference: res.reference ?? "",
          card_last4: res.last4 ?? "", card_scheme: res.scheme ?? "",
          terminal_id: res.terminal_id ?? "", card_batch: res.batch ?? "",
        };
      } finally {
        setTerminalState("");
      }
    }
    return {
      card_auth_code: card.auth.trim(), card_reference: card.reference.trim(),
      card_last4: card.last4.trim(), card_scheme: card.scheme,
      terminal_id: card.terminal.trim(), card_batch: "",
    };
  }

  /** Mobile money is a push: send it, then wait for the customer to approve on
   *  their handset. Nothing is settled until the provider confirms. */
  async function resolveMobileTender(amount: number, reference: string) {
    // No gateway on this till: the customer paid on their handset and read the
    // code back, exactly as they do for a card slip off a standalone machine.
    //
    // This used to throw "No mobile money provider is configured on this till"
    // — after the screen had already asked for the confirmation code and
    // promised to keep it with the sale. The card path has always fallen back
    // to keyed slip detail; this one refused the sale outright, so a pharmacy
    // without an integration either rang wallet payments up as cash, which is a
    // hole nobody can close at cash-up, or could not sell at all.
    if (!agent?.mobile_money?.ready) {
      const code = walletReference.trim();
      if (!code) {
        throw new Refused(
          "Enter the confirmation code the customer read back, or take the payment another way.");
      }
      return code;
    }
    if (!mobilePhone.trim()) throw new Refused("Enter the customer's mobile number");
    setMobileState("Sending request to the customer's phone…");
    // The wallet the cashier chose, not a hardcoded one. Sending every payment
    // to EcoCash meant an Omari customer watched a prompt that never arrived.
    const started = await deviceAgent.initiateMobile(amount, mobilePhone.trim(), wallet, reference);
    if (!started.started || !started.poll_ref) {
      throw new Refused(started.message || "Could not start the mobile money request");
    }
    setMobileState(started.message ?? "Waiting for the customer to approve…");
    const result = await deviceAgent.awaitMobilePayment(started.poll_ref, {
      timeoutMs: (agent.mobile_money.timeout_seconds ?? 180) * 1000,
      onTick: (secs) => setMobileState(`Waiting for the customer to approve… ${secs}s`),
    });
    setMobileState("");
    if (result.state !== "paid") {
      throw new Refused(result.message || `Mobile money ${result.state}`);
    }
    return result.reference ?? "";
  }

  /** Lines the till can only sell from stock with no expiry recorded, and the
   *  date the cashier read off each pack.
   *
   *  A shop's opening count says how many boxes are on the shelf, never what is
   *  printed on them, so every batch it creates is undated — and undated stock
   *  cannot be sold, because First-Expiry-First-Out has no way to place it. The
   *  dispensary learned to ask the person holding the box; the till did not, and
   *  a pharmacy whose whole shelf had arrived that way could dispense a script
   *  and not sell a tube of cream.
   *
   *  Asked while the basket is being built rather than at Complete Sale, because
   *  the cashier is holding the box then and there is nobody waiting yet. The
   *  server writes the date onto the stock as the sale draws it, so the shelf
   *  dates itself one customer at a time and nobody is asked twice. */
  const [packNeeded, setPackNeeded] = useState<
    { product_id: number; name: string; needed_units: number;
      dated_units: number; undated_units: number }[]>([]);
  const [packExpiry, setPackExpiry] = useState<Record<number, string>>({});
  const basketKey = cart.map((l) => `${l.product.id}:${l.quantity}`).join(",");
  useEffect(() => {
    if (!cart.length) { setPackNeeded([]); return; }
    const t = window.setTimeout(() => {
      api.post<typeof packNeeded>("/api/pos/expiry-needed", {
        lines: cart.map((l) => ({ product_id: l.product.id, quantity: l.quantity })),
      }).then(setPackNeeded).catch(() => setPackNeeded([]));
    }, 200);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basketKey]);

  /** The first pack still needing a date, or one whose date has already gone. */
  function packProblem(): string {
    const today = new Date().toLocaleDateString("en-CA");
    const past = packNeeded.find((l) => packExpiry[l.product_id]
      && packExpiry[l.product_id] < today);
    if (past) return `That pack of ${past.name} has expired. Take another off the shelf.`;
    const missing = packNeeded.find((l) => !packExpiry[l.product_id]);
    if (missing) return `Enter the expiry printed on the pack of ${missing.name}.`;
    return "";
  }

  /* Keys at the till.
   *
   * A cashier's hands are on the scanner and the keypad, not the mouse, and a
   * queue forms in the seconds spent reaching for one. These deliberately do
   * not reuse the dispensary's F-keys: F3 means "mark line as cash" on a
   * script, and a cashier who learns it means something else here will
   * eventually press it on the wrong screen.
   */
  const hotkeys: Hotkey[] = [
    {
      combo: "F2",
      label: "Back to the scanner",
      group: "Till",
      run: () => scanRef.current?.focus(),
    },
    {
      combo: "F12",
      label: "Take payment",
      group: "Till",
      // Refused rather than silently ignored when there is nothing to sell:
      // a disabled key that does nothing feels like a broken keyboard.
      disabled: cart.length === 0,
      run: () => completeSale(),
    },
    {
      combo: "Escape",
      label: "Clear the sale",
      group: "Till",
      disabled: cart.length === 0 || busy,
      run: () => {
        // No confirm: a cashier clears a mis-scanned basket constantly, and a
        // dialog in that loop is worse than re-scanning three items.
        setCart([]);
        setScan("");
        scanRef.current?.focus();
        toast.ok("Sale cleared.");
      },
    },
  ];
  useHotkeys(hotkeys);

  /** Take the sale offline, into the queue.
   *
   *  Narrower than the online path on purpose. Everything refused here needs
   *  the server at the moment of sale and cannot be settled afterwards by
   *  replaying a record: a card has to be authorised by the acquirer, mobile
   *  money has to be confirmed by the customer's handset, a medical aid claim
   *  has to be adjudicated, and loyalty points have to be checked against a
   *  balance we cannot read. Accepting any of them offline would mean handing
   *  over goods against a payment that may never have happened.
   *
   *  Cash is the exception, because cash settles in the drawer rather than on a
   *  network, and that is the whole of what an offline till can honestly do.
   */
  async function checkoutOffline() {
    if (payMethod !== "cash" || splitMode) {
      toast.error(
        "Only cash can be taken while the server is unreachable. A card or "
        + "mobile payment has to be authorised at the time, and cannot be "
        + "settled later from a queued record.",
      );
      return;
    }
    if (patient && redeemValue > 0) {
      toast.error("Loyalty points cannot be redeemed offline. The balance cannot be checked.");
      return;
    }
    const schedules = cart.filter((l) => (l.product.schedule ?? 0) >= 5);
    if (schedules.length) {
      toast.error(
        `${schedules[0].product.name} is a schedule ${schedules[0].product.schedule} `
        + "item and cannot leave the counter without the register.",
      );
      return;
    }

    setBusy(true);
    try {
      const row = await queue.enqueue({
        patient_id: patient?.id ?? null,
        items: cart.map((l) => ({ product_id: l.product.id, quantity: l.quantity })),
        payment_method: "cash",
        amount_tendered: Number(tendered) || payable,
        loyalty_points_redeemed: 0,
        // Held with the sale. The dates were read off the boxes that went over
        // the counter tonight; when the line comes back the server still has to
        // be told them, or the replay is refused for stock with no expiry.
        pack_expiries: Object.fromEntries(
          packNeeded.filter((l) => packExpiry[l.product_id])
            .map((l) => [l.product_id, packExpiry[l.product_id]])),
      });
      const held = await queue.pendingCount();
      toast.ok(
        `Sale held on this till (${row.ref.slice(0, 12)}…): ${held} waiting to be `
        + "sent when the line is back. Give the customer their change and goods.",
      );
      setCart([]); setPatient(null); setTendered(""); setRedeem("0");
      scanRef.current?.focus();
    } catch (e: any) {
      // The one failure that must never be quiet: if it did not reach the
      // queue, the sale exists nowhere at all.
      toast.error(
        "This sale could not be saved on the till, so it has NOT been recorded. "
        + "Write it down before continuing. " + (e?.message || ""),
      );
    } finally {
      setBusy(false);
    }
  }

  /** Take the money, and let the next customer start while it is being taken.
   *
   *  A till is a queue. The old flow held the screen — button disabled, basket
   *  frozen, cashier watching a spinner — for as long as a hosted database in
   *  another city took to write a sale, its lines, its tenders and its stock
   *  movements. At a counter with four people in it that is the whole cost of
   *  the software.
   *
   *  So the basket clears on the keystroke and the sale goes into the tray: it
   *  is named while it runs, it says what happened when it lands, and the
   *  receipt prints by itself. A refusal hands the basket back exactly as it
   *  was — every line, the customer, the tender — with the reason and a Try
   *  again, because the one thing worse than a slow till is a till that loses
   *  what somebody just scanned.
   *
   *  Nothing retries itself. A till that quietly re-sends a sale takes the
   *  money twice.
   */
  function completeSale() {
    if (!online) return checkoutOffline();
    if (!cart.length) return;
    // Held back rather than sent to be refused: the server would decline this
    // sale anyway, and the cashier would read "not enough stock" about a shelf
    // they can see is full. Asked here, it is a date away from being sold.
    const pack = packProblem();
    if (pack) {
      toast.warn(pack);
      window.setTimeout(() => {
        const first = packNeeded.find((l) => !packExpiry[l.product_id]) ?? packNeeded[0];
        document.getElementById(`till-pack-${first?.product_id}`)?.focus();
      }, 40);
      return;
    }

    // Everything needed to put the counter back, taken before it is cleared,
    // and everything the sale is built from, taken before the screen moves on.
    const before: Counter = {
      cart, patient, payMethod, tendered, redeem, card, splitMode,
      tenderLines, changeCurrency, mobilePhone, wallet, walletCurrency,
      payable, redeemValue,
      // Snapshotted with everything else. The basket clears on the keystroke,
      // so reading these off state when the request runs would send the next
      // customer's dates, or none.
      packExpiries: Object.fromEntries(
        packNeeded.filter((l) => packExpiry[l.product_id])
          .map((l) => [l.product_id, packExpiry[l.product_id]])),
    };
    const lines = cart.reduce((n, l) => n + l.quantity, 0);
    const owed = payable;

    clearTheCounter();
    doing.run({
      label: `${lines} item${lines === 1 ? "" : "s"} · ${money(owed)}`,
      said: "Taking the money…",
      run: () => ringItUp(before),
      done: (sale: Sale) => {
        toast.ok(`${sale.sale_number} · ${money(owed)} taken. Receipt printing.`);
      },
      // Offered, not taken. The receipt has already printed; this is for the
      // roll that jammed or the customer who asks at the door.
      next: (sale: Sale) => (sale ? {
        label: "Print the receipt again",
        go: () => printPaidReceipt(sale),
      } : null),
      undo: () => {
        setCart(before.cart);
        // Including the dates read off the packs: a cashier who has already
        // typed four of them should not type them again because the line was
        // down. `packNeeded` refills itself from the restored basket.
        setPackExpiry(before.packExpiries);
        setPatient(before.patient);
        setPayMethod(before.payMethod);
        setTendered(before.tendered);
        setRedeem(before.redeem);
        setCard(before.card);
        setSplitMode(before.splitMode);
        setTenderLines(before.tenderLines);
        setChangeCurrency(before.changeCurrency);
        setMobilePhone(before.mobilePhone);
        setWallet(before.wallet);
        setWalletCurrency(before.walletCurrency);
        window.setTimeout(() => scanRef.current?.focus(), 60);
      },
    });
  }

  /** The counter, ready for the next customer. */
  function startPriceEdit(line: CartLine) {
    setPriceDraft(lineEach(line).toFixed(2));
    setPriceEdit(line.product.id);
  }

  /** Change what this line charges, on somebody's code.
   *
   *  The same action, record and rules as the dispensary's — one decision with
   *  one name, so a cashier and a dispenser are held to the same standard and
   *  both show up in the same report. The price on screen only moves once the
   *  code is accepted: an optimistic figure here would be money a customer had
   *  been quoted that nobody approved.
   */
  async function commitPrice(line: CartLine) {
    const typed = Number(priceDraft);
    const was = lineEach(line);
    setPriceEdit(null);
    setPriceDraft("");
    if (!Number.isFinite(typed) || typed < 0) return;
    if (Math.abs(typed - was) < 0.005) return;

    setTillPricing(line.product.id);
    try {
      const said = await guarded<{ id: number; now: number; below_cost?: boolean;
                                   note?: string; approved_by?: string }>(
        "script.price_set",
        (token) => api.post("/api/price-override", {
          product_id: line.product.id, now: Number(typed.toFixed(4)),
          was: line.product.unit_price, quantity: line.quantity,
          reason: "Changed at the till",
        }, token),
        `${line.product.name} · ${money(was)} → ${money(typed)}`,
      );
      if (said === CANCELLED) return;
      setCart((list) => list.map((c) => (c.product.id === line.product.id
        ? { ...c, price: said.now, priceOverrideId: said.id } : c)));
      toast.ok(`${line.product.name} now ${money(said.now)}`
        + (said.approved_by ? `, approved by ${said.approved_by}.` : "."));
      if (said.below_cost && said.note) toast.warn(said.note);
    } catch (e) {
      toast.error(errorText(e, "That price could not be authorised."));
    } finally {
      setTillPricing(null);
    }
  }

  function clearTheCounter() {
    setCart([]);
    setPackNeeded([]);
    setPackExpiry({});
    setPatient(null);
    setTendered("");
    setRedeem("0");
    setCard(EMPTY_CARD);
    setMobilePhone("");
    setResults([]);
    setScan("");
    setTenderLines([{ method: "cash", currency_code: currencyState?.base ?? "", amount: "" }]);
    window.setTimeout(() => scanRef.current?.focus(), 60);
  }

  /** What the counter looked like when the cashier pressed the button. */
  interface Counter {
    cart: CartLine[];
    patient: Patient | null;
    payMethod: string;
    tendered: string;
    redeem: string;
    card: typeof EMPTY_CARD;
    splitMode: boolean;
    tenderLines: TenderLine[];
    changeCurrency: string;
    mobilePhone: string;
    wallet: string;
    walletCurrency: string;
    payable: number;
    redeemValue: number;
    /** The expiry read off each pack, by product id, for stock that carries none. */
    packExpiries: Record<number, string>;
  }

  /** Write the sale, from the snapshot rather than from the screen.
   *
   *  Every figure comes off `was`, never off state. By the time this runs the
   *  cashier has cleared the counter and may be half way through the next
   *  customer, so reading `cart` or `payMethod` here would bill this sale for
   *  whatever is on the screen by then — the single worst bug an optimistic
   *  till could have.
   */
  async function ringItUp(was: Counter): Promise<Sale> {
    const cardTender = !was.splitMode && was.payMethod === "card"
      ? await resolveCardTender(was.payable, "POS")
      : {};
    // Mobile money settles as a tender so the provider reference is retained.
    const mobileTenders = !was.splitMode && was.payMethod === "mobile_money"
      ? [{ method: "mobile_money", wallet: was.wallet,
           currency_code: was.walletCurrency || (currencyState?.base ?? ""),
           amount: was.payable,
           reference: await resolveMobileTender(was.payable, "POS") }]
      : null;
    const sale = await api.post<Sale>("/api/pos/sales", {
      patient_id: was.patient?.id ?? null,
      items: was.cart.map((l) => ({ product_id: l.product.id, quantity: l.quantity,
                                    price_override_id: l.priceOverrideId ?? null })),
      payment_method: was.payMethod,
      amount_tendered: Number(was.tendered) || 0,
      loyalty_points_redeemed: was.redeemValue,
      pack_expiries: was.packExpiries,
      ...(mobileTenders ? { tenders: mobileTenders } : {}),
      ...(was.splitMode ? {
        tenders: was.tenderLines
          .filter((l) => Number(l.amount) > 0)
          .map((l) => ({
            method: l.method,
            currency_code: l.currency_code,
            amount: Number(l.amount),
            // Everything needed to match this line against a statement: the
            // wallet and the number, or the bank and the last four.
            reference: [l.wallet, l.phone, l.scheme,
                        l.last4 && `••${l.last4}`, l.auth]
              .filter(Boolean).join(" "),
          })),
        change_currency: was.changeCurrency,
      } : {}),
      ...cardTender,
    });

    // The receipt prints itself. A cashier who has to press Print after every
    // sale prints it late, or not at all, and the customer is already walking.
    printPaidReceipt(sale);
    setReceipt(sale);
    // Points move when a sale lands, so a linked customer is re-read — but only
    // if they are still the one on the counter.
    if (was.patient) {
      // Deliberately silent: a best-effort refresh of a record already on
      // screen after a sale. Nothing is blocked if it does not arrive, and
      // the figures shown are the ones the sale was made against.
      api.get<Patient>(`/api/patients/${was.patient.id}`)
        .then((fresh) => setPatient((now) => (now && now.id === fresh.id ? fresh : now)))
        .catch(() => {});
    }
    return sale;
  }

  /** What the customer actually has to hand over on a dispensed sale.
   *
   *  A script dispensed for a scheme member is adjudicated as it is dispensed,
   *  so the sale arrives here already split: the funder's share and the levy.
   *  Asking the customer for the gross is asking them for the scheme's money
   *  as well as their own.
   */
  function patientOwes(sale: Sale): number {
    const claim = sale.claim;
    if (!claim) return sale.total;
    if (claim.status === "rejected" || claim.status === "reversed") return sale.total;
    return Math.max(0, Number(claim.patient_liable ?? sale.total));
  }

  /** Take less than is owed and let the patient carry the balance.
   *
   *  Guarded, so the pharmacist's password is asked for by the same prompt
   *  that guards voids and price overrides rather than a second one invented
   *  here. The server answers 428 when it is missing, which is what `guarded`
   *  watches for.
   */
  async function takePart(sale: Sale, choice: PartPaymentChoice) {
    try {
      const res = await guarded(
        "sale.part_payment",
        (token) => api.post<Sale>(`/api/pos/sales/${sale.id}/pay`, {
          payment_method: "split",
          part_payment: true,
          part_payment_note: choice.note,
          // Hold the claim rather than sending it into a switch that is not
          // answering. The server has supported this all along.
          claim_later: choice.claim_later ?? false,
          claim_later_reason: choice.claim_later_reason ?? "",
          // Every payment the cashier actually took, not a single flattened
          // line. A part payment made of ZiG cash and an EcoCash transfer is
          // two tenders, and recording it as one loses which drawer each
          // belongs to, which is the whole of cash-up.
          tenders: choice.tenders,
        }, token),
        `${sale.sale_number}. ${money(choice.amount)} of ${money(patientOwes(sale))}`,
      );
      if (res === CANCELLED) return;
      const owed = Math.round((patientOwes(sale) - choice.amount) * 100) / 100;
      toast.ok(owed > 0.005
        ? `${money(choice.amount)} taken. ${money(owed)} still owed.`
        : `${money(choice.amount)} taken. Settled in full.`);
      setPartOf(null);
      setReceipt(res as Sale);
      loadPending();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  async function settlePending(sale: Sale, method: string,
                              confirmed?: { method: string; currency_code: string;
                                            amount: number; reference: string }[]) {
    // Out of the way first. The dialog used to stay up through the whole round
    // trip, so a cashier who had pressed "Take payment" watched a spinner with
    // a customer in front of them, and the one thing they could be sure of —
    // that they had pressed it — was the one thing the screen did not show.
    //
    // The pending list is what confirms it: the sale leaves it. A failure
    // leaves the sale exactly where it was, so the row is still there to try
    // again, and the message says so rather than assuming a form is still open
    // behind it.
    setSettling(null);
    markSettling(sale.id, true);
    try {
      const owed = patientOwes(sale);
      const claim = sale.claim;
      const covered = round2(sale.total - owed);

      // The confirmation dialog already captured the bank and the last four,
      // so the terminal prompt is only used when something else settles
      // without one.
      const cardTender = method === "card" && !confirmed
        ? await resolveCardTender(owed, sale.sale_number)
        : {};

      // Where the scheme is carrying part of it, the sale is settled as two
      // tenders rather than one. Sent as a split even when the levy is nil, so
      // the funder's share is recorded against the sale either way — a sale
      // marked "paid by medical aid" with no tender behind it reconciles to
      // nothing at cash-up.
      // What the cashier actually confirmed, where they confirmed it. Each
      // piece keeps its own currency and its own reference, so a ZiG swipe and
      // a USD EcoCash transfer on one sale stay two reconcilable lines rather
      // than one figure nobody can match.
      const taken = confirmed?.length
        ? confirmed
        : [{ method, currency_code: currencyState?.base ?? "USD", amount: owed,
             reference: "" }];

      const split = claim && covered > 0.005
        ? {
            payment_method: "split",
            tenders: [
              { method: "medical_aid", currency_code: currencyState?.base ?? "USD",
                amount: covered },
              ...(owed > 0.005 ? taken : []),
            ],
          }
        : confirmed?.length
          ? { payment_method: "split", tenders: taken }
          : {
              payment_method: method,
              amount_tendered: method === "cash" ? owed : 0,
            };

      const paid = await api.post<Sale>(`/api/pos/sales/${sale.id}/pay`, {
        ...split,
        ...cardTender,
      });
      setReceipt(paid);
      // Said out loud. The receipt opened and nothing else happened, so on a
      // busy counter it read as the row having simply vanished, and once the
      // receipt was dismissed there was nothing on screen saying the money had
      // been taken at all.
      toast.ok(covered > 0.005
        ? `${money(owed)} taken, ${money(covered)} on the scheme. ${sale.sale_number} is settled.`
        : `${money(owed)} taken. ${sale.sale_number} is settled.`);
      loadPending();
      if (tab === "history") loadHistory();
      // The invoice the dispensary sent has been dealt with; drop it from the
      // address so a refresh does not reopen a settled sale.
      if (settleId === sale.id) {
        const next = new URLSearchParams(params);
        next.delete("settle");
        setParams(next, { replace: true });
      }
      printPaidReceipt(paid);
    } catch (e: any) {
      toast.error(errorText(
        e, `${sale.sale_number} was not settled. It is still awaiting payment.`));
    } finally {
      // Whichever way it went, the row stops saying it is working. On success
      // loadPending has already taken it off the list; on failure it is still
      // there, in its ordinary state, ready to be tried again.
      markSettling(sale.id, false);
    }
  }

  /** Print the receipt the moment the money is taken.
   *
   *  It used to print only where a device agent was running, and to do nothing
   *  at all otherwise, so a till without the agent settled the sale, opened a
   *  receipt on screen, and left the customer waiting while somebody found the
   *  print button. The roll is the right destination when there is one; the
   *  browser's dialog is the fallback rather than the absence of one.
   */
  function printPaidReceipt(paid: Sale) {
    // The till's own receipt printer first. The routing has allowed a separate
    // one since the printer settings were written, and nothing used it: a till
    // with a receipt roll chosen still opened the browser's dialog, which is
    // the one thing this function exists to avoid.
    // WHY THE PRINTER'S COMPLAINT IS SAID OUT LOUD.
    //
    // Both of these swallowed the reason and quietly opened the print dialog.
    // From behind the counter that is a till which sometimes prints a receipt
    // and sometimes asks you to, for no reason anybody can see — and the
    // reasons are things a cashier can fix in seconds: out of paper, switched
    // off, paused. The sale is already settled either way, so this is a
    // warning and the dialog still follows.
    if (roll.goesStraightToPrinter("receipt")) {
      roll.printReceiptDirect(paid, pharmacy.name, pharmacy.regNo)
        .catch((e) => {
          toast.warn(errorText(e, "The receipt printer did not take it. "
                                + "Opening the print dialogue instead."));
          printReceipt(paid, pharmacy.name, pharmacy.regNo);
        });
      return;
    }
    if (agent?.printer.ready) {
      deviceAgent.printReceiptOnAgent(paid, pharmacy.name, pharmacy.regNo)
        .catch((e) => {
          toast.warn(errorText(e, "The receipt roll did not answer. "
                                + "Opening the print dialogue instead."));
          printReceipt(paid, pharmacy.name, pharmacy.regNo);
        });
      return;
    }
    printReceipt(paid, pharmacy.name, pharmacy.regNo);
  }

  return (
    <>
      {/* One line, not a masthead. A till is looked at all day by somebody who
          knows what screen they are on; the strapline under the title was
          costing the basket a hundred and thirty pixels to say so again. The
          subtitle stays on the pages you arrive at, not the one you live in. */}
      <div className={`page-head${tab === "till" ? " till-head" : ""}`}>
        <div>
          <h1>Front Shop</h1>
          {tab !== "till" && (
            <div className="sub">Barcode scanning, loyalty, airtime, medical aid claiming &amp; EFTPOS</div>
          )}
        </div>
        {/* History is where you go to look something up, not a place the till
            sits. Same shape as the dispensary's own history button, so the two
            counters behave alike. */}
        <button className="btn secondary"
                onClick={() => setTab(tab === "history" ? "till" : "history")}>
          <ClockCounterClockwise size={15} />
          {tab === "history" ? "Back to the till" : "History"}
        </button>
      </div>

      {/* One switch, not a row of tabs.
          Taking money and settling what the dispensary sent over are the two
          states of a till, and a cashier is always in one of them wanting the
          other. A tab bar makes you read three labels and pick; a switch says
          where you are and what one press does. It carries the count, because
          how many are waiting is the reason to press it. */}
      {tab !== "history" && (
        <div className="till-switch">
          <button className="btn"
                  onClick={() => setTab(tab === "till" ? "pending" : "till")}>
            {tab === "till" ? (
              <>Awaiting payment{pending.length > 0 && <span className="btn-count">{pending.length}</span>}</>
            ) : (
              <>Back to the till</>
            )}
          </button>
          <span className="muted small">
            {tab === "till"
              ? (pending.length
                  ? `${pending.length} dispensary sale${pending.length === 1 ? "" : "s"} waiting to be settled`
                  : "Nothing is waiting to be settled")
              : "Ringing up over the counter"}
          </span>
        </div>
      )}

      {tab === "pending" ? (
        <div className="card">
          <Refreshable
            loading={pendingLoading}
            hasData={pending.length > 0}
            skeleton={<TableSkeleton cols={5} rows={5}
              widths={["14ch", "20ch", "16ch", "10ch", "12ch"]} />}
          >
          <table>
            <thead><tr><Th>Sale</Th><Th>Customer</Th><Th>Raised</Th><Th className="num">Due</Th><th className="actions" /></tr></thead>
            <tbody>
              {pending.map((s) => (
                <tr key={s.id}
                    className={[settlingNow.has(s.id) ? "row-saving" : "",
                                settleId === s.id ? "row-flag"
                                  : outWith[String(s.id)] ? "row-muted" : ""]
                               .filter(Boolean).join(" ")}>
                  <td className="mono">
                    <EntityLink kind="sale" id={s.id}>{s.sale_number}</EntityLink>
                    {settleId === s.id && <span className="muted small"> · just dispensed</span>}
                    {/* On a driver's account. Said on the row, because the row
                        is where somebody is about to press Cash. */}
                    {outWith[String(s.id)] && (
                      <div className="muted small">
                        out with {outWith[String(s.id)].driver} ·{" "}
                        {outWith[String(s.id)].waybill_number}
                      </div>
                    )}
                  </td>
                  <td>
                    <EntityLink kind="patient" id={s.patient?.id}>
                      {s.patient ? `${s.patient.first_name} ${s.patient.last_name}` : "Walk-in"}
                    </EntityLink>
                  </td>
                  <td className="muted">{fmtDateTime(s.created_at)}</td>
                  {/* The gross, and underneath it what the customer actually
                      pays. A cashier reading only the total asks a scheme
                      member for the funder's money as well as their own. */}
                  <td className="num">
                    <b>{money(patientOwes(s))}</b>
                    {s.claim && patientOwes(s) < s.total - 0.005 && (
                      <div className="muted small">
                        of {money(s.total)} · {money(s.total - patientOwes(s))} on the scheme
                      </div>
                    )}
                  </td>
                  <td className="right" style={{ whiteSpace: "nowrap" }}>
                    {/* No "Claim aid" button: the claim was raised when the
                        script was dispensed. What is left here is collecting
                        the levy, in whatever the customer is paying with. */}
                    {/* One step, not a form. Each opens already set to that
                        method with the amount filled in, so the common case is
                        still one press. The question is only asked where the
                        answer cannot be guessed: which currency, which wallet,
                        which bank. Settling outright recorded one word, and a
                        drawer counted at five o'clock cannot be matched to a
                        day of sales that each said "cash". */}
                    {/* A sale a driver is out with is not settled here. The
                        driver collects at the door and hands it in, and that
                        hand-in is what settles it. A cashier taking it as
                        well collects the same money twice. */}
                    {settlingNow.has(s.id) ? (
                      <span className="row-doing">Taking the money…</span>
                    ) : outWith[String(s.id)] ? (
                      <span className="badge warn" title={
                        `${outWith[String(s.id)].driver} is to collect `
                        + `${money(outWith[String(s.id)].cod_amount)} at the door. `
                        + `It settles when they hand it in.`}>
                        <Truck size={11} weight="fill" /> on{" "}
                        {outWith[String(s.id)].driver}&rsquo;s account
                      </span>
                    ) : (
                      <>
                    <button className="btn small"
                            onClick={() => setSettling({ sale: s, method: "cash" })}>Cash</button>{" "}
                    <button className="btn small secondary"
                            onClick={() => setSettling({ sale: s, method: "card" })}>Card</button>{" "}
                    <button className="btn small secondary"
                            onClick={() => setSettling({ sale: s, method: "mobile_money" })}>Mobile</button>{" "}
                    {/* The conversation this exists for: they have some of it,
                        not all of it, and the medicine is already in the bag. */}
                    <button className="btn small ghost" disabled={!s.patient_id}
                            onClick={() => setPartOf(s)}>
                      Part
                    </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pending.length === 0 && !pendingLoading && (
            <div className="empty">
              <b>Nothing awaiting payment</b>
              <p>
                Every invoice raised at the dispensary has been settled. Sales
                sent here from a dispensing appear the moment they are made.
              </p>
            </div>
          )}
          </Refreshable>
        </div>
      ) : tab === "history" ? (
        <div className="card">
          <input className="page-search" value={historyQ}
                 onChange={(e) => setHistoryQ(e.target.value)}
                 placeholder="Search by invoice number or customer" />
          <Refreshable
            loading={historyLoading}
            hasData={history.length > 0}
            skeleton={<TableSkeleton cols={5} rows={6}
              widths={["14ch", "20ch", "16ch", "12ch", "10ch"]} />}
          >
          <table className="dt">
            <thead>
              <tr>
                <Th>Invoice</Th><Th>Customer</Th><Th>Taken</Th>
                <Th>How</Th><Th className="num">Total</Th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <RowLink key={h.id} to={`/sales/${h.id}`} prefetch={prefetchRoute}>
                  <td className="mono">{h.sale_number}</td>
                  <td>
                    {h.patient
                      ? `${h.patient.first_name} ${h.patient.last_name}`
                      : <span className="muted">Walk-in</span>}
                  </td>
                  <td className="muted">{fmtDateTime(h.created_at)}</td>
                  {/* How it was settled, which is the question asked when the
                      drawer does not balance. */}
                  <td>{h.payment_method || "none"}</td>
                  <td className="num"><b>{money(h.total)}</b></td>
                </RowLink>
              ))}
            </tbody>
          </table>
          {history.length === 0 && !historyLoading && (
            <div className="empty">
              <b>{historyQ ? "No sale matches that" : "Nothing taken yet"}</b>
              <p>
                {historyQ
                  ? "Search by the invoice number on the slip, or the customer's name."
                  : "Every sale settled at this till appears here, newest first."}
              </p>
            </div>
          )}
          </Refreshable>
        </div>
      ) : (
      <div className="pos-layout till-dense">
        <div>
          <div className="card">
            <div className="card-head">
              <h3>Scan or search</h3>
              {/* A phone borrowed as this till's scanner. It was built for
                  the dispensary and mounted only there, which left the till
                  — the counter most likely to have no scanner plugged into
                  it — with no way to borrow one. It produces the same event
                  the ScanBar below does and hands it to the same place. */}
            </div>
            <ScanBar
              context="pos"
              inputRef={scanRef}
              value={scan}
              onValueChange={setScan}
              onResolved={onScanned}
              onCorrect={onCorrected}
              placeholder="Scan a barcode, or type a product name…"
              cameraTitle="Scan items"
              // The basket travels with the camera. Scanning a trolley of
              // front-shop items without seeing what has gone in is how you
              // find out at the till that something scanned twice.
              cameraFeed={
                <>
                  <div className="scan-feed-head">
                    <span>Scanned items</span>
                    <span>{money(total)}</span>
                  </div>
                  {cart.length === 0 && (
                    <p className="muted" style={{ margin: 0 }}>
                      Point the camera at a barcode to start.
                    </p>
                  )}
                  {cart.map((l) => (
                    <div key={l.product.id} className="scan-feed-row">
                      <span>
                        {l.product.name}
                        {l.quantity > 1 && <b> ×{l.quantity}</b>}
                      </span>
                      <span className="mono">{money(lineEach(l) * l.quantity)}</span>
                    </div>
                  ))}
                </>
              }
              autoFocus
            />
            {results.map((p) => (
              <div key={p.id} className="product-pick" onClick={() => addToCart(p)}>
                <span>
                  <b>{p.name}</b> {p.strength}
                  {p.category === "airtime" && <span className="badge" style={{ marginLeft: 6 }}>airtime</span>}
                  {p.schedule >= 5 && <span className="badge sched" style={{ marginLeft: 6 }}>{sched(p.schedule)}</span>}
                </span>
                <span className="muted">{money(p.unit_price)} · {p.category === "airtime" ? "∞" : p.quantity_on_hand}</span>
              </div>
            ))}
          </div>

          {/* The basket, ruled to the floor like the dispensary's script.
              Columns are drawn whether or not anything is in them, so a cashier
              can see where the next scan lands rather than reading an apology in
              the middle of an empty box. It scrolls inside itself, so a trolley
              of forty items never pushes the total off the screen. */}
          <div className="card sec till-basket">
            <div className="till-row till-row-head" aria-hidden="true">
              <span>Item</span>
              <span className="num">Qty</span>
              <span className="num">Price</span>
              <span className="num">Total</span>
              <span />
            </div>
            <div className="till-lines">
              {cart.map((l) => (
                <div key={l.product.id} className="till-row">
                  <span className="till-name">
                    <span className="cell-text">{l.product.name} {l.product.strength}</span>
                    {l.product.schedule >= 3 && (
                      <span className="badge muted">{sched(l.product.schedule)}</span>
                    )}
                  </span>
                  <span className="num">
                    <input className="cell-input is-num" type="number" min={1}
                           aria-label={`Quantity of ${l.product.name}`}
                           value={l.quantity}
                           onFocus={(e) => e.currentTarget.select()}
                           onChange={(e) => setCart(cart.map((c) => c.product.id === l.product.id
                             ? { ...c, quantity: Math.max(1, Number(e.target.value)) } : c))} />
                  </span>
                  {/* The price, edited where it is shown, exactly like the
                      quantity beside it. And it costs a code, because a price
                      changed at a counter with nobody named against it is how a
                      drawer goes short. */}
                  <span className={`num till-price${tillPricing === l.product.id ? " is-busy" : ""}`
                          + (l.price !== undefined ? " is-hand-set" : "")}
                        onDoubleClick={() => startPriceEdit(l)}
                        title={l.price !== undefined
                          ? `Set by hand. The shelf price is ${money(l.product.unit_price)}.`
                          : "Double-click to change this price. It needs a code."}>
                    {priceEdit === l.product.id ? (
                      <input className="cell-input is-num" type="number" min={0} step="0.01"
                             autoFocus
                             aria-label={`Price of ${l.product.name}`}
                             value={priceDraft}
                             onFocus={(e) => e.currentTarget.select()}
                             onChange={(e) => setPriceDraft(e.target.value)}
                             onKeyDown={(e) => {
                               if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
                               if (e.key === "Escape") {
                                 e.preventDefault(); setPriceEdit(null); setPriceDraft("");
                               }
                             }}
                             onBlur={() => commitPrice(l)} />
                    ) : (<>
                      {money(lineEach(l))}
                      {l.price !== undefined && <span className="rx-hand-set">*</span>}
                    </>)}
                  </span>
                  <span className="num"><b>{money(lineEach(l) * l.quantity)}</b></span>
                  <span className="right">
                    <IconButton action="remove" danger title="Remove from the basket"
                      onClick={() => setCart(cart.filter((c) => c.product.id !== l.product.id))} />
                  </span>
                </div>
              ))}
              <div className="till-waiting" aria-hidden="true"
                   onDoubleClick={() => scanRef.current?.focus()}>
                {Array.from({ length: 14 }).map((_, i) => (
                  <div key={`w${i}`} className="till-row till-row-empty">
                    <span>
                      {i === 0 && cart.length === 0 && (
                        <em className="till-hint">Scan an item, or press F2 to search</em>
                      )}
                    </span>
                    <span /><span /><span /><span />
                  </div>
                ))}
                <div className="till-row till-row-empty till-row-fill"><span /><span /><span /><span /><span /></div>
              </div>
            </div>
            {/* The table's own last row: what the columns above add up to. */}
            {cart.length > 0 && (
              <div className="till-foot">
                <span>{cart.reduce((n, l) => n + l.quantity, 0)} item
                  {cart.reduce((n, l) => n + l.quantity, 0) === 1 ? "" : "s"}</span>
                <span className="till-foot-cell"><span>Subtotal</span><b>{money(total)}</b></span>
                {redeemValue > 0 && (
                  <span className="till-foot-cell"><span>Points</span><b>−{money(redeemValue)}</b></span>
                )}
                <span className="till-foot-cell is-lead"><span>Due</span><b>{money(payable)}</b></span>
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h3>Customer / loyalty</h3>
            {patient ? (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <b>{patient.first_name} {patient.last_name}</b>
                  <div className="muted">{patient.loyalty_points} loyalty points · {patient.medical_aid?.name ?? "Private"}</div>
                  {owes && (
                    <div className="muted small">
                      <b>Owes {money(owes.balance)}</b>
                      {owes.oldest ? ` from ${fmtDate(owes.oldest)}` : ""} ·{" "}
                      <Link to="/money-owed">collect it</Link>
                    </div>
                  )}
                </div>
                <IconButton action="remove" onClick={() => setPatient(null)} />
              </div>
            ) : (
              <>
                <input type="search" placeholder="Link a patient (optional)…" value={patientQ} onChange={(e) => setPatientQ(e.target.value)} />
                {patients.map((p) => (
                  <div key={p.id} className="product-pick" onClick={() => { setPatient(p); setPatients([]); setPatientQ(""); }}>
                    <span>{p.last_name}, {p.first_name}</span>
                    <span className="muted">{p.loyalty_points} pts</span>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="card">
            <h3>Payment</h3>
            <div className="basket-total" style={{ marginBottom: 14 }}>{money(payable)}</div>
            {redeemValue > 0 && <div className="muted" style={{ marginTop: -10, marginBottom: 12 }}>after {redeemValue} pts redeemed off {money(total)}</div>}
            {/* A split tender is only worth the extra controls where more than
                one currency actually trades, or when the cashier asks for it. */}
            {currencyState?.multi_currency && (
              <div className="seg" style={{ marginBottom: 12 }}>
                <button className={!splitMode ? "on" : ""} onClick={() => setSplitMode(false)}>Single payment</button>
                <button className={splitMode ? "on" : ""} onClick={() => setSplitMode(true)}>Split / multi-currency</button>
              </div>
            )}

            {splitMode ? (
              <>
                {/* The same rows as the part-payment modal and the dispensary.
                    This panel asked for a method, a currency and an amount and
                    nothing else, so a split sale recorded "mobile money 20.00"
                    with no wallet on it. Unreconcilable at cash-up, and the
                    exact fault that was fixed everywhere except here. */}
                <Tenders
                  lines={tenderLines}
                  onChange={setTenderLines}
                  owed={payable}
                  allowAid={false}
                  {...world}
                />


                <div className="tender-summary">
                  <div><span>Collected</span><b>{money(collectedInBase)}</b></div>
                  <div><span>Due</span><b>{money(payable)}</b></div>
                  {shortfall > 0
                    ? <div className="short"><span>Short by</span><b>{money(shortfall)}</b></div>
                    : changeInBase > 0.004 && (
                      <div className="change">
                        <span>Change</span>
                        <b>{money(changeInBase)}</b>
                      </div>
                    )}
                </div>

                {changeInBase > 0.004 && (
                  <div className="field">
                    <label>Give change in</label>
                    <Select
                      value={changeCurrency}
                      onChange={setChangeCurrency}
                      options={(currencyState?.currencies ?? [])
                        .filter((c) => c.rate > 0)
                        .map((c) => ({
                          value: c.code,
                          label: `${c.code} ${(changeInBase * c.rate).toFixed(c.decimals)}`,
                        }))}
                    />
                  </div>
                )}
              </>
            ) : (
            <div className="field">
              <label>Method</label>
              <Select
                value={payMethod}
                onChange={setPayMethod}
                options={[
                  { value: "cash", label: "Cash" },
                  { value: "card", label: "Card (EFTPOS)" },
                  // Always offered, whether or not the device agent is running.
                  // With the agent, a prompt goes to the handset. Without it the
                  // cashier takes the payment the way most Zimbabwean tills
                  // already do, by watching the customer send to the merchant
                  // code and entering the confirmation, and hiding the option
                  // only meant those sales were rung up as cash.
                  { value: "mobile_money", label: "Mobile money" },
                  {
                    value: "medical_aid",
                    label: "Medical aid claim",
                    disabled: !patient,
                    // Why it is greyed, rather than leaving the cashier guessing.
                    hint: patient ? undefined : "needs a patient on the sale",
                  },
                ]}
              />
            </div>
            )}
            {!splitMode && payMethod === "cash" && (
              <div className="field">
                <label>Amount tendered</label>
                <input type="number" step="0.01" value={tendered} onChange={(e) => setTendered(e.target.value)} placeholder="0.00" />
                {Number(tendered) >= payable && payable > 0 && (
                  <div className="muted" style={{ marginTop: 6 }}>Change: <b>{money(Number(tendered) - payable)}</b></div>
                )}
              </div>
            )}
            {!splitMode && payMethod === "mobile_money" && (
              <>
                <MobileMoney
                  wallet={wallet}
                  onWallet={setWallet}
                  currency={walletCurrency}
                  onCurrency={setWalletCurrency}
                  phone={mobilePhone}
                  onPhone={setMobilePhone}
                  amountDue={payable}
                  base={currencyState?.base ?? "USD"}
                  rates={Object.fromEntries(
                    (currencyState?.currencies ?? []).map((c) => [c.code, c.rate]))}
                  agentReady={!!agent?.mobile_money?.ready}
                  reference={walletReference}
                  onReference={setWalletReference}
                />
                {mobileState && <div className="device-note">{mobileState}</div>}
              </>
            )}
            {!splitMode && payMethod === "card" && (
              agent?.terminal.ready ? (
                <div className="device-note ok">
                  <b>Terminal connected:</b> {agent.terminal.terminal_id ?? agent.terminal.driver}.
                  The amount is sent to the machine when you complete the sale.
                  {terminalState && <div className="muted">{terminalState}</div>}
                </div>
              ) : (
                <>
                  <div className="device-note">
                    No terminal connected to this till, key the amount into the card machine,
                    then capture the slip so the sale can be reconciled.
                  </div>
                  <div className="form-row">
                    <div className="field"><label>Auth code</label>
                      <input value={card.auth} onChange={(e) => setCard({ ...card, auth: e.target.value })}
                        placeholder="from the slip" /></div>
                    <div className="field" style={{ maxWidth: 120 }}><label>Last 4</label>
                      <input value={card.last4} maxLength={4}
                        onChange={(e) => setCard({ ...card, last4: e.target.value.replace(/\D/g, "") })} /></div>
                  </div>
                  <div className="form-row">
                    <div className="field"><label>Reference (optional)</label>
                      <input value={card.reference}
                        onChange={(e) => setCard({ ...card, reference: e.target.value })} /></div>
                    <div className="field" style={{ maxWidth: 140 }}><label>Scheme</label>
                      <Select
                        value={card.scheme}
                        onChange={(v) => setCard({ ...card, scheme: v })}
                        placeholder="—"
                        clearable
                        options={[
                          { value: "visa", label: "Visa" },
                          { value: "mastercard", label: "Mastercard" },
                          { value: "amex", label: "Amex" },
                        ]}
                      /></div>
                    <div className="field" style={{ maxWidth: 140 }}><label>Terminal</label>
                      <input value={card.terminal}
                        onChange={(e) => setCard({ ...card, terminal: e.target.value })} /></div>
                  </div>
                </>
              )
            )}
            {patient && (patient.loyalty_points ?? 0) > 0 && (
              <div className="field">
                <label>Redeem loyalty points (1 pt = {money(1)}), available: {patient.loyalty_points}</label>
                <input type="number" min={0} max={patient.loyalty_points} value={redeem} onChange={(e) => setRedeem(e.target.value)} />
              </div>
            )}
            {/* Stock the shelf holds and the till cannot sell until somebody
                reads the date off the box. Shown in the payment column, beside
                the money, because that is where the cashier already is, and
                answered in one keystroke per line. */}
            {packNeeded.length > 0 && (
              <section className="till-packs">
                <h4>Expiry from the pack</h4>
                <p className="muted small">
                  This stock was counted in without an expiry date. Type the date printed
                  on the box you are selling. It is kept against the stock, so nobody is
                  asked for it again.
                </p>
                <ul>
                  {packNeeded.map((l) => {
                    const value = packExpiry[l.product_id] ?? "";
                    const past = !!value && value < new Date().toLocaleDateString("en-CA");
                    return (
                      <li key={l.product_id} className={past ? "is-bad" : value ? "is-done" : ""}>
                        <div className="till-pack-what">
                          <b>{l.name}</b>
                          <span className="muted small">
                            {l.undated_units} with no date recorded
                            {l.dated_units ? `, ${l.dated_units} dated` : ""}
                          </span>
                          {past && (
                            <span className="till-pack-warn">
                              <Warning size={12} weight="fill" /> That box has expired.
                              Take another off the shelf.
                            </span>
                          )}
                        </div>
                        <input type="date" id={`till-pack-${l.product_id}`}
                          aria-label={`Expiry printed on the pack of ${l.name}`}
                          value={value}
                          onChange={(e) => setPackExpiry((cur) => ({
                            ...cur, [l.product_id]: e.target.value }))} />
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
            {/* Released on the keystroke. It is not disabled while a sale is
                in flight, because the whole point is that the next customer
                can start: the work is in the tray, not on this button. */}
            <button className="btn primary till-take"
              disabled={cart.length === 0 || (splitMode && shortfall > 0)}
              onClick={completeSale}>
              {mobileState ? "Waiting for customer…" : terminalState ? "Waiting for card…"
                : payMethod === "medical_aid" ? "Submit claim & complete" : "Complete sale"}
              <span className="till-take-key">F12</span>
            </button>
          </div>

        </div>
      </div>
      )}
      {/* Outside the tab conditional, deliberately.
          This lived inside the till's branch, so settling from Awaiting
          payment set the receipt and drew nothing: the row vanished, no
          receipt appeared, and the cashier had no way to tell whether the
          money had been taken. A receipt belongs to the sale, not to the
          screen the sale happened to be settled from. */}
        {/* Not on the till itself. There the receipt prints by itself and the
            tray says what was taken, so this card only repeated it. And being
            an ordinary block it pushed the key strip off the bottom of the
            screen, which is how F12 disappeared after every sale. It stays for
            a sale settled from Awaiting payment, where it is the only thing
            that says the money was taken. */}
        {receipt && tab !== "till" && (
          <div className="card">
            <h3>Receipt {receipt.sale_number}</h3>
            <table>
              <tbody>
                {receipt.items.map((i) => (
                  <tr key={i.id}><td>{i.description} ×{i.quantity}</td><td className="num">{money(i.line_total)}</td></tr>
                ))}
                <tr><td><b>Total (incl. VAT {money(receipt.vat_amount)})</b></td><td className="num"><b>{money(receipt.total)}</b></td></tr>
                {receipt.payment_method === "cash" && receipt.change_due > 0 && (
                  <tr><td>Change</td><td className="num">{money(receipt.change_due)}</td></tr>
                )}
                {receipt.loyalty_points_earned > 0 && (
                  <tr><td>Loyalty earned</td><td className="num">{receipt.loyalty_points_earned} pts</td></tr>
                )}
              </tbody>
            </table>
            {receipt.claim && (
              <div className={receipt.claim.status === "approved" ? "success-banner" : "error-banner"} style={{ marginTop: 12 }}>
                Claim {receipt.claim.claim_number}: <b>{receipt.claim.status.toUpperCase()}</b>. {receipt.claim.response_message}
                {receipt.claim.patient_liable > 0 && <> Shortfall <b>{money(receipt.claim.patient_liable)}</b> to settle here.</>}
              </div>
            )}
            <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
              <button className="small" onClick={() => printReceipt(receipt, pharmacy.name, pharmacy.regNo)}><Printer size={14} /> Print receipt</button>
              <button className="secondary small" onClick={() => setReceipt(null)}>Dismiss</button>
            </div>
          </div>
        )}
      {settling && (
        <SettleSale
          sale={settling.sale.sale_number}
          owed={patientOwes(settling.sale)}
          method={settling.method}
          patientId={settling.sale.patient_id ?? null}
          aidCovers={settling.sale.total - patientOwes(settling.sale)}
          {...currencyWorld(currencyState)}
          onCancel={() => setSettling(null)}
          onConfirm={(choice) =>
            settlePending(settling.sale, settling.method, choice.tenders)}
        />
      )}

      {partOf && (
        <PartPayment
          patientId={partOf.patient_id ?? null}
          owed={patientOwes(partOf)}
          patient={partOf.patient
            ? `${partOf.patient.first_name} ${partOf.patient.last_name}`
            : "This customer"}
          {...currencyWorld(currencyState)}
          aidCovers={partOf.total - patientOwes(partOf)}
          onCancel={() => setPartOf(null)}
          onConfirm={(choice) => takePart(partOf, choice)}
        />
      )}
      {stepUpPrompt}
      {/* The keys this screen answers to, said out loud. The till had them all
          along and showed none of them, so every cashier used the mouse. */}
      {tab === "till" && <KeyBar keys={hotkeys} />}
    </>
  );
}
