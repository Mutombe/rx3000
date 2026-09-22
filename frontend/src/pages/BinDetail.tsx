/** One shelf: what is on it, and everything you can do standing in front of it.
 *
 *  WHY THIS IS A PAGE AND NOT A PANEL
 *
 *  It used to open inside the Bins tab: click a bin, a drawer appears under
 *  the grid, and the address bar still says Inventory. Three things are lost
 *  that way and all of them matter to somebody doing a shelf walk. The view
 *  cannot be linked, so "check bin A14" has to be said as directions rather
 *  than a link. It cannot be reloaded or come back from the browser's back
 *  button. And a panel has nowhere to put the actions a person actually wants
 *  when they are standing at the shelf, so it had almost none.
 *
 *  EVERY FIGURE HERE GOES SOMEWHERE
 *
 *  A line name opens the product. A shelf named under "also kept in" opens
 *  that shelf. A count that is short leads to what to do about it. That is
 *  the whole idea: a screen showing a fact that cannot be followed is a dead
 *  end, and a person who hits one goes back to asking a colleague.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, ArrowsLeftRight, Eraser, PencilSimple, Printer,
} from "@phosphor-icons/react";

import { api, errorText, money } from "../api";
import BusyButton from "../components/BusyButton";
import { useConfirm } from "../components/Confirm";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Units } from "./BinsUnassigned";
import { useToast } from "../components/Toast";

interface Line {
  product_id: number;
  name: string;
  stock_code: string;
  pack_size: string;
  on_hand: number;
  reorder_level: number;
  short: boolean;
  empty: boolean;
  value: number;
  bin: string;
  /** False when this shelf is the line's second or third home. The money is
   *  counted against the primary shelf only, so every bin total adds up to
   *  the stock valuation rather than double counting. */
  primary: boolean;
  also_in: string[];
}

interface Contents {
  bin: string;
  lines: Line[];
  units: number;
  value: number;
  short: number;
}

