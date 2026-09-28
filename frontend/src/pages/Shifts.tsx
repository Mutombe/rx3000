import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import RowLink, { RowActions } from "../components/RowLink";
import { X } from "@phosphor-icons/react";
import PettyCash from "../components/PettyCash";
import CashUp from "../components/CashUp";
import { api, fmtDateTime, money, errorText, prefetchRoute } from "../api";
import { Shift, ShiftTakings } from "../types";
import { EntityLink } from "../components/Filters";
import { Figure, GhostRows, Refreshable, TableSkeleton } from "../components/Skeleton";
import Person from "../components/Person";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import Th from "../components/Th";

/** The words a teller uses, not the words the database uses. */
const METHOD_LABEL: Record<string, string> = {
  cash: "Cash", card: "Card / swipe", mobile_money: "Mobile money",
  medical_aid: "Medical aid", loyalty: "Loyalty points",
};

export default function Shifts() {
  const [current, setCurrent] = useState<Shift | null>(null);
  /* Whether the till has been asked yet, which `current` alone cannot say: a
     null shift before the answer and a null shift after it are the same value
     and opposite statements. */
  const [shiftKnown, setShiftKnown] = useState(false);
  const [history, setHistory] = useState<Shift[]>([]);
  const [historyUnknown, setHistoryUnknown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [openFloat, setOpenFloat] = useState("500");
  const [till, setTill] = useState("1");
  const [draw, setDraw] = useState("");
  const [notes, setNotes] = useState("");
  const [takings, setTakings] = useState<ShiftTakings | null>(null);
  /* Same distinction the shift itself makes: a null takings that was never
     answered and one that came back refused are the same value and opposite
     statements, and a card left pulsing for ever is the second pretending to
     be the first. */
  const [takingsUnknown, setTakingsUnknown] = useState(false);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [counting, setCounting] = useState<Shift | null>(null);

  function load() {
    api.get<Shift | null>("/api/shifts/current").then((shift) => {
      setCurrent(shift);
      setShiftKnown(true);
      // Only meaningful once a shift exists; skipped entirely on single-currency tills.
      if (shift) {
        api.get<ShiftTakings>(`/api/shifts/${shift.id}/takings`)
          .then((t) => { setTakings(t); setTakingsUnknown(false); })
          .catch((e) => {
            setTakings(null); setTakingsUnknown(true);
            toast.error(errorText(e, "This shift's takings could not be read."));
          });
      } else {
        setTakings(null);
        setTakingsUnknown(false);
      }
    }).catch((e) => { setShiftKnown(true); toast.error(errorText(e)); });
    api.get<Shift[]>("/api/shifts")
      .then((r) => { setHistory(r); setHistoryUnknown(false); })
      // A `.finally` is not a `.catch`: the skeleton went away and an empty
      // table took its place, saying this till has never been cashed up.
      .catch(() => { setHistory([]); setHistoryUnknown(true); })
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  /* Summed from the per-currency takings, in base. The shift row carries a
     card total and a medical aid total and no equivalent for the two a teller
     actually counts out. */
  const cashTaken = (takings?.currencies ?? [])
    .reduce((n: number, c: any) => n + (c.in_base_cash ?? c.cash ?? 0), 0);
  const mobileTaken = (takings?.currencies ?? [])
    .reduce((n: number, c: any) => n + (c.mobile_money ?? 0), 0);


  async function openShift(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/api/shifts/open", {
        opening_float: Number(openFloat) || 0,
        till_no: till.trim(), draw_no: draw.trim(),
      });
      toast.ok("Shift opened, sales you process are now tracked against it.");
      load();
    } catch (err: any) { toast.error(errorText(err)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHead
        title="Cash Office"
        sub="Opening float, takings by tender and end-of-shift cash-up"
        count={<Figure ready={shiftKnown} w="13ch">
          {shiftKnown && (current ? "A shift is open" : "No shift open")}
        </Figure>}
        /* EVERY CASH-UP, WHICH IS WHERE A SHORTAGE IS FOUND.
           One cash-up on a screen says whether tonight balanced. Forty of them
           in a sheet say which till, and which person, is short every Friday,
           and that is a question no single screen can answer. */
        take={<ExportButton dataset="shifts" />}
      />

      {/* SCOPED LOADING, AND THE ORDER OF THE ARMS.
       *
       * The whole of this hung on `current`, so six tile labels, two panel
       * headings with their sentences and nine column heads were withheld
       * until the till had answered and then arrived as though they had been
       * fetched. They had not: the labels are written here and say the same
       * thing on every visit, and only the money under them comes from
       * anywhere.
       *
       * So the tiles are the frame, drawn while the answer is still coming,
       * and the offer to start a shift sits after `shiftKnown` — because a
       * screen that has not been told anything must not offer to open a till
       * that is already open. */}
      {!shiftKnown || current ? (
        <>
          <div className="grid cols-4">
            <div className="card stat hero">
              {/* This was the expected drawer total, in the largest type on the
                  page, directly above the box you type your count into. The
                  float is the useful part and gives nothing away: it is what
                  was in the drawer before trading, not what should be in it
                  now. */}
              <div className="label">Opening float</div>
              <div className="value">
                <Figure ready={!!current} w="9ch">
                  {current && money(current.opening_float)}
                </Figure>
              </div>
              <div className="hint">Counted in at the start of this shift</div>
            </div>
            {/* Cash and mobile money were both missing from this row, which
                on a Zimbabwean counter is most of the money: the headline
                showed the card total and the scheme total and left out the two
                the teller actually counts. */}
            <div className="card stat">
              <div className="label">Cash takings</div>
              <div className="value">
                <Figure ready={!!takings} w="9ch">{money(cashTaken)}</Figure>
              </div>
              <div className="hint">net of change given</div>
            </div>
            <div className="card stat">
              <div className="label">Mobile money</div>
              <div className="value">
                <Figure ready={!!takings} w="9ch">{money(mobileTaken)}</Figure>
              </div>
            </div>
            <div className="card stat">
              <div className="label">Card takings</div>
              <div className="value">
                <Figure ready={!!current} w="9ch">
                  {current && money(current.card_total)}
                </Figure>
              </div>
            </div>
            <div className="card stat">
              <div className="label">Medical aid</div>
              <div className="value">
                <Figure ready={!!current} w="9ch">
                  {current && money(current.medical_aid_total)}
                </Figure>
              </div>
            </div>
            <div className="card stat">
              <div className="label">Transactions</div>
              <div className="value">
                <Figure ready={!!current} w="3ch">{current?.sales_count}</Figure>
              </div>
              <div className="hint">
                since{" "}
                <Figure ready={!!current} w="14ch">
                  {current && fmtDateTime(current.opened_at)}
                </Figure>
              </div>
            </div>
          </div>

          <div className="card">
            <h3>Takings by currency</h3>
            <p className="muted">
              Each currency has its own drawer. Cash is shown net of change,
              because change leaves the drawer in whichever currency it was given.
            </p>
            {takingsUnknown ? (
              <div className="empty">
                <b>This shift&rsquo;s takings could not be read</b>
                <p>
                  That is not a statement that no money has come in. Reload the
                  page before counting a drawer against it.
                </p>
              </div>
            ) : takings && takings.currencies.length === 0 ? (
              <div className="empty">
                Nothing has been taken on this shift yet, so every drawer still
                holds what was counted into it.
              </div>
            ) : (
              <table>
                <thead>
                  <tr><Th>Currency</Th><Th className="num">Opening float</Th><Th className="num">Cash (net)</Th>
                    <Th className="num">Card</Th><Th className="num">Mobile money</Th>
</tr>
                </thead>
                {!takings ? (
                  <GhostRows cols={5} rows={2}
                             widths={["6ch", "8ch", "8ch", "8ch", "8ch"]} />
                ) : (
                <tbody>
                  {takings.currencies.map((c) => (
                    <tr key={c.currency}>
                      <td>
                        <b>{c.currency}</b>
                        {c.is_base && <span className="badge muted" style={{ marginLeft: 8 }}>base</span>}
                      </td>
                      <td className="num">{c.opening_float.toFixed(2)}</td>
                      <td className="num">{c.cash.toFixed(2)}</td>
                      <td className="num">{c.card.toFixed(2)}</td>
                      <td className="num">{c.mobile_money.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
                )}
              </table>
            )}
          </div>

          {/* Read against the sheet they fill in by hand, which has a column
              per wallet and per bank rather than one for "mobile money". */}
          <div className="card">
            <h3>What it came in on</h3>
            <p className="muted">
              EcoCash and Omari settle separately, and so do the banks behind
              a swipe. This is the same split as the teller sheet.
            </p>
            {takingsUnknown ? (
              <div className="empty">
                What the money came in on could not be read. Reload the page
                before reading this against a teller sheet.
              </div>
            ) : takings && (takings.instruments?.length ?? 0) === 0 ? (
              <div className="empty">
                No payment on this shift names a wallet or a bank yet.
              </div>
            ) : (
              <table className="dt dt-wide">
                <thead>
                  <tr>
                    <Th>Instrument</Th><Th>Currency</Th>
                    <Th className="num">Payments</Th>
                    <Th className="num">Taken</Th>
                    {/* The base currency is this pharmacy's own setting, so the
                        code waits and the word that makes the column readable
                        does not. */}
                    <th className="num">
                      In <Figure ready={!!takings} w="4ch">{takings?.base_currency}</Figure>
                    </th>
                  </tr>
                </thead>
                {!takings ? (
                  <GhostRows cols={5} rows={3} secondLine={[0]}
                             widths={["14ch", "6ch", "4ch", "8ch", "8ch"]} />
                ) : (
                <tbody>
                  {(takings.instruments ?? []).map((i, n) => (
                    <tr key={n}>
                      <td>
                        <b>{i.instrument || METHOD_LABEL[i.method] || i.method}</b>
                        {i.instrument && (
                          <div className="muted small">
                            {METHOD_LABEL[i.method] ?? i.method}
                          </div>
                        )}
                        {/* Said rather than left blank: a swipe with no bank
                            on it cannot be matched to a settlement. */}
                        {!i.instrument && i.method !== "cash" && (
                          <div className="muted small">not named on the sale</div>
                        )}
                      </td>
                      <td>{i.currency}</td>
                      <td className="num">{i.count}</td>
                      <td className="num">{i.amount.toFixed(2)}</td>
                      <td className="num">{money(i.in_base)}</td>
                    </tr>
                  ))}
                </tbody>
                )}
              </table>
            )}
          </div>

          {/* The count itself needs a shift to count, so it waits for one
              rather than being ghosted: there is no drawer to type into
              until the till has said which one is open. */}
          {current && <CashUp shiftId={current.id} onCounted={load} />}

        </>
      ) : (
        <div className="card">
          <h3>Start a shift</h3>
          <p className="muted">Count your opening float, then open a shift so every sale you take is attributed to it.</p>
          <form onSubmit={openShift} style={{ maxWidth: 320, marginTop: 12 }}>
            <div className="field">
              <label>Opening float</label>
              <input type="number" step="0.01" value={openFloat} onChange={(e) => setOpenFloat(e.target.value)} />
            </div>
            {/* Asked now, not at cash-up. The run number is allocated per till
                when the shift opens, so the run has an identity while it is
                still trading rather than only once the money is counted. */}
            <div className="field">
              <label>Till</label>
              <input
                value={till} onChange={(e) => setTill(e.target.value)}
                placeholder="e.g. 1"
              />
            </div>
            <div className="field">
              <label>Drawer <span className="muted">(optional)</span></label>
              <input value={draw} onChange={(e) => setDraw(e.target.value)} />
            </div>
            <button disabled={busy}>{busy ? "Opening…" : "Open shift"}</button>
          </form>
        </div>
      )}

      {/* Sits with the drawer it affects rather than in an admin screen: the
          cash-up counts petty cash into what the till should hold. */}
      <PettyCash />

      <div className="card">
        <h3>Shift history</h3>
        <Refreshable
          loading={loading}
          hasData={history.length > 0}
          skeleton={<TableSkeleton cols={10} rows={5}
            headers={["Cashier", "Run", "Opened", "Closed", "Float", "Expected",
                      "Counted", "Variance", "Sales", "Notes"]}
            widths={["14ch", "8ch", "12ch", "12ch", "8ch", "8ch", "8ch", "8ch", "8ch", "10ch"]} />}
        >
        {/* Ten columns wanting 1,128px in a 1,002px card. Everything that
            knows its width says so; the cashier's name and the note take what
            is left, and the table carries a floor so the two of them are not
            squeezed to 45px each. */}
        <table className="sh-history">
          <thead>
            <tr>
              <Th>Cashier</Th>
              <Th className="sh-run-col">Run</Th>
              <Th className="sh-when">Opened</Th>
              <Th className="sh-when">Closed</Th>
              <Th className="num sh-float">Float</Th>
              <Th className="num sh-money">Expected</Th>
              <Th className="num sh-money">Counted</Th>
              <Th className="num sh-var">Variance</Th>
              <Th className="num sh-sales">Sales</Th>
              <Th>Notes</Th>
            </tr>
          </thead>
          <tbody>
            {history.map((s) => (
              <RowLink key={s.id} to={`/shifts/${s.id}`}
                       prefetch={prefetchRoute}>
                <td><EntityLink kind="staff" id={s.user_id}>
                  <Person className="strong" name={s.user?.full_name ?? String(s.user_id)} />
                </EntityLink></td>
                {/* A run number without its till is meaningless, and every shift
                    opened before runs were numbered has neither. Both absent
                    shows a dash rather than "Till  · run 0". */}
                <td className="mono sh-run">
                  {s.till_no || s.run_number
                    ? [s.till_no && `Till ${s.till_no}`, s.run_number && `run ${s.run_number}`]
                        .filter(Boolean).join(" · ")
                    : "none"}
                </td>
                <td>{fmtDateTime(s.opened_at)}</td>
                <td>
                  {s.closed_at ? fmtDateTime(s.closed_at) : (
                    /* A SHIFT LEFT OPEN, AND THE ONLY SCREEN THAT COULD SAY SO.
                       Reconciliation counts these and calls them "run(s) closed
                       without the drawer being counted", and its card points
                       here. Here they were an inert badge. Counting one is a
                       shift that ended without anybody counting the money:
                       somebody went home, the till rolled over, the count was
                       never taken. The endpoint has always accepted any shift
                       id and `CashUp` has always taken one as a prop; this
                       screen simply never passed anything but its own. */
                    <span className="row-actions">
                      <span className="badge">Open</span>
                      <button className="btn sm" onClick={(e) => {
                        e.preventDefault(); e.stopPropagation(); setCounting(s);
                      }}>
                        Count it
                      </button>
                    </span>
                  )}
                </td>
                <td className="num">{money(s.opening_float)}</td>
                <td className="num">{money(s.expected_cash)}</td>
                <td className="num">{money(s.counted_cash)}</td>
                <td className="num">
                  {s.status === "closed" && (
                    <span className={`badge ${Math.abs(s.variance) < 0.005 ? "ok" : "danger"}`}>
                      {s.variance > 0 ? "+" : ""}{money(s.variance)}
                    </span>
                  )}
                </td>
                <td className="num">{s.sales_count}</td>
                <td className="muted">{s.notes}</td>
              </RowLink>
            ))}
          </tbody>
        </table>
        {historyUnknown && !loading && (
          <div className="empty">
            <b>The shift history could not be read</b>
            <p>
              This is not a statement that no till has ever been cashed up.
              Reload the page before checking a cash-up against it.
            </p>
          </div>
        )}
        {!historyUnknown && history.length === 0 && !loading && (
          <div className="empty">
            <b>No shifts recorded yet</b>
            <p>
              A shift is opened when somebody takes the till and closed when
              they count it. The history is what a cash-up is checked against.
            </p>
          </div>
        )}
        </Refreshable>
      </div>

      {/* Counting somebody else's shift, in a dialogue that says whose it was.
          A blind count is still a blind count: `CashUp` shows the drawer's
          expected figure only after the count is committed, and the server
          refuses a second one. */}
      {counting && (
        <div className="modal-backdrop" onClick={() => setCounting(null)}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="imp-head">
              <h2>
                Count {counting.user?.full_name ?? "that"}&rsquo;s drawer
              </h2>
              <button className="btn ghost sm" onClick={() => setCounting(null)}
                      aria-label="Close">
                <X size={14} />
              </button>
            </div>
            <p className="muted">
              Opened {fmtDateTime(counting.opened_at)} and never counted. The
              count stands on its own: what was expected is shown once it is
              committed, and it cannot be taken twice.
            </p>
            <CashUp shiftId={counting.id}
                    onCounted={() => { setCounting(null); load(); }} />
          </div>
        </div>
      )}
    </>
  );
}
