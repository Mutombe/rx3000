import { useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { Hotkey, useHotkeys } from "../hooks/useHotkeys";
import { api, fmtDate, fmtDateTime, money, errorText, prefetchRoute, Refused } from "../api";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { ScanBar, ScanResult } from "../components/Scanner";
import { useConnection } from "../components/Connection";
import * as queue from "../offline/queue";
import * as deviceAgent from "../deviceAgent";
import { printReceipt } from "../print";
import { usePharmacy } from "../hooks/usePharmacy";
import { CurrencyState, Patient, Product, Sale } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import MobileMoney from "../components/MobileMoney";
import { ClockCounterClockwise, Printer, Truck } from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";
import RowLink from "../components/RowLink";
import { Link, useSearchParams } from "react-router-dom";
import { EntityLink } from "../components/Filters";
import PartPayment, { PartPaymentChoice } from "../components/PartPayment";
import Tenders, { TenderLine, currencyWorld, inBase } from "../components/Tenders";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import SettleSale from "../components/SettleSale";

type Tab = "till" | "pending" | "history";

const EMPTY_CARD = { auth: "", reference: "", last4: "", scheme: "", terminal: "" };

/* The local three-field TenderLine used to live here — method, currency,
   amount, which is why the till's own split panel could not say which wallet
   or which bank, while the part-payment modal beside it could. It is the
   shared one now: one definition, one set of questions, wherever money is
   taken. */

const round2 = (n: number) => Math.round(n * 100) / 100;

interface CartLine {
  product: Product;
  quantity: number;
}

export default function POS() {
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
    }).catch(() => {});
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
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(scan)}&limit=8`).then(setResults);
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

  const total = cart.reduce((s, l) => s + l.product.unit_price * l.quantity, 0);
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
      disabled: cart.length === 0 || busy,
      run: () => { void checkout(); },
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
      });
      const held = await queue.pendingCount();
      toast.ok(
        `Sale held on this till (${row.ref.slice(0, 12)}…). ${held} waiting to be `
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

  async function checkout() {
    if (!online) return checkoutOffline();
    setBusy(true);
    try {
      const cardTender = !splitMode && payMethod === "card"
        ? await resolveCardTender(payable, "POS")
        : {};
      // Mobile money settles as a tender so the provider reference is retained.
      const mobileTenders = !splitMode && payMethod === "mobile_money"
        ? [{ method: "mobile_money", wallet, currency_code: walletCurrency || (currencyState?.base ?? ""),
             amount: payable, reference: await resolveMobileTender(payable, "POS") }]
        : null;
      const sale = await api.post<Sale>("/api/pos/sales", {
        patient_id: patient?.id ?? null,
        items: cart.map((l) => ({ product_id: l.product.id, quantity: l.quantity })),
        payment_method: payMethod,
        amount_tendered: Number(tendered) || 0,
        loyalty_points_redeemed: redeemValue,
        ...(mobileTenders ? { tenders: mobileTenders } : {}),
        ...(splitMode ? {
          tenders: tenderLines
            .filter((l) => Number(l.amount) > 0)
            .map((l) => ({
              method: l.method,
              currency_code: l.currency_code,
              amount: Number(l.amount),
              // Everything needed to match this line against a statement: the
              // wallet and the number, or the bank and the last four. Dropped
              // on the floor until now.
              reference: [l.wallet, l.phone, l.scheme,
                          l.last4 && `••${l.last4}`, l.auth]
                .filter(Boolean).join(" "),
            })),
          change_currency: changeCurrency,
        } : {}),
        ...cardTender,
      });
      setReceipt(sale);
      setCart([]);
      setTendered("");
      setRedeem("0");
      setCard(EMPTY_CARD);
      setMobilePhone("");
      setTenderLines([{ method: "cash", currency_code: currencyState?.base ?? "", amount: "" }]);
      if (patient) api.get<Patient>(`/api/patients/${patient.id}`).then(setPatient);
      // Same as settling a waiting sale: the roll where there is one, the
      // browser's dialog where there is not. Printing only on the agent meant
      // a till without it took the money and printed nothing.
      printPaidReceipt(sale);
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
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
        `${sale.sale_number} — ${money(choice.amount)} of ${money(patientOwes(sale))}`,
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
    if (agent?.printer.ready) {
      deviceAgent.printReceiptOnAgent(paid, pharmacy.name, pharmacy.regNo)
        .catch(() => printReceipt(paid, pharmacy.name, pharmacy.regNo));
      return;
    }
    printReceipt(paid, pharmacy.name, pharmacy.regNo);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Front Shop</h1>
          <div className="sub">Barcode scanning, loyalty, airtime, medical aid claiming &amp; EFTPOS</div>
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
            <thead><tr><th>Sale</th><th>Customer</th><th>Raised</th><th className="num">Due</th><th className="actions" /></tr></thead>
            <tbody>
              {pending.map((s) => (
                <tr key={s.id}
                    className={settleId === s.id ? "row-flag"
                      : outWith[String(s.id)] ? "row-muted" : ""}>
                  <td className="mono">
                    <EntityLink kind="sale" id={s.id}>{s.sale_number}</EntityLink>
                    {settleId === s.id && <div className="muted small">just dispensed</div>}
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
                        still one press — the question is only asked where the
                        answer cannot be guessed: which currency, which wallet,
                        which bank. Settling outright recorded one word, and a
                        drawer counted at five o'clock cannot be matched to a
                        day of sales that each said "cash". */}
                    {/* A sale a driver is out with is not settled here. The
                        driver collects at the door and hands it in, and that
                        hand-in is what settles it — a cashier taking it as
                        well collects the same money twice. */}
                    {outWith[String(s.id)] ? (
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
                <th>Invoice</th><th>Customer</th><th>Taken</th>
                <th>How</th><th className="num">Total</th>
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
                  <td>{h.payment_method || "—"}</td>
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
      <div className="pos-layout">
        <div>
          <div className="card">
            <h3>Scan or search</h3>
            <ScanBar
              context="pos"
              inputRef={scanRef}
              value={scan}
              onValueChange={setScan}
              onResolved={onScanned}
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
                      <span className="mono">{money(l.product.unit_price * l.quantity)}</span>
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
                  {p.schedule >= 5 && <span className="badge sched" style={{ marginLeft: 6 }}>S{p.schedule}</span>}
                </span>
                <span className="muted">{money(p.unit_price)} · {p.category === "airtime" ? "∞" : p.quantity_on_hand}</span>
              </div>
            ))}
          </div>

          <div className="card">
            <h3>Basket</h3>
            <table>
              <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th><th className="actions" /></tr></thead>
              <tbody>
                {cart.map((l) => (
                  <tr key={l.product.id}>
                    <td>{l.product.name} {l.product.strength}</td>
                    <td className="num" style={{ width: 90 }}>
                      <input type="number" min={1} value={l.quantity} style={{ width: 70, padding: "4px 8px" }}
                        onChange={(e) => setCart(cart.map((c) => c.product.id === l.product.id ? { ...c, quantity: Math.max(1, Number(e.target.value)) } : c))} />
                    </td>
                    <td className="num">{money(l.product.unit_price)}</td>
                    <td className="num">{money(l.product.unit_price * l.quantity)}</td>
                    <td className="right"><IconButton action="remove" danger title="Remove from the basket"
                      onClick={() => setCart(cart.filter((c) => c.product.id !== l.product.id))} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {cart.length === 0 && <div className="empty">Scan an item to begin</div>}
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
                    with no wallet on it — unreconcilable at cash-up, and the
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
            <button style={{ width: "100%" }}
              disabled={busy || cart.length === 0 || (splitMode && shortfall > 0)}
              onClick={checkout}>
              {mobileState ? "Waiting for customer…" : terminalState ? "Waiting for card…" : busy ? "Processing…"
                : payMethod === "medical_aid" ? "Submit claim & complete" : "Complete sale"}
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
        {receipt && (
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
    </>
  );
}
