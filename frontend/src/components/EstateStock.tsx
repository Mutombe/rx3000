/** Moving stock across the estate, from the one screen that can see all of it.
 *
 *  The Branches page can already send stock, one shop at a time, from the point
 *  of view of whoever is standing in it. Head office has the opposite problem:
 *  it is standing nowhere, and the question it asks is "who has this and who
 *  needs it", which no per-branch screen answers.
 *
 *  SHOW BOTH SHELVES BEFORE ANYTHING MOVES.
 *
 *  A transfer is a deduction from one shop and an addition to another, and
 *  until it is sent neither of those has happened. So the numbers are on screen
 *  before the button is pressed, with the change against each: 128 becomes 108,
 *  4 becomes 24. Somebody who can see that does not send twenty of something a
 *  branch only has twelve of, and does not need to be told off by a validation
 *  message afterwards.
 *
 *  Stock in transit is shown as what it is: gone from one shelf and not yet on
 *  the other. That gap is real, it lasts as long as the drive takes, and it is
 *  the only period in which the group total on a product record is wrong.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Package, Truck, Warning } from "@phosphor-icons/react";

import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { useConfirm } from "./Confirm";
import { useToast } from "./Toast";
import { TableSkeleton } from "./Skeleton";
import Th from "./Th";

interface Held {
  branch_id: number; branch: string; code: string; on_hand: number;
}
interface Holdings {
  product_id: number; product: string; strength: string;
  units_per_pack: number; branches: Held[]; group_total: number;
}
interface Transit {
  id: number; reference: string; from_branch: string; to_branch: string;
  product: string; quantity: number; despatched_at: string; days_in_transit: number;
}

export default function EstateStock() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ id: number; name: string; strength: string }[]>([]);
  const [holdings, setHoldings] = useState<Holdings | null>(null);
  const [looking, setLooking] = useState(false);

  const [fromId, setFromId] = useState<number | null>(null);
  const [toId, setToId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState("");
  const [notes, setNotes] = useState("");

  const [transit, setTransit] = useState<Transit[] | null>(null);
  const toast = useToast();
  const confirm = useConfirm();

  const loadTransit = useCallback(() => {
    api.get<Transit[]>("/api/branches/transfers/in-transit")
      .then(setTransit).catch(() => setTransit([]));
  }, []);
  useEffect(loadTransit, [loadTransit]);

  // Searching the catalogue, with the answer dropped if the typing moved on.
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits([]); return; }
    let live = true;
    const t = window.setTimeout(() => {
      api.get<any[]>(`/api/products?q=${encodeURIComponent(term)}&limit=6`)
        .then((rows) => { if (live) setHits(rows.map((r) => ({ id: r.id, name: r.name, strength: r.strength ?? "" }))); })
        .catch(() => { if (live) setHits([]); });
    }, 220);
    return () => { live = false; window.clearTimeout(t); };
  }, [q]);

  function pick(id: number) {
    setLooking(true);
    setHits([]);
    api.get<Holdings>(`/api/branches/transfers/holdings?product_id=${id}`)
      .then((h) => {
        setHoldings(h);
        setQ(`${h.product} ${h.strength}`.trim());
        // The branch with the most is the obvious sender and the one with the
        // least the obvious receiver. Both stay changeable; this is only so the
        // common case needs no clicks.
        const sorted = [...h.branches].sort((a, b) => b.on_hand - a.on_hand);
        setFromId(sorted[0]?.branch_id ?? null);
        setToId(sorted.length > 1 ? sorted[sorted.length - 1].branch_id : null);
      })
      .catch((e) => toast.error(errorText(e, "That product could not be read.")))
      .finally(() => setLooking(false));
  }

  const moving = Math.max(0, Math.floor(Number(quantity) || 0));
  const sender = holdings?.branches.find((b) => b.branch_id === fromId) ?? null;
  const receiver = holdings?.branches.find((b) => b.branch_id === toId) ?? null;
  const tooMuch = !!sender && moving > sender.on_hand;
  const ready = !!holdings && !!sender && !!receiver && fromId !== toId
                && moving > 0 && !tooMuch;

  async function send() {
    if (!ready || !holdings) return;
    const ok = await confirm({
      title: `Send ${moving} to ${receiver!.branch}?`,
      body: `${sender!.branch} goes from ${sender!.on_hand} to ${sender!.on_hand - moving} `
          + `now. ${receiver!.branch} goes from ${receiver!.on_hand} to `
          + `${receiver!.on_hand + moving} when somebody there books it in.`,
      confirmLabel: "Send it",
    });
    if (!ok) return;
    try {
      const said = await api.post<{ reference: string }>("/api/branches/transfers", {
        from_branch_id: fromId, to_branch_id: toId,
        product_id: holdings.product_id, quantity: moving, notes,
      });
      toast.ok(`${said.reference} is on its way.`);
      setQuantity(""); setNotes("");
      pick(holdings.product_id);          // the shelves, as they now are
      loadTransit();
    } catch (e) {
      toast.error(errorText(e, "That transfer could not be sent."));
    }
  }

  async function receive(row: Transit) {
    const ok = await confirm({
      title: `Book in ${row.quantity} of ${row.product}?`,
      body: `It goes onto ${row.to_branch}'s shelf now, with the batch numbers `
          + `and expiry dates it left ${row.from_branch} with.`,
      confirmLabel: "It has arrived",
    });
    if (!ok) return;
    try {
      await api.post(`/api/branches/transfers/${row.id}/receive`);
      toast.ok(`${row.reference} is on the shelf at ${row.to_branch}.`);
      loadTransit();
      if (holdings) pick(holdings.product_id);
    } catch (e) {
      toast.error(errorText(e, "That could not be booked in."));
    }
  }

  const options = (holdings?.branches ?? []).map((b) => ({
    value: String(b.branch_id), label: `${b.branch} · ${b.on_hand}`,
  }));

  return (
    <div className="es">
      <section className="card">
        <h3 className="card-title"><Package size={18} /> Move stock between branches</h3>
        <p className="muted small es-say">
          Find the medicine, and every shop that holds any of it is listed with
          what is on its shelf. Nothing moves until you send it.
        </p>

        <div className="es-find">
          <input
            type="search" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="Medicine name…" aria-label="Find a medicine"
          />
          {hits.length > 0 && (
            <ul className="es-hits" role="listbox">
              {hits.map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => pick(h.id)}>
                    <b>{h.name}</b> <span className="muted">{h.strength}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {looking && <TableSkeleton cols={3} rows={3} rowHeight={44} />}

        {holdings && !looking && (
          <>
            <div className="dt-scroll">
              <table className="dt es-shelves">
                <thead>
                  <tr><Th>Branch</Th><Th className="num">On the shelf</Th>
                    <Th className="num">After this move</Th></tr>
                </thead>
                <tbody>
                  {holdings.branches.map((b) => {
                    const delta = b.branch_id === fromId ? -moving
                      : b.branch_id === toId ? moving : 0;
                    return (
                      <tr key={b.branch_id} className={delta ? "is-moving" : undefined}>
                        <td>
                          <b>{b.branch}</b>
                          {b.code && <span className="muted small"> {b.code}</span>}
                        </td>
                        <td className="num">{b.on_hand}</td>
                        <td className="num">
                          {delta ? (
                            <span className={delta < 0 ? "es-down" : "es-up"}>
                              {b.on_hand + delta}
                              <span className="es-delta">
                                {delta < 0 ? "" : "+"}{delta}
                              </span>
                            </span>
                          ) : <span className="muted">Unchanged</span>}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="es-total">
                    <td>Across the group</td>
                    <td className="num">{holdings.group_total}</td>
                    <td className="num muted">
                      {moving ? "the same, once it arrives" : "unchanged"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="es-move">
              <label className="es-pick">
                From
                <Select value={String(fromId ?? "")} onChange={(v) => setFromId(Number(v) || null)}
                        options={options} ariaLabel="Sending branch" />
              </label>
              <ArrowRight size={16} className="es-arrow" aria-hidden="true" />
              <label className="es-pick">
                To
                <Select value={String(toId ?? "")} onChange={(v) => setToId(Number(v) || null)}
                        options={options.filter((o) => Number(o.value) !== fromId)}
                        ariaLabel="Receiving branch" />
              </label>
              <label className="es-qty">
                How many
                <input type="number" min={1} value={quantity} inputMode="numeric"
                       onChange={(e) => setQuantity(e.target.value)} />
              </label>
              <label className="es-notes">
                Why, or anything the other shop should know
                <input value={notes} onChange={(e) => setNotes(e.target.value)}
                       placeholder="optional" />
              </label>
              <BusyButton className="btn primary" disabled={!ready} onClick={send}
                          busyLabel="Sending…">
                Send it
              </BusyButton>
            </div>

            {tooMuch && sender && (
              <p className="alert warn es-warn">
                <Warning size={15} weight="fill" />
                {sender.branch} holds {sender.on_hand}. Send that or less, or
                move some there first.
              </p>
            )}
            {fromId === toId && fromId !== null && (
              <p className="alert warn es-warn">
                <Warning size={15} weight="fill" />
                A transfer needs two different branches.
              </p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <h3 className="card-title"><Truck size={18} /> On the road</h3>
        <p className="muted small es-say">
          Off one shelf and not yet on the other. While a transfer sits here the
          group total on the product record counts it, and neither branch does.
        </p>
        {!transit ? <TableSkeleton cols={6} rows={3} rowHeight={48} />
         : transit.length === 0 ? (
          <div className="empty">
            <b>Nothing is in transit.</b>
            <p>Every transfer that has been sent has been booked in at the other end.</p>
          </div>
        ) : (
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr><Th>Reference</Th><Th>Medicine</Th><Th className="num">Qty</Th>
                  <Th>From</Th><Th>To</Th><Th className="num">Days out</Th>
                  <th className="actions" /></tr>
              </thead>
              <tbody>
                {transit.map((t) => (
                  <tr key={t.id} className={t.days_in_transit >= 7 ? "is-off" : undefined}>
                    <td className="mono">{t.reference}</td>
                    <td>{t.product}</td>
                    <td className="num">{t.quantity}</td>
                    <td>{t.from_branch}</td>
                    <td>{t.to_branch}</td>
                    <td className={`num${t.days_in_transit >= 7 ? " cu-diff" : ""}`}>
                      {t.days_in_transit}
                    </td>
                    <td className="actions">
                      <BusyButton className="btn small" onClick={() => receive(t)}
                                  busyLabel="Booking in…">
                        It has arrived
                      </BusyButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
