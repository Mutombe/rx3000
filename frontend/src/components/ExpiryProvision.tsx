/** The provision against short-dated stock.
 *
 *  Inventory is carried at the lower of cost and what it will realistically
 *  fetch. A shelf expiring in three weeks will not fetch cost, and the pharmacy
 *  has already lost the difference whether or not anybody has written it down.
 *  Without this the ledger carried every batch at full cost until the day it
 *  expired and then took the whole loss at once — overstating the business every
 *  month, then taking a lump in whichever month somebody happened to write off.
 *
 *  The screen says what it would post *before* anybody presses anything. An
 *  accounting routine whose effect is only visible afterwards is one nobody runs
 *  a second time.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import { useConfirm } from "./Confirm";
import { EmptyRow } from "./Empty";
import { useToast } from "./Toast";
import { EntityLink, TableSearch, useSearch } from "./Filters";
import { Figure, GhostRows } from "./Skeleton";
import Th from "./Th";

interface Item {
  batch_id: number; product: string; batch_number: string;
  expiry: string | null; quantity: number; unit_cost: number;
  days_left: number; rate: number; at_cost: number; provision: number; reason: string;
}
interface Band {
  rate: number; batches: number; at_cost: number; provision: number; reason: string;
}
interface Entry {
  id: number; reference: string; entry_date: string; description: string; movement: number;
}
interface State {
  items: Item[];
  bands: Record<string, Band>;
  stock_at_risk: number;
  required: number;
  carried: number;
  movement: number;
  history: Entry[];
}

export default function ExpiryProvision() {
  const [state, setState] = useState<State | null>(null);
  /* Every batch carrying a provision. Read to answer "why is this line
     provided for" about one medicine. */
  const { q, setQ, shown } = useSearch(state?.items ?? [], (i) =>
    [i.product, i.batch_number, i.reason]);
  const [failed, setFailed] = useState("");
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(() =>
    api.get<State>("/api/ledger/expiry-provision")
      .then((s) => { setState(s); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The provision could not be worked out."))),
  []);

  useEffect(() => { load(); }, [load]);

  async function postIt() {
    if (!state) return;
    const up = state.movement > 0;
    const ok = await confirm({
      title: up ? "Charge the provision?" : "Release the provision?",
      body: (
        <>
          {up
            ? <>This charges <b>{money(state.movement)}</b> against profit and writes
                the stock down to what it is likely to fetch.</>
            : <>Stock at risk has fallen, so <b>{money(Math.abs(state.movement))}</b> comes
                back. The provision is reduced to {money(state.required)}.</>}
          {" "}It posts the movement, not the whole balance, so running it again
          today does nothing.
        </>
      ),
      confirmLabel: up ? "Charge it" : "Release it",
    });
    if (!ok) return;
    try {
      const r = await api.post<{ message: string }>("/api/ledger/expiry-provision", {});
      toast.ok(r.message);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be posted."));
    }
  }

  if (failed) return <div className="alert error">{failed}</div>;

  const nothingToDo = !!state && Math.abs(state.movement) < 0.01;

  /* SCOPED LOADING.
   *
   * "Working out the exposure…" stood in for the entire routine, so three of the
   * four band captions, the band table's whole head and the button that posts
   * the movement were all withheld, and then the screen arrived at its real
   * height in one jump. Every one of those is written here.
   *
   * The sentence under the bands and the fourth caption do wait, because they
   * are the verdict: "the provision already matches the stock on hand" and "to
   * release" are findings, and a screen that has been told nothing has found
   * nothing. So is the band table's "nothing is close to expiry" row, which is
   * why it sits inside the arm that has an answer. */
  return (
    <div className="prov">
      <div className="wc-bands">
        <div className="wl-stat">
          <b><Figure ready={!!state} w="9ch">{state && money(state.stock_at_risk)}</Figure></b>
          <span>Stock within 90 days of expiry</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!state} w="9ch">{state && money(state.required)}</Figure></b>
          <span>Provision required</span>
        </div>
        <div className="wl-stat">
          <b><Figure ready={!!state} w="9ch">{state && money(state.carried)}</Figure></b>
          <span>Already provided</span>
        </div>
        <div className={`wl-stat${!state || nothingToDo ? "" : " wc-stale"}`}>
          <b>
            <Figure ready={!!state} w="9ch">
              {state && (state.movement >= 0
                ? money(state.movement)
                : `(${money(Math.abs(state.movement))})`)}
            </Figure>
          </b>
          <span>
            <Figure ready={!!state} w="9ch">
              {state && (state.movement >= 0 ? "to charge" : "to release")}
            </Figure>
          </span>
        </div>
      </div>

      {/* Said in a sentence, because a row of four figures does not tell an owner
          what happens next. */}
      <p className="prov-said">
        <Figure ready={!!state} w="60ch">
          {state && (nothingToDo
            ? "The provision already matches the stock on hand. Nothing to post."
            : state.movement > 0
              ? `Charging ${money(state.movement)} writes this stock down to what it is likely to fetch. Until it is posted the balance sheet carries it at full cost.`
              : `Stock at risk has fallen. ${money(Math.abs(state.movement))} comes back to profit.`)}
        </Figure>
      </p>

      <BusyButton onClick={postIt} disabled={!state || nothingToDo}>
        <Figure ready={!!state} w="14ch">
          {state && (state.movement >= 0 ? "Post the charge" : "Post the release")}
        </Figure>
      </BusyButton>

      <table className="dt" style={{ marginTop: 18 }}>
        <thead>
          <tr>
            <Th>Band</Th><Th className="num">Batches</Th><Th className="num">At cost</Th>
            <Th className="num">Rate</Th><Th className="num">Provision</Th>
          </tr>
        </thead>
        {!state ? (
          <GhostRows cols={5} rows={4} secondLine={[0]}
                     widths={["60%", "30%", "50%", "30%", "50%"]} />
        ) : (
        <tbody>
          {/* Nothing short-dated is the best answer this table can give, and a
              blank one reads as the worst. */}
          {Object.keys(state.bands).length === 0 && (
            <EmptyRow cols={5} title="Nothing on the shelf is close to expiry">
              No batch falls in any band, so no provision is being made. The
              bands fill themselves as stock ages.
            </EmptyRow>
          )}
          {Object.entries(state.bands).map(([label, b]) => (
            <tr key={label}>
              <td>
                <b>{label}</b>
                {/* The judgement behind the rate, in words. These are not law:
                    IAS 2 says lower of cost and net realisable value and does not
                    say what a pharmacy can shift in sixty days. */}
                <div className="muted small">{b.reason}</div>
              </td>
              <td className="num">{b.batches}</td>
              <td className="num">{money(b.at_cost)}</td>
              <td className="num">{Math.round(b.rate * 100)}%</td>
              <td className="num">{money(b.provision)}</td>
            </tr>
          ))}
        </tbody>
        )}
      </table>

      {state && state.items.length > 0 && (
        <details className="prov-detail">
          <summary>{state.items.length} batch{state.items.length === 1 ? "" : "es"} behind this figure</summary>
          <div className="dt-scroll">
              <TableSearch value={q} onChange={setQ}
                           placeholder="Find a medicine or a batch…"
                           shown={shown.length} total={state.items.length} />
            <table className="dt sub">
              <thead>
                <tr>
                  <Th>Medicine</Th><Th>Batch</Th><Th>Expires</Th>
                  <Th className="num">Qty</Th><Th className="num">At cost</Th>
                  <Th className="num">Provision</Th>
                </tr>
              </thead>
              <tbody>
                {/* This section only exists when there ARE batches, so an empty list
                    here is always the search and never the shelf. */}
                {shown.length === 0 && (
                  <EmptyRow cols={6} title="No batch matches that">
                    {state.items.length.toLocaleString()} short-dated
                    batch{state.items.length === 1 ? " is" : "es are"} behind this
                    figure. Clear the search above to see them.
                  </EmptyRow>
                )}
                {shown.map((i) => (
                  <tr key={i.batch_id}>
                    <td>{i.product}</td>
                    <td className="mono"><EntityLink kind="batch" id={i.batch_id}>{i.batch_number || "none"}</EntityLink></td>
                    <td>
                      {i.expiry ? fmtDate(i.expiry) : "No date"}
                      <div className="muted small">
                        {i.days_left < 0 ? `${Math.abs(i.days_left)} days ago` : `in ${i.days_left} days`}
                      </div>
                    </td>
                    <td className="num">{i.quantity}</td>
                    <td className="num">{money(i.at_cost)}</td>
                    <td className="num">{money(i.provision)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {state && state.history.length > 0 && (
        <details className="prov-detail">
          <summary>{state.history.length} posting{state.history.length === 1 ? "" : "s"} on file</summary>
          <table className="dt sub">
            <thead>
              <tr><Th>Date</Th><Th>Reference</Th><Th className="num">Movement</Th></tr>
            </thead>
            <tbody>
              {state.history.map((h) => (
                <tr key={h.id}>
                  <td>{fmtDate(h.entry_date)}</td>
                  <td className="mono">{h.reference}</td>
                  <td className="num">
                    {h.movement >= 0 ? money(h.movement) : `(${money(Math.abs(h.movement))})`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
