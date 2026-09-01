/** Repeats due, and a quick price.
 *
 *  Two counter jobs that share a screen because they share a moment: the phone
 *  is in the pharmacist's hand either way. One is outbound, who is due and can
 *  be served today. The other is inbound — a patient asking what something will
 *  cost them before they commit to collecting it.
 *
 *  A chronic patient who has not collected is not a missed sale, it is a patient
 *  not taking their medicine. The list is ordered the way somebody would work
 *  down it: overdue first, then soonest, and stock already checked so nobody
 *  telephones a patient they cannot serve.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDate, money, prefetchRoute, errorText  } from "../api";
import Churn from "../components/Churn";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import RepeatValue from "../components/RepeatValue";
import BulkBar, { SelectAll, SelectRow } from "../components/BulkBar";
import { useSelection } from "../hooks/useSelection";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import Checkbox from "../components/Checkbox";
import Pagination from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import Select from "../components/Select";
import BusyButton from "../components/BusyButton";
import { useConfirm } from "../components/Confirm";
import { EntityLink } from "../components/Filters";
import { overdueTone, rateTone } from "../tone";
import { patientOwes } from "../terms";

interface DueItem {
  prescription_id: number; rx_number: string; item_id: number;
  patient_id: number; patient_name: string; patient_phone: string;
  product_id: number; product: string; quantity: number; supply_days: number;
  repeats_used: number; repeats_allowed: number; repeats_left: number;
  due_on: string; days_overdue: number; overdue: boolean;
  in_stock: number; can_supply: boolean;
  /** What this one repeat is worth if the patient comes in for it. */
  value: number; cost: number;
}
interface Due {
  as_at: string; count: number; overdue: number; items: DueItem[];
  /** Totals over everything due, not over the page shown. */
  total_due: number; due_value: number; overdue_value: number;
  cannot_supply: number; blocked_value: number;
}

interface Quote {
  product: string; quantity: number; classification: string; route: string;
  requires_prescription: boolean; cash_price: number; scheme: string;
  scheme_price: number; dispensing_fee: number; scheme_pays: number;
  patient_pays: number; levy: number; in_stock: number; can_supply: boolean;
  note: string;
}

type Tab = "due" | "value" | "churn" | "price";

/** Where a lost repeat went, in the pharmacy's words, and what colour it
 *  earns. Red is reserved for the two that are genuinely gone; a repeat that
 *  is merely due today has done nothing wrong. */
const LOSS_LABEL: Record<string, string> = {
  "still in hand": "Due, not yet late",
  late: "Late, still ours",
  "cannot supply": "Could not be supplied",
  lapsed: "Lapsed",
};
/* The server owns these thresholds and returns them with the figures; these
   are the fallbacks for the due list, which does not carry them. */
const GRACE = 7;
const LAPSED = 45;

const LOSS_TONE: Record<string, string> = {
  "still in hand": "muted",
  late: "warn",
  "cannot supply": "danger",
  lapsed: "danger",
};