export default function BinDetail() {
  const { bin = "" } = useParams();
  const shelf = decodeURIComponent(bin);
  const toast = useToast();
  const confirm = useConfirm();
  const go = useNavigate();

  const [data, setData] = useState<Contents | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [moving, setMoving] = useState(false);
  const [renaming, setRenaming] = useState(false);

  const load = useCallback(() => {
    api.get<Contents>(`/api/stock/bins/${encodeURIComponent(shelf)}`)
      .then((r) => { setData(r); setPicked(new Set()); })
      .catch((e) => setError(errorText(e, "That shelf could not be read.")));
  }, [shelf]);
  useEffect(load, [load]);

  function toggle(id: number) {
    setPicked((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  /** Take everything off this shelf. Asked for rather than defaulted into:
   *  an empty box in a move form looks exactly the same as meaning to clear
   *  one, and only one of those should empty a shelf. */
  async function clearShelf() {
    const sure = await confirm({
      title: `Take every line off ${shelf}?`,
      body: `${data?.lines.length ?? 0} line(s) become unplaced. The stock does `
          + "not move and the counts do not change; what is lost is knowing "
          + "where to send somebody to fetch it.",
      confirmLabel: "Clear the shelf",
      destructive: true,
    });
    if (!sure) return;
    try {
      const said = await api.post<{ message: string }>("/api/stock/bins/move", {
        product_ids: data?.lines.map((l) => l.product_id) ?? [],
        clear: true,
        reason: `Cleared ${shelf}`,
      });
      toast.ok(said.message);
      go("/stock?tab=bins");
    } catch (e) {
      toast.error(errorText(e, "That shelf could not be cleared."));
    }
  }

  const chosen = [...picked];
  const worth = data?.lines
    .filter((l) => picked.has(l.product_id))
    .reduce((sum, l) => sum + l.value, 0) ?? 0;

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "Bins", to: "/stock?tab=bins" },
              { label: `Bin ${shelf}` }]}
      eyebrow="Shelf location"
      title={`Bin ${shelf}`}
      subtitle={data
        ? `${data.lines.length} line(s), ${data.units.toLocaleString()} unit(s)`
        : undefined}
      loading={!data && !error}
      error={error}
      actions={
        <>
          <button type="button" className="btn secondary"
                  onClick={() => setRenaming(true)}>
            <PencilSimple size={13} /> Rename or merge
          </button>
          <button type="button" className="btn secondary"
                  onClick={() => window.print()}>
            <Printer size={13} /> Print this shelf
          </button>
          <Link to="/stock?tab=bins" className="btn secondary">
            <ArrowLeft size={13} weight="bold" /> Bins
          </Link>
        </>
      }
      facts={data ? [
        { label: "Lines", value: data.lines.length,
          hint: data.lines.length ? "on this shelf" : "nothing is kept here" },
        // A shelf whose counts add up to less than nothing is not a shelf
        // holding a negative number of boxes; it is a record that is wrong.
        { label: "Units", value: data.units < 0
            ? `${Math.abs(data.units).toLocaleString()} over-issued`
            : data.units.toLocaleString(),
          hint: data.units < 0
            ? "more has gone out than was booked in, so this needs counting"
            : "counted on hand",
          tone: data.units < 0 ? "bad" : undefined },
        // Only the lines whose MAIN shelf this is. Said out loud, because a
        // bin total that claimed a line kept in two places would make the
        // directory add up to more than the pharmacy owns.
        { label: "Worth", value: money(data.value),
          hint: "at cost, for lines kept mainly here" },
        { label: "Short", value: data.short,
          hint: data.short ? "at or below the reorder level" : "nothing is short",
          tone: data.short ? "warn" : undefined },
      ] : []}
    >
      {data && (
        <>
          {data.lines.length === 0 && (
            <div className="alert">
              Nothing is recorded on this shelf. A line is put here from its
              own page, or by moving it from another bin.
            </div>
          )}

          <Panel
            title="What is on this shelf"
            count={data.lines.length}
            empty="Nothing is kept here."
            aside={data.lines.length > 0 ? (
              <button type="button" className="btn secondary small"
                      onClick={clearShelf}>
                <Eraser size={13} /> Clear the shelf
              </button>
            ) : undefined}
          >
            <div className="dt-scroll">
              <table className="dt bin-table dt-wide">
                <thead>
                  <tr>
                    <th className="bulk-tick" />
                    <th className="col-med">Line</th>
                    <th className="mono col-code">Code</th>
                    <th className="num">On hand</th>
                    <th className="num">Reorder at</th>
                    <th className="num">Worth</th>
                    <th className="col-when">Also kept in</th>
                  </tr>
                </thead>
                <tbody>
                  {data.lines.map((l) => (
                    <tr key={l.product_id}
                        className={l.short ? "row-flag" : undefined}>
                      <td className="bulk-tick">
                        <input type="checkbox" checked={picked.has(l.product_id)}
                               aria-label={`Choose ${l.name}`}
                               onChange={() => toggle(l.product_id)} />
                      </td>
                      <td>
                        {/* The line opens the product, which is where its
                            batches, its movements and its suppliers are. */}
                        <EntityLink to={`/products/${l.product_id}`}>
                          {l.name}
                        </EntityLink>
                        {!l.primary && (
                          <div className="muted small">
                            kept mainly in bin {l.bin}, so its worth is counted
                            there
                          </div>
                        )}
                      </td>
                      <td className="mono small">
                        {l.stock_code || <span className="muted">none</span>}
                      </td>
                      <td className="num"><Units n={l.on_hand} /></td>
                      <td className="num">{l.reorder_level}</td>
                      <td className="num">
                        {l.primary ? money(l.value)
                                   : <span className="muted">counted elsewhere</span>}
                      </td>
                      <td>
                        {/* Another shelf is another page. Following one is the
                            whole point of writing them down. */}
                        {l.also_in.length
                          ? l.also_in.map((other, i) => (
                              <span key={other}>
                                {i > 0 && ", "}
                                <Link to={`/bins/${encodeURIComponent(other)}`}
                                      className="btn-link">
                                  {other}
                                </Link>
                              </span>
                            ))
                          : <span className="muted">nowhere else</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* Acting on a selection, where the selection is. A shelf walk moves
              a handful of lines at a time and doing it from each product's own
              form is why the field stayed empty in the first place. */}
          {chosen.length > 0 && (
            <div className="card bin-foot">
              <div>
                <b>{chosen.length} line(s) chosen</b>
                {worth > 0 && <span className="muted"> · {money(worth)}</span>}
                <div className="muted small">
                  Moving a line records where it went and who moved it.
                </div>
              </div>
              <div className="bin-foot-acts">
                <button type="button" className="btn secondary"
                        onClick={() => setPicked(new Set())}>
                  Clear the choice
                </button>
                <button type="button" className="btn primary"
                        onClick={() => setMoving(true)}>
                  <ArrowsLeftRight size={13} /> Move to another shelf
                </button>
              </div>
            </div>
          )}

          {moving && (
            <MoveLines from={shelf} ids={chosen}
                       onClose={() => setMoving(false)}
                       onDone={() => { setMoving(false); load(); }} />
          )}
          {renaming && (
            <RenameShelf bin={shelf} onClose={() => setRenaming(false)}
                         onDone={(to) => {
                           setRenaming(false);
                           go(`/bins/${encodeURIComponent(to)}`);
                         }} />
          )}
        </>
      )}
    </RecordPage>
  );
}

/** Put the chosen lines on a different shelf. */
function MoveLines({ from, ids, onClose, onDone }: {
  from: string;
  ids: number[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [to, setTo] = useState("");
  const [slot, setSlot] = useState(1);

  async function go() {
    try {
      const said = await api.post<{ message: string }>("/api/stock/bins/move", {
        product_ids: ids, bin: to, slot,
        reason: `Moved from ${from}`,
      });
      toast.ok(said.message);
      onDone();
    } catch (e) {
      toast.error(errorText(e, "Those lines could not be moved."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Move {ids.length} line(s) off {from}</h2>
        <p className="muted">
          The stock does not move and the counts do not change. What changes is
          where somebody is sent to fetch it.
        </p>

        <div className="field">
          <label htmlFor="bin-to">The shelf they go to</label>
          <input id="bin-to" value={to} autoFocus maxLength={20}
                 onChange={(e) => setTo(e.target.value)}
                 placeholder="A14" />
        </div>

        <div className="field">
          <label htmlFor="bin-slot">Which of the line's shelves this sets</label>
          {/* A line kept in the dispensary and the back store has two, and
              moving it without saying which is how the back store location
              gets quietly overwritten. */}
          <select id="bin-slot" className="st-control" value={slot}
                  onChange={(e) => setSlot(Number(e.target.value))}>
            <option value={1}>Its main shelf</option>
            <option value={2}>Its second shelf</option>
            <option value={3}>Its third shelf</option>
          </select>
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={go} disabled={!to.trim()}
                      busyLabel="Moving…">
            Move them
          </BusyButton>
        </div>
      </div>
    </div>
  );
}

/** Rename this shelf, which merges it where the new name already exists. */
function RenameShelf({ bin, onClose, onDone }: {
  bin: string;
  onClose: () => void;
  onDone: (to: string) => void;
}) {
  const toast = useToast();
  const [to, setTo] = useState(bin);

  async function go() {
    try {
      const said = await api.post<{ message: string }>("/api/stock/bins/rename", {
        from: bin, to,
      });
      toast.ok(said.message);
      onDone(to.trim());
    } catch (e) {
      toast.error(errorText(e, "That shelf could not be renamed."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Rename bin {bin}</h2>
        <p className="muted">
          Every line on this shelf follows the new name. Where that name is
          already in use the two shelves become one, which is how two spellings
          of the same place get put right.
        </p>
        <div className="field">
          <label htmlFor="bin-new">The new name</label>
          <input id="bin-new" value={to} autoFocus maxLength={20}
                 onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={go}
                      disabled={!to.trim() || to.trim() === bin}
                      busyLabel="Renaming…">
            Rename it
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
