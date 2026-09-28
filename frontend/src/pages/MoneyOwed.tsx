/** Medicine that has gone out and money that has not come in.
 *
 *  A work list, not a report. Every row is a patient who took their medicine
 *  and paid part of it, and it stays here until somebody collects the rest —
 *  which is the whole reason for allowing it in the first place. A debt the
 *  software will not show you is a debt nobody chases.
 *
 *  Sorted oldest first, because the one most likely to go uncollected is the
 *  one that has been sitting longest, not the largest.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Phone } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "../components/BusyButton";
import { currencyWorld } from "../components/Tenders";
import { EntityLink } from "../components/Filters";
import { TableSearch, useSearch } from "../components/Filters";
import PartPayment, { PartPaymentChoice } from "../components/PartPayment";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/Confirm";
import { Figure, GhostRows, Refreshable } from "../components/Skeleton";
import Person from "../components/Person";
import PageHead from "../components/PageHead";
import Th from "../components/Th";
import ExportButton from "../components/ExportButton";

interface Row {
  sale_id: number;
  sale_number: string;
  created_at: string;
  patient_id: number | null;
  patient: string;
  phone: string;
  total: number;
  paid: number;
  balance: number;
  days: number;
}

interface Owed {
  items: Row[];
  total_owed: number;
  patients: number;
}

export default function MoneyOwed() {
  const [data, setData] = useState<Owed | null>(null);
  const [failed, setFailed] = useState("");
  const [spinning, setSpinning] = useState(false);
  const [collecting, setCollecting] = useState<Row | null>(null);
  const [currencyState, setCurrencyState] = useState<any>(null);
  const toast = useToast();
  const confirm = useConfirm();

  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setSpinning(true);
    api.get<Owed>("/api/pos/owed")
      .then((d) => { setData(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "What is owed could not be worked out.")))
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 400);
      });
  }, []);
  useEffect(() => {
    api.get("/api/currency").then(setCurrencyState).catch(() => undefined);
  }, []);


  useEffect(() => { load(); }, [load]);

  /** Collecting the rest needs no authorisation — taking money in is not the
   *  decision that had to be approved; letting it go out was. */
  async function collect(row: Row, choice: PartPaymentChoice) {
    try {
      const settles = choice.amount + 0.005 >= row.balance;
      await api.post(`/api/pos/sales/${row.sale_id}/pay`, settles
        ? { payment_method: choice.method, amount_tendered: choice.amount }
        : {
            payment_method: "split",
            part_payment: true,
            part_payment_note: choice.note,
            tenders: [{ method: choice.method, currency_code: "USD", amount: choice.amount }],
          });
      toast.ok(settles
        ? `${money(choice.amount)} collected. ${row.patient} owes nothing.`
        : `${money(choice.amount)} collected. ${money(row.balance - choice.amount)} still owed.`);
      setCollecting(null);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  /** Remind everybody in view what they owe.
   *
   *  WHAT THIS SCREEN IS ACTUALLY FOR, AND WHAT IT COULD NOT DO.
   *
   *  A debtors' list exists to be worked. The working is a morning of telephone
   *  calls, and the calls do not happen: there are eighty names, each one is an
   *  awkward conversation, and the awkward conversation about forty dollars is
   *  the one that gets postponed until the debt is a year old and written off.
   *
   *  A message is not an awkward conversation. It states the amount and the
   *  sale it belongs to, which is most of what the call was going to say, and
   *  the ones who then walk in have settled themselves.
   *
   *  It goes to whoever is in view, so the filter above decides who is asked:
   *  the usual thing somebody wants is everybody past thirty days, and that is
   *  a search away rather than a second button.
   *
   *  Sent one at a time because there is no bulk endpoint, and counted, so a
   *  number that fails is named.
   */
  async function remindEveryone() {
    const reachable = shown.filter((r) => r.phone?.trim() && r.patient_id);
    const without = shown.length - reachable.length;
    if (!reachable.length) {
      toast.warn(shown.length
        ? "None of these have a telephone number on file, so they have to be rung by hand."
        : "There is nobody here to remind.");
      return;
    }
    const owed = reachable.reduce((sum, r) => sum + r.balance, 0);
    const ok = await confirm({
      title: `Remind ${reachable.length} `
           + `${reachable.length === 1 ? "person" : "people"} of ${money(owed)}?`,
      body: (
        <>
          <p>
            Each of them gets one message with their own balance and the sale it
            belongs to, asking them to settle it. It goes to the number on their
            profile.
          </p>
          {without > 0 && (
            <p className="muted">
              {without} of the {shown.length} have no number on file and are
              skipped. They stay on the list to be rung by hand.
            </p>
          )}
        </>
      ),
      confirmLabel: `Send ${reachable.length}`,
    });
    if (!ok) return;

    let sent = 0;
    const failedFor: string[] = [];
    for (const r of reachable) {
      try {
        await api.post("/api/messages", {
          patient_id: r.patient_id,
          channel: "sms",
          subject: "Your pharmacy account",
          body: `Good day ${r.patient}. Our records show ${money(r.balance)} `
              + `still owing on ${r.sale_number}. Please settle it at the `
              + `pharmacy when you can, or telephone us if this does not look `
              + `right.`,
        });
        sent += 1;
      } catch {
        failedFor.push(r.patient);
      }
    }
    if (failedFor.length) {
      toast.warn(`${sent} reminded. ${failedFor.length} did not go: `
                 + failedFor.slice(0, 3).join(", ")
                 + (failedFor.length > 3 ? ` and ${failedFor.length - 3} more.` : "."));
    } else {
      toast.ok(`${sent} ${sent === 1 ? "person has" : "people have"} been reminded.`);
    }
  }

  const all = data?.items ?? [];
  const stale = all.filter((r) => r.days >= 30);

  /* THE BAND IS THE FILTER, AND IT HAD TO BECOME ONE.
   *
   * A comment on the reminder below said the usual thing somebody wants is
   * everybody past thirty days, "and that is a search away rather than a
   * second button". It was not. The only narrowing was a free text search
   * over names, telephone numbers and sale numbers, and the thirty day figure
   * was a tile nobody could press. So "Remind 80 to pay" meant everybody,
   * including the person who took their medicine this morning and is not late
   * at all, and a reminder to somebody who owes nothing yet is worse than no
   * reminder: it is the pharmacy looking as though it does not know.
   *
   * The tile was already there and already carried the number. Making it the
   * control adds nothing to the screen.
   */
  const [olderThan, setOlderThan] = useState(0);
  const rows = olderThan ? all.filter((r) => r.days >= olderThan) : all;
  /* Every unpaid sale in the shop. Somebody rings about THEIR bill, so
     the question is always one name in a list that only grows. */
  const { q, setQ, shown } = useSearch(rows, (r) => [r.patient, r.phone, r.sale_number]);

  return (
    <>
      <PageHead
        title="Money owed"
        sub="Medicine that has gone out and has not been paid for in full"
        // The debtors' list is worked from a sheet as often as from a screen:
        // it is what a morning of follow-up calls is read off, and it is
        // reconciled in a spreadsheet whatever the software offers.
        take={<ExportButton dataset="money-owed" />}
        also={
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} />
            Refresh
          </button>
        }
        /* The loudest thing on a debtors' screen should be collecting the debt.
           Whoever is in view is who gets asked, so narrowing the list above
           narrows who is reminded. */
        primary={shown.length ? (
          <BusyButton className="btn primary" onClick={remindEveryone}
                      busyLabel="Reminding them…">
            <Phone size={14} /> Remind {shown.length} to pay
          </BusyButton>
        ) : undefined}
      />

      {failed && <div className="alert error">{failed}</div>}

      {/* SCOPED LOADING.
       *
       * The three bands sat behind `data &&`, so a debtors' screen opened with
       * nothing on it at all: not the figures, which nobody could know yet,
       * but "Owed to the pharmacy" and "Owing more than a month", which are
       * written here and are the same words every morning. The month filter is
       * one of those bands, so it disappeared with them and the one control
       * that narrows this list was missing exactly while somebody was waiting
       * for the list.
       *
       * The words stay. The figures pulse, and the button is simply inert
       * until there is something to filter. */}
      <div className="wc-bands">
        <div className="wl-stat">
          <b><Figure ready={!!data} w="9ch">{data && money(data.total_owed)}</Figure></b>
          <span>Owed to the pharmacy</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!data} w="3ch">{data?.patients}</Figure></b>
          {/* Said in the plural until the count is in. Guessing "patient" or
              "patients" from a nought would be guessing the answer. */}
          <span>patient{data && data.patients === 1 ? "" : "s"}</span>
        </div>
        <button
          className={`wl-stat${data && stale.length ? " wc-stale" : ""}`
                     + (olderThan ? " is-on" : "")}
          disabled={!data}
          onClick={() => setOlderThan(olderThan ? 0 : 30)}
          title={olderThan
            ? "Show everything owed again"
            : "Show only what has been owed longer than a month"}>
          <b>
            <Figure ready={!!data} w="9ch">
              {data && money(stale.reduce((s, r) => s + r.balance, 0))}
            </Figure>
          </b>
          <span>Owing more than a month</span>
        </button>
      </div>

      <div className="card">
        {/* The search box and its placeholder are written here, so they are on
            screen from the first frame and hold the row the table hangs
            beneath. "Nobody owes the pharmacy anything" used to be reachable
            the instant the page opened, before a single sale had been counted,
            which told the one person chasing debts that there were none. It is
            now the last arm of three: ghost, then empty, then the real list. */}
        {data ? (
          <TableSearch value={q} onChange={setQ}
                       placeholder="Find a patient, a phone number or a sale…"
                       shown={shown.length} total={rows.length} />
        ) : (
          /* The same row, in the same place, because the box and its
             placeholder are written here and somebody can start typing a name
             before the list lands. The only part of it that is an answer is
             the count on the right, and `TableSearch` can only print a number,
             so while there is no answer the count pulses instead of saying
             nought. Nought would be a claim about the debtors' book. */
          <div className="dt-filters">
            <input type="search" className="filter-search" value={q}
                   placeholder="Find a patient, a phone number or a sale…"
                   onChange={(e) => setQ(e.target.value)} />
            <span className="dt-count muted">
              <Figure ready={false} w="3ch">{null}</Figure>
            </span>
          </div>
        )}
        {/* Said where the list is, not only on the tile, because what is on
            screen is now a part of what is owed and everything below reads
            differently for it. */}
        {olderThan > 0 && (
          <p className="muted small">
            Showing the {rows.length} owed longer than a month, of{" "}
            {all.length}.{" "}
            <button className="linkish" onClick={() => setOlderThan(0)}>
              Show everything owed
            </button>
          </p>
        )}
        {!data && failed ? (
          /* A skeleton that never resolves is the one failure nobody reports,
             because it looks like patience is all it needs. The alert above
             has already said what went wrong, so this simply stops pulsing. */
          <p className="muted small">
            Nothing can be listed here until what is owed can be read again.
          </p>
        ) : !data ? (
          <table className="dt">
            <thead>
              <tr>
                <Th>Patient</Th><Th>Sale</Th><Th>Since</Th>
                <Th className="num">Sale</Th><Th className="num">Paid</Th>
                <Th className="num">Owed</Th><th className="actions" />
              </tr>
            </thead>
            {/* A patient carries their telephone number underneath and a date
                carries how many days ago it was, so those two ghost with a
                second line or the table lifts when the rows land. */}
            <GhostRows cols={7} rows={5} secondLine={[0, 2]}
                       widths={["18ch", "10ch", "10ch", "8ch", "8ch", "8ch", "7ch"]} />
          </table>
        ) : rows.length === 0 ? (
          <div className="empty">
            <b>Nobody owes the pharmacy anything.</b>
            <p>
              A sale appears here when a patient pays part of it and takes their
              medicine. It leaves when the balance is collected.
            </p>
          </div>
        ) : (
          /* The previous list stays put while the next one loads: a debtors'
             table that blanks itself on every refresh reads as the money
             having been collected. */
          <Refreshable loading={loading} hasData skeleton={null}>
          <table className="dt">
            <thead>
              <tr>
                <Th>Patient</Th><Th>Sale</Th><Th>Since</Th>
                <Th className="num">Sale</Th><Th className="num">Paid</Th>
                <Th className="num">Owed</Th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.sale_id} className={r.days >= 30 ? "row-flag" : ""}>
                  <td>
                    <EntityLink kind="patient" id={r.patient_id}>
                      <Person className="strong" name={r.patient} />
                    </EntityLink>
                    {r.phone && (
                      <div className="muted small"><Phone size={11} /> {r.phone}</div>
                    )}
                  </td>
                  <td className="mono">
                    <EntityLink kind="sale" id={r.sale_id}>{r.sale_number}</EntityLink>
                  </td>
                  <td>
                    {fmtDate(r.created_at)}
                    <div className="muted small">
                      {r.days} day{r.days === 1 ? "" : "s"}
                    </div>
                  </td>
                  <td className="num">{money(r.total)}</td>
                  <td className="num">{money(r.paid)}</td>
                  <td className="num"><b>{money(r.balance)}</b></td>
                  <td className="actions">
                    <BusyButton className="small" onClick={async () => setCollecting(r)}>
                      Collect
                    </BusyButton>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </Refreshable>
        )}
      </div>

      {collecting && (
        <PartPayment
          owed={collecting.balance}
          patient={collecting.patient}
          {...currencyWorld(currencyState)}
          onCancel={() => setCollecting(null)}
          onConfirm={(choice) => collect(collecting, choice)}
        />
      )}
    </>
  );
}