export default function Repeats() {
  const [due, setDue] = useState<Due | null>(null);
  // The endpoint returns the whole call sheet — `count` and `overdue` are over
  // all of it and must stay that way, so only the render is bounded.
  const dueRows = useClientPage<DueItem>(due?.items ?? [], 25);
  // Which rows are ticked. Anything that leaves the list — a filter change,
  // or the send itself — is dropped from the selection, so an action can never
  // reach a row the operator can no longer see.
  const picked = useSelection(dueRows?.items ?? [], (r) => r.item_id);

  const [horizon, setHorizon] = useState(14);
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const navigate = useNavigate();
  const confirm = useConfirm();
  // What the dispensing record needs before it can be written: who checked it,
  // and whether the script it repeats was actually looked at.
  const [supplying, setSupplying] = useState<DueItem | null>(null);
  const [initials, setInitials] = useState("");
  const [sighted, setSighted] = useState(false);
  const [busy, setBusy] = useState(false);

  const [products, setProducts] = useState<any[]>([]);
  const [aids, setAids] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<any>(null);
  const [qty, setQty] = useState(1);
  const [aidId, setAidId] = useState<number | "">("");
  const [quote, setQuote] = useState<Quote | null>(null);

  const TABS: TabDef<Tab>[] = [
    { key: "due", label: "Repeats due", count: due?.count,
      hint: "Overdue first. The order somebody would telephone in" },
    { key: "value", label: "What it is worth",
      hint: "How much of its own repeat book this pharmacy keeps" },
    // Beside the value tab, because they are two halves of one question: what
    // the repeat book is worth, and who has quietly walked out of it.
    { key: "churn", label: "Churn",
      hint: "Regulars who stopped coming, and treatments that stopped" },
    { key: "price", label: "Quick price",
      hint: "What will this cost on my scheme?" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "due");
  const [perf, setPerf] = useState<any>(null);
  const [daily, setDaily] = useState<any[]>([]);
  const [weekly, setWeekly] = useState<any[]>([]);
  const [perfDays, setPerfDays] = useState("30");

  useEffect(() => {
    if (tab !== "value") return;
    api.get<any>(`/api/repeats/performance?days=${perfDays}`)
      .then(setPerf).catch(() => setPerf(null));
    api.get<any>("/api/repeats/daily?days=14")
      .then((d) => setDaily(d.days ?? [])).catch(() => setDaily([]));
    api.get<any>("/api/repeats/weekly?weeks=8")
      .then((d) => setWeekly(d.weeks ?? [])).catch(() => setWeekly([]));
  }, [tab, perfDays]);


  function load() {
    setLoading(true);
    api
      .get<Due>(`/api/repeats/call-sheet?within_days=${horizon}` +
                (overdueOnly ? "&overdue_only=true" : ""))
      .then(setDue)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, [horizon, overdueOnly]);
  useEffect(() => { api.get<any[]>("/api/medical-aids").then(setAids).catch(() => undefined); }, []);
  useEffect(() => {
    if (q.length < 2) { setProducts([]); return; }
    api.get<any[]>(`/api/products?q=${encodeURIComponent(q)}&limit=8`)
      .then(setProducts).catch(() => undefined);
  }, [q]);

  async function price(product: any) {
    setPick(product);
    try {
      setQuote(await api.post<Quote>("/api/quick-price", {
        product_id: product.id, quantity: qty,
        medical_aid_id: aidId === "" ? null : Number(aidId),
      }));
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }
  useEffect(() => { if (pick) price(pick); }, [qty, aidId]);

  /** Supply a due repeat.
   *
   *  This asked for a plain yes and sent empty initials, which the server
   *  refuses, so the button could never once have worked, and said so with a
   *  400 the dispenser could do nothing about. It also asserted that the script
   *  had been sighted, on the dispenser's behalf and without asking. A false
   *  entry in a dispensing record is worse than a missing feature: the record
   *  exists to say who checked what, and one that answers for somebody is not a
   *  record at all.
   *
   *  Both are now asked for, because both are what the dispensing is.
   */
  async function dispenseRepeat() {
    const item = supplying;
    if (!item) return;
    setBusy(true);
    try {
      const sale = await api.post<{ id: number; total: number }>(
        `/api/prescriptions/${item.prescription_id}/dispense`, {
          item_ids: [item.item_id],
          payment_method: "cash",
          supply: {},
          id_verified: false,
          script_sighted: sighted,
          prescriber_verified: false,
          id_number_seen: "",
          pharmacist_initial: initials.trim(),
          compliance_notes: "",
        });
      setSupplying(null);
      setInitials("");
      setSighted(false);

      // Dispensing hands the medicine over and raises a sale that is still
      // waiting to be paid. This screen used to stop here — a toast, and the
      // operator left on the repeats list with a pending sale nobody had told
      // them about. The stock had gone out and the money was collected only if
      // somebody remembered to go and find the invoice.
      //
      // So it goes where the dispensary already goes: the till, with the sale
      // in the address, on the list it is in. The patient is still standing
      // there — this is one movement of work, not two.
      if (sale?.id) {
        toast.ok(`${item.product} dispensed. Taking you to the till to bill `
                 + `${money(sale.total ?? item.value ?? 0)}.`);
        navigate(`/pos?settle=${sale.id}&tab=pending`);
        return;
      }
      toast.ok(`${item.product} dispensed for ${item.patient_name}.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be dispensed."));
    } finally {
      setBusy(false);
    }
  }

  /** Tell the patient their repeat is due. */
  /** Telephoning two hundred overdue repeats one row at a time telephones
   *  about nine of them. The remind endpoint existed and the only way to reach
   *  it was one button per row, which for the screen this book is worked from
   *  is the same as not having it.
   */
  async function remindAll() {
    const rows = picked.rows.filter((r) => r.patient_phone);
    const without = picked.count - rows.length;
    if (!rows.length) {
      toast.error("None of the selected patients has a telephone number.");
      return;
    }
    const ok = await confirm({
      title: `Remind ${rows.length} patient${rows.length === 1 ? "" : "s"}?`,
      body: (
        <>
          <p>
            A message goes to each of them saying their repeat is due — worth{" "}
            <b>{money(rows.reduce((n, r) => n + (r.value ?? 0), 0))}</b> if they
            all come in.
          </p>
          {without > 0 && (
            <p className="muted">
              {without} of the selected have no number on file and will be
              skipped. They are still on the list to be rung by hand.
            </p>
          )}
        </>
      ),
      confirmLabel: `Send ${rows.length}`,
    });
    if (!ok) return;

    // Sent one at a time rather than as one call, because there is no bulk
    // endpoint and inventing one to save a round trip would mean a partial
    // failure nobody could see. Counted, so the result is the truth rather
    // than an optimistic "sent".
    let sent = 0;
    const failed: string[] = [];
    for (const r of rows) {
      try {
        await api.post("/api/messages", {
          patient_id: r.patient_id,
          channel: "sms",
          subject: "Your repeat is due",
          body: `Good day ${r.patient_name}. Your ${r.product} is due for `
              + `collection. Please come in when you can.`,
        });
        sent += 1;
      } catch {
        failed.push(r.patient_name);
      }
    }
    picked.clear();
    if (failed.length) {
      toast.warn(`${sent} sent. ${failed.length} did not go: `
                 + `${failed.slice(0, 3).join(", ")}`
                 + (failed.length > 3 ? ` and ${failed.length - 3} more.` : "."));
    } else {
      toast.ok(`${sent} reminder${sent === 1 ? "" : "s"} sent.`);
    }
  }

  async function remind(item: DueItem) {
    try {
      await api.post("/api/messages", {
        patient_id: item.patient_id,
        channel: "sms",
        subject: "Your repeat is due",
        body: `Good day ${item.patient_name}. Your ${item.product} is due for `
            + `collection. Please come in when you can.`,
      });
      toast.ok(`Reminder sent to ${item.patient_name}.`);
    } catch (e) {
      toast.error(errorText(e, "The reminder could not be sent."));
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Repeats</h1>
          <p className="muted">
            {due
              ? due.count
                ? `${due.count} due within ${horizon} days` +
                  (due.overdue ? `, ${due.overdue} already overdue.` : ".")
                : "Nobody is due."
              : ""}
          </p>
        </div>
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "due" && (
        <>
          {/* What the fortnight is worth, before the list of names. A call
              sheet without it is a list; with it, it is a list in the order
              worth telephoning. */}
          {due && (
            <div className="wc-bands">
              <div className="wl-stat">
                <b>{money(due.due_value ?? 0)}</b><span>due, all of it</span>
              </div>
              <div className={`wl-stat${(due.overdue ?? 0) > 0 ? " wc-stale" : ""}`}>
                <b>{money(due.overdue_value ?? 0)}</b>
                <span>{due.overdue} already overdue</span>
              </div>
              {/* The one the pharmacy loses by its own doing. */}
              <div className={`wl-stat${(due.cannot_supply ?? 0) > 0 ? " wc-abandoned" : ""}`}>
                <b>{money(due.blocked_value ?? 0)}</b>
                <span>{due.cannot_supply} cannot be filled today</span>
              </div>
              <div className="wl-stat">
                <b>{due.total_due ?? due.count}</b><span>repeats due</span>
              </div>
            </div>
          )}

          <div className="dt-filters">
            <label>
              Within
              <Select
                value={String(horizon ?? "")}
                onChange={(__value) => setHorizon(Number(__value))}
                options={[{ value: String(7), label: "7 days" }, { value: String(14), label: "14 days" }, { value: String(30), label: "30 days" }, { value: String(60), label: "60 days" }]}
              />
            </label>
            <Checkbox checked={overdueOnly} onChange={setOverdueOnly}>Overdue only</Checkbox>
          </div>

          {/* In a card, like every other list in the product. Without one the
              table, and the skeleton standing in for it, sat directly on the
              page ground and began at the exact pixel the filter bar ended, so
              the controls and the rows read as one undifferentiated block. */}
          <div className="card">
          <Refreshable
            loading={loading}
            hasData={!!due?.items.length}
            skeleton={<TableSkeleton cols={6} rows={6}
              widths={["18ch", "22ch", "10ch", "10ch", "10ch", "12ch"]} />}
          >
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <SelectAll checked={picked.allChosen} onChange={picked.all} />
                    <th>Patient</th><th>Medicine</th><th>Due</th>
                    {/* The row already carried this figure and the table never
                        showed it — while the comment below said the question
                        being asked is "what is it worth". A queue without money
                        cannot be worked in the order that pays. */}
                    <th className="num">Worth</th>
                    <th className="num">Repeats left</th>
                    <th className="num">In stock</th><th className="actions" /></tr>
                </thead>
                <tbody>
                  {dueRows.items.map((i) => (
                    // The repeat line, not the person holding it. Clicking a
                    // repeat used to open the patient, which answers a
                    // different question — the one being asked is about this
                    // line: how many are left, what it is worth, and whether
                    // there is stock to fill it this morning.
                    <RowLink key={i.item_id} to={`/repeats/${i.item_id}`}
                      prefetch={prefetchRoute}
                      /* Green until it is late, amber while a telephone call
                         still works, red once the patient has almost certainly
                         been served somewhere else, or once the shelf cannot
                         serve them, which is the same loss for a different
                         reason. Read down the edge without reading the rows. */
                      className={`row-${
                        !i.can_supply ? "danger"
                          : overdueTone(i.days_overdue,
                                        GRACE, LAPSED)}`}>
                      <SelectRow checked={picked.has(i.item_id)}
                                 onChange={() => picked.toggle(i.item_id)} />
                      <td>
                        <EntityLink kind="patient" id={i.patient_id}>{i.patient_name}</EntityLink>
                        {i.patient_phone && (
                          <div className="muted small">{i.patient_phone}</div>
                        )}
                      </td>
                      <td>
                        <EntityLink kind="product" id={i.product_id}>{i.product}</EntityLink>
                        <div className="muted small">
                          {i.quantity} · {i.supply_days} days
                        </div>
                      </td>
                      <td>
                        {fmtDate(i.due_on)}
                        {i.overdue && (
                          <div><span className="badge warn">
                            {i.days_overdue} days overdue
                          </span></div>
                        )}
                      </td>
                      <td className="num">
                        <RepeatValue value={i.value}
                          remaining={i.value * i.repeats_left} />
                      </td>
                      <td className="num">{i.repeats_left} of {i.repeats_allowed}</td>
                      <td className="num">{i.in_stock}</td>
                      <RowActions>
                        {/* A queue you can only read is a list, not a work
                            screen. A repeat is re-supplying a line on a script
                            that already exists, so dispensing it is one call —
                            there is nothing to capture again. */}
                        {/* One slot, whether it holds the action or the
                            reason there is no action. Without it the rows
                            with stock and the rows without put Alter and
                            Remind in different places, and a column of
                            actions that does not line up reads as broken. */}
                        <span className="act-primary">
                          {i.can_supply ? (
                            <BusyButton className="btn primary sm"
                                        onClick={() => {
                                          setInitials(""); setSighted(false);
                                          setSupplying(i);
                                        }}>
                              Dispense
                              <span className="btn-count">{i.quantity}</span>
                            </BusyButton>
                          ) : (
                            <span className="badge warn">not enough stock</span>
                          )}
                        </span>
                        {/* Not every repeat goes out as written. The patient
                            wants a fortnight rather than a month, or something
                            added, or the prescriber has changed the dose — and
                            the one-press supply above cannot express any of
                            that. This opens the dispensary with the script
                            already loaded, so the alteration is made where
                            capture belongs rather than by abandoning the
                            repeat and starting again. */}
                        <button className="btn ghost sm"
                          title="Open the script in the dispensary to change it"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/dispense?rx=${i.prescription_id}`
                                     + `&item=${i.item_id}`);
                          }}>
                          Alter
                        </button>
                        {/* The other half of the job. Half of a repeat queue is
                            people who have not come in, and telephoning them is
                            the work, so the message is here rather than on a
                            screen somebody has to remember to open. */}
                        <BusyButton className="btn ghost sm"
                                    disabled={!i.patient_phone}
                                    onClick={() => remind(i)}>
                          Remind
                        </BusyButton>
                      </RowActions>
                    </RowLink>
                  ))}
                  {!due?.items.length && !loading && (
                    <tr><td colSpan={6} className="muted pad">Nobody is due.</td></tr>
                  )}
                </tbody>
              </table>
              <Pagination meta={dueRows.meta} onPage={dueRows.setPage} noun="repeats" />
            </div>
          </Refreshable>
          </div>
        </>
      )}

      {tab === "value" && (
        <>
          <div className="card">
            <div className="card-head">
              <div>
                <h3>How much of its own repeat book this pharmacy keeps</h3>
                <span className="muted small">
                  A repeat that was not filled leaves no record anywhere — the
                  patient simply goes elsewhere next month and the line stops
                  appearing. This is the one figure a takings report cannot show.
                </span>
              </div>
              <Select value={perfDays} onChange={setPerfDays}
                      options={[{ value: "7", label: "Last 7 days" },
                                { value: "30", label: "Last 30 days" },
                                { value: "90", label: "Last quarter" }]} />
            </div>

            {!perf ? <TableSkeleton cols={4} rows={3} /> : (
              <>
                <div className="wc-bands">
                  <div className="wl-stat">
                    <b>{money(perf.due_value)}</b>
                    <span>the book was worth · {perf.due} repeats</span>
                  </div>
                  <div className="wl-stat">
                    <b className="tone-ok">{money(perf.captured_value)}</b>
                    <span>
                      we filled · {perf.captured}
                      {/* On time is the half that decides whether they come
                          back. A pharmacy filling everything three weeks late
                          has kept the money and is one bad month from losing
                          the patient. */}
                      {perf.on_time_rate !== null && perf.on_time_rate !== undefined
                        && ` · ${Math.round(perf.on_time_rate * 100)}% on time`}
                    </span>
                  </div>
                  {perf.filled_late > 0 && (
                    <div className="wl-stat wc-stale">
                      <b className="tone-warn">{money(perf.filled_late_value)}</b>
                      <span>
                        filled late · {perf.filled_late} · kept, but the patient
                        went without
                      </span>
                    </div>
                  )}
                  {/* The number the whole view exists for, said as money and
                      as a share, because "we lose about ten per cent" is a
                      sentence nobody can act on. */}
                  <div className={`wl-stat${perf.lost_value > 0.005 ? " wc-stale" : ""}`}>
                    <b className={`tone-${rateTone(
                      100 - (perf.value_loss_rate ?? 0) * 100, 80)}`}>
                      {money(perf.lost_value)}
                    </b>
                    <span>
                      lost · {perf.lost} repeats
                      {perf.value_loss_rate !== null
                        && ` · ${Math.round(perf.value_loss_rate * 100)}% of the value`}
                    </span>
                  </div>
                  <div className="wl-stat">
                    <b className={`tone-${rateTone(
                      (perf.value_capture_rate ?? 0) * 100, 80)}`}>
                      {perf.value_capture_rate === null
                        ? "—" : `${Math.round(perf.value_capture_rate * 100)}%`}
                    </b>
                    <span>of the value kept</span>
                  </div>
                  <div className="wl-stat">
                    <b>{money(perf.average_value)}</b>
                    <span>what one repeat is worth</span>
                  </div>
                  <div className="wl-stat">
                    <b>{money(perf.due_today_value)}</b>
                    <span>due today · {perf.due_today}</span>
                  </div>
                </div>

                {/* Three different jobs, so three separate figures. Telling a
                    manager "you lost 39,000" is not actionable; telling them
                    17,000 of it was an empty shelf is. */}
                {/* Every lost repeat lands in exactly one row and the column
                    sums to the loss above. A breakdown that accounts for most
                    of a number and says nothing about the rest is a breakdown
                    nobody trusts. */}
                <table className="dt" style={{ marginTop: "var(--s4)" }}>
                  <thead>
                    <tr>
                      <th>Where it went</th><th className="num">Repeats</th>
                      <th className="num">Worth</th>
                      <th className="num">Share</th><th>What fixes it</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perf.loss_split.map((r: any) => (
                      <tr key={r.reason}
                          className={`row-${LOSS_TONE[r.reason] ?? "warn"}`}>
                        <td><b>{LOSS_LABEL[r.reason] ?? r.reason}</b></td>
                        <td className="num">{r.count}</td>
                        <td className="num">{money(r.value)}</td>
                        <td className={`num tone-${LOSS_TONE[r.reason] ?? "warn"}`}>
                          {Math.round(r.share * 100)}%
                        </td>
                        <td className="muted wrap">{r.fix}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td><b>Lost altogether</b></td>
                      <td className="num"><b>{perf.lost}</b></td>
                      <td className="num"><b>{money(perf.lost_value)}</b></td>
                      <td className="num"><b>100%</b></td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </>
            )}
          </div>

          {/* Day by day, either side of today. A fortnight of this is what
              tells a pharmacy whether Monday is quietly worse than Thursday —
              and the week ahead is what somebody staffs and orders against. */}
          {weekly.length > 0 && (
            <div className="card">
              <div className="card-head">
                <div>
                  <h3>How many repeats we are filling, week by week</h3>
                  <span className="muted small">
                    What actually went out, counted and priced. A week is the
                    unit a pharmacy orders in and staffs to.
                  </span>
                </div>
              </div>
              <table className="dt">
                <thead>
                  <tr>
                    <th>Week</th>
                    <th className="num">Repeats filled</th>
                    <th className="num">Worth</th>
                    <th className="num">Average</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {weekly.map((w: any) => {
                    // Against the best full week, so the bar is a comparison
                    // rather than decoration.
                    const peak = Math.max(...weekly.filter((x: any) => !x.current)
                                           .map((x: any) => x.value), 1);
                    return (
                      <tr key={w.from} className={w.current ? "row-ok" : undefined}>
                        <td>
                          {fmtDate(w.from)} – {fmtDate(w.to)}
                          {w.current && (
                            <div className="muted small">
                              this week · {w.days_so_far} day
                              {w.days_so_far === 1 ? "" : "s"} so far
                            </div>
                          )}
                        </td>
                        <td className="num">{w.filled}</td>
                        <td className="num"><b>{money(w.value)}</b></td>
                        <td className="num">{money(w.average)}</td>
                        <td style={{ width: "14rem" }}>
                          <span className="rw-bar"
                                style={{ width: `${Math.min(100, (w.value / peak) * 100)}%` }} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="muted small">
                This is what was filled, not what fell due — a repeat's due date
                moves forward every time it is handed over, so the book does not
                remember what was outstanding in July. How much of the book is
                being kept is the capture rate above, which is worked out line
                by line.
              </p>
            </div>
          )}

          {daily.length > 0 && (
            <div className="card">
              <div className="card-head">
                <h3>What is due, day by day</h3>
                <span className="muted small">
                  A fortnight either side of today. The bar is what that day is
                  worth.
                </span>
              </div>
              <div className="rp-days">
                {daily.map((d: any) => {
                  const peak = Math.max(...daily.map((x: any) => x.value), 1);
                  return (
                    <div key={d.date}
                         className={`rp-day${d.today ? " is-today" : ""}${d.past ? " is-past" : ""}`}
                         title={`${d.due} repeats · ${money(d.value)}`}>
                      <span className="rp-bar"
                            style={{ height: `${Math.max(2, (d.value / peak) * 100)}%` }} />
                      <span className="rp-date">{fmtDate(d.date).slice(0, 6)}</span>
                      <span className="rp-value">{d.due || ""}</span>
                    </div>
                  );
                })}
              </div>
              <div className="wc-bands" style={{ marginTop: "var(--s3)" }}>
                <div className="wl-stat">
                  <b>{money(daily.filter((d: any) => d.past || d.today)
                        .reduce((n: number, d: any) => n + d.value, 0))}</b>
                  <span>the fortnight behind</span>
                </div>
                <div className="wl-stat">
                  <b>{money(daily.filter((d: any) => !d.past && !d.today)
                        .reduce((n: number, d: any) => n + d.value, 0))}</b>
                  <span>the fortnight ahead</span>
                </div>
                <div className="wl-stat">
                  <b>{money(daily.find((d: any) => d.today)?.value ?? 0)}</b>
                  <span>due today</span>
                </div>
              </div>
            </div>
          )}

          {perf?.at_risk?.length > 0 && (
            <div className="card">
              <div className="card-head">
                <h3>Worth ringing first</h3>
                <span className="muted small">
                  {perf.at_risk_total} overdue, the most valuable at the top
                </span>
              </div>
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Patient</th><th>Medicine</th><th>Due</th>
                      <th className="num">Worth</th><th>State</th>
                      <th className="actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {perf.at_risk.map((r: any) => (
                      <tr key={r.item_id}
                          className={`row-${r.state === "cannot supply" ? "danger"
                            : r.state === "lapsed" ? "danger" : "warn"}`}>
                        <td>
                          <EntityLink kind="patient" id={r.patient_id}>
                            <b>{r.patient}</b>
                          </EntityLink>
                          {r.phone && <div className="muted small">{r.phone}</div>}
                        </td>
                        <td>{r.product}</td>
                        <td>
                          {fmtDate(r.due_on)}
                          <div className="muted small">{r.days_overdue} days ago</div>
                        </td>
                        <td className="num"><b>{money(r.value)}</b></td>
                        <td>
                          <span className={`badge ${r.state === "cannot supply" ? "danger"
                            : r.state === "lapsed" ? "warn" : "muted"}`}>
                            {r.state}
                          </span>
                        </td>
                        <td className="actions">
                          {r.phone && (
                            <a className="btn small secondary" href={`tel:${r.phone}`}>
                              Call
                            </a>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {tab === "churn" && <Churn />}

      {tab === "price" && (
        <div className="quick-price">
          <div className="card">
            <label>
              Medicine
              <input value={q} autoFocus onChange={(e) => setQ(e.target.value)}
                placeholder="Start typing a product name" />
            </label>
            {products.length > 0 && (
              <ul className="pick-list">
                {products.map((p) => (
                  <li key={p.id}>
                    <BusyButton className="btn ghost sm" onClick={() => price(p)}>
                      {p.name} {p.strength}
                    </BusyButton>
                  </li>
                ))}
              </ul>
            )}
            <label>
              Quantity
              <input type="number" min={1} value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value)))} />
            </label>
            <label>
              Scheme
              <Select
                value={String(aidId ?? "")}
                onChange={(__value) => setAidId(__value === "" ? "" : Number(__value))}
                options={[{ value: "", label: "Cash" }, ...aids.map((a) => ({ value: String(a.id), label: a.name }))]}
              />
            </label>
          </div>

          {quote && (
            <div className="card">
              <h3>{quote.product} × {quote.quantity}</h3>
              <p className="muted">
                {quote.classification} · {quote.route}
                {quote.requires_prescription ? " · prescription required" : ""}
              </p>
              <dl className="kv">
                <dt>Cash price</dt><dd className="num">{money(quote.cash_price)}</dd>
                {quote.scheme && (
                  <>
                    <dt>On {quote.scheme}</dt>
                    <dd className="num">{money(quote.scheme_price)}</dd>
                    <dt>Dispensing fee</dt>
                    <dd className="num">{money(quote.dispensing_fee)}</dd>
                    <dt>Scheme pays</dt><dd className="num">{money(quote.scheme_pays)}</dd>
                    <dt>Levy</dt><dd className="num">{money(quote.levy)}</dd>
                  </>
                )}
                {/* The figure the patient standing there actually asked
                    for, called what they and every pharmacy in the country
                    call it. */}
                <dt><strong>{patientOwes(!!quote.scheme)}</strong></dt>
                <dd className="num"><strong>{money(quote.patient_pays)}</strong></dd>
              </dl>
              <p className={quote.can_supply ? "muted small" : "alert warn"}>
                {quote.can_supply
                  ? `${quote.in_stock} in stock.`
                  : `Only ${quote.in_stock} in stock. This cannot be supplied in full today.`}
              </p>
              {quote.note && <p className="muted small">{quote.note}</p>}
            </div>
          )}
        </div>
      )}

      {supplying && (
        <div className="modal-backdrop" onClick={() => setSupplying(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Dispense {supplying.product}?</h2>
            <p className="muted">
              {supplying.quantity} for <b>{supplying.patient_name}</b> against{" "}
              <span className="mono">{supplying.rx_number}</span>. This moves the
              stock, raises the sale and puts the bag on the will-call shelf.
            </p>
            <label className="field">
              Checked by (pharmacist initials)
              <input
                value={initials} maxLength={8} autoFocus
                onChange={(e) => setInitials(e.target.value)}
                placeholder="e.g. TM"
              />
            </label>
            {/* Asked, not assumed. This used to be sent as true on the
                dispenser's behalf, which put a statement in the register that
                nobody had made. */}
            <Checkbox checked={sighted} onChange={setSighted}>
              The script this repeats has been sighted
            </Checkbox>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setSupplying(null)}>
                Cancel
              </button>
              <BusyButton
                disabled={busy || !initials.trim() || !sighted}
                onClick={dispenseRepeat}
              >
                Dispense it
              </BusyButton>
            </div>
            {!initials.trim() && (
              <p className="muted small">
                The dispensing record has to say who checked it.
              </p>
            )}
          </div>
        </div>
      )}
      <BulkBar count={picked.count} noun="repeat" onClear={picked.clear}>
        <BusyButton className="btn primary sm" onClick={remindAll}
                    busyLabel="Sending…">
          Remind them all
        </BusyButton>
        {/* What the selection is worth, beside the action that chases it —
            so the decision to spend a morning on it is made on the money. */}
        <span className="bulk-count">
          worth <b>{money(picked.rows.reduce((n, r) => n + (r.value ?? 0), 0))}</b>
        </span>
      </BulkBar>
    </div>
  );
}
