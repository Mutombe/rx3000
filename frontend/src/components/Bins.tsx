/** The shelves, as something a pharmacy can run.
 *
 *  A bin was already on every product record and already came in on the
 *  client's own export, sixty four of them. What did not exist was any way to
 *  work with them, so the field was filled in once by an import and then never
 *  looked at again, which is the same as not having it.
 *
 *  THE NUMBER THIS SCREEN EXISTS FOR
 *
 *  Stock that is on hand and in no bin. It is paid for, it is in date, and
 *  nobody can find it, so it gets ordered again. On the client's own catalogue
 *  that is 994 lines. It is stated at the top rather than hidden behind a
 *  filter, because a pharmacy that does not know the number will not go
 *  looking for it.
 *
 *  WHY MOVING IS A LIST AND NOT A FORM FIELD
 *
 *  The real act is a list. Somebody reorganises the dispensary and forty lines
 *  move at once, and doing that one product form at a time is exactly why the
 *  field stayed empty. So rows tick and one button moves all of them.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Link } from "react-router-dom";

import { api, errorText, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { EntityLink } from "./Filters";
import { useToast } from "./Toast";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";

interface Bin {
  bin: string;
  lines: number;
  units: number;
  value: number;
  spellings: string[];
  /** Lines kept here as well as somewhere else. Their stock is valued at
   *  their main shelf, so this bin counts them to walk and not to price. */
  also: number;
}

interface Directory {
  bins: Bin[];
  lines: number;
  units: number;
  value: number;
  unbinned: number;
  unbinned_units: number;
}

interface Line {
  product_id: number;
  name: string;
  stock_code: string;
  pack_size?: string;
  on_hand: number;
  reorder_level?: number;
  short?: boolean;
  empty?: boolean;
  value: number;
  primary?: boolean;
  also_in?: string[];
}

export default function Bins() {
  const toast = useToast();
  const [dir, setDir] = useState<Directory | null>(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  /** Which shelf is open. "" is the directory; "?" is the unbinned list. */
  const [open, setOpen] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState("");
  const [why, setWhy] = useState("");
  /** WHICH OF THE THREE PLACES A LINE IS KEPT.
   *
   *  The endpoint has taken a slot since a line could be kept in three
   *  places, and this screen never sent one — so every move wrote the primary
   *  bin. A line kept in the dispensary AND the back store could only have
   *  its second place set on the product form, and moving it "to bin 14" here
   *  silently overwrote the dispensary one. */
  const [slot, setSlot] = useState(1);
  const [renaming, setRenaming] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api.get<Directory>("/api/stock/bins")
      .then(setDir)
      .catch((e) => toast.error(errorText(e, "The bins could not be read.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  const openShelf = useCallback((bin: string) => {
    setOpen(bin);
    setPicked(new Set());
    setBusy(true);
    const url = bin === "?"
      ? "/api/stock/bins/unbinned"
      : `/api/stock/bins/${encodeURIComponent(bin)}`;
    api.get<{ lines: Line[] }>(url)
      .then((r) => setLines(r.lines))
      .catch((e) => toast.error(errorText(e, "That shelf could not be read.")))
      .finally(() => setBusy(false));
  }, [toast]);

  const shown = useMemo(() => {
    const term = q.trim().toUpperCase();
    if (!dir) return [];
    if (!term) return dir.bins;
    return dir.bins.filter((b) => b.bin.toUpperCase().includes(term));
  }, [dir, q]);

  function toggle(id: number) {
    setPicked((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function move(clear = false) {
    const ids = [...picked];
    if (!ids.length) return;
    const where = clear ? "" : target.trim();
    if (!clear && !where) {
      toast.error("Give the bin these are moving to.");
      return;
    }

    // Optimistic, and honestly so: the rows leave this shelf on the click
    // because they have left it. The list they are joining is reloaded from
    // the server, which is the part that can disagree.
    const moving = lines.filter((l) => picked.has(l.product_id));
    setLines((all) => all.filter((l) => !picked.has(l.product_id)));
    setPicked(new Set());
    setTarget("");
    setWhy("");

    try {
      const r = await api.post<{ moved: number; message: string }>(
        "/api/stock/bins/move",
        { product_ids: ids, bin: where, clear, reason: why.trim(), slot });
      toast.ok(r.message);
      load();
    } catch (e) {
      // Put them back exactly where they were rather than reloading: a
      // reload would lose which rows the person had ticked, and the ticking
      // is the work they just did.
      setLines((all) => [...all, ...moving].sort(
        (a, b) => a.name.localeCompare(b.name)));
      setPicked(new Set(ids));
      toast.error(errorText(e, "Those lines could not be moved."));
    }
  }

  // ---------- one shelf ----------
  if (open) {
    const worth = lines.reduce((sum, l) => sum + l.value, 0);
    const units = lines.reduce((sum, l) => sum + l.on_hand, 0);
    return (
      <>
        <div className="bins-head">
          <div>
            <button type="button" className="btn small ghost"
                    onClick={() => { setOpen(""); setPicked(new Set()); }}>
              Back to all bins
            </button>
            <h3 className="bins-title">
              {open === "?" ? "Stock with no bin" : `Bin ${open}`}
            </h3>
            <p className="muted small">
              {lines.length.toLocaleString()} line{lines.length === 1 ? "" : "s"},
              {" "}{units.toLocaleString()} unit{units === 1 ? "" : "s"},
              {" "}{money(worth)} at cost
              {open === "?" && lines.length > 0 && (
                <>. This is stock the pharmacy owns and cannot be sent to
                  {" "}anybody to fetch.</>
              )}
            </p>
          </div>
        </div>

        {picked.size > 0 && (
          <div className="bins-move">
            <span className="bins-move-count">
              {picked.size} line{picked.size === 1 ? "" : "s"} ticked
            </span>
            <input value={target} onChange={(e) => setTarget(e.target.value)}
                   placeholder="Move to bin" maxLength={20}
                   className="bins-move-bin" />
            <select className="bins-move-slot" value={slot}
                    aria-label="Which of the three places this sets"
                    onChange={(e) => setSlot(Number(e.target.value))}>
              <option value={1}>Main shelf</option>
              <option value={2}>Second place</option>
              <option value={3}>Third place</option>
            </select>
            <input value={why} onChange={(e) => setWhy(e.target.value)}
                   placeholder="Why, if there is a reason" maxLength={200}
                   className="bins-move-why" />
            <button type="button" className="btn small" onClick={() => move(false)}>
              Move them
            </button>
            {open !== "?" && (
              <button type="button" className="btn small ghost"
                      onClick={() => move(true)}
                      title="Take these off the shelf. They join the list of stock with no bin.">
                Take off the shelf
              </button>
            )}
            <button type="button" className="btn small ghost"
                    onClick={() => setPicked(new Set())}>
              Clear
            </button>
          </div>
        )}

        <Refreshable loading={busy} hasData={lines.length > 0}
                     skeleton={<TableSkeleton cols={5} rows={8}
                                              widths={["3ch", "34ch", "12ch", "10ch", "12ch"]} />}>
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th className="bins-tick">
                    <input type="checkbox"
                           checked={picked.size > 0 && picked.size === lines.length}
                           onChange={(e) => setPicked(e.target.checked
                             ? new Set(lines.map((l) => l.product_id)) : new Set())} />
                  </th>
                  <th>Medicine</th>
                  <th>Code</th>
                  <th className="num">On hand</th>
                  <th className="num">Value at cost</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.product_id}
                      className={picked.has(l.product_id) ? "row-flag" : undefined}>
                    <td className="bins-tick">
                      <input type="checkbox" checked={picked.has(l.product_id)}
                             onChange={() => toggle(l.product_id)} />
                    </td>
                    <td>
                      <EntityLink kind="product" id={l.product_id}>{l.name}</EntityLink>
                      {/* Flagged here because a shelf walk is when somebody
                          can do something about it: they are standing in
                          front of the gap. */}
                      {l.empty ? <span className="badge danger">Empty</span>
                        : l.short ? <span className="badge warn">Low</span> : null}
                    </td>
                    <td className="muted small">{l.stock_code || "—"}</td>
                    <td className="num">{l.on_hand.toLocaleString()}</td>
                    <td className="num">
                      {/* Valued where it mainly lives, or the same stock is
                          worth money on two shelves at once and the bin
                          totals stop adding up to the shelf. */}
                      {l.primary === false
                        ? <span className="muted small">
                            valued in {l.also_in?.[0] ?? "its main bin"}
                          </span>
                        : l.value > 0.005 ? money(l.value) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Refreshable>
      </>
    );
  }

  // ---------- the directory ----------
  return (
    <>
      <div className="bins-head">
        <p className="muted bins-say">
          {dir && dir.bins.length > 0
            ? <>
                <b>{dir.bins.length}</b> bin{dir.bins.length === 1 ? "" : "s"} holding
                {" "}<b>{dir.lines.toLocaleString()}</b> line
                {dir.lines === 1 ? "" : "s"} and {money(dir.value)} at cost.
              </>
            : !loading
              ? "No shelf locations are recorded yet. They come in on a stock "
                + "import, or can be set on any product."
              : null}
        </p>
        <input className="bins-find" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Find a bin" />
      </div>

      {/* The number this screen exists for, stated rather than filtered to. */}
      {dir && dir.unbinned > 0 && (
        // READING THE NUMBER IS NOT THE JOB.
        // It opened a drawer listing them, and the job is putting them on
        // shelves, which a drawer had no room to do.
        <Link to="/bins/unassigned" className="bins-loose">
          <span className="bins-loose-n">{dir.unbinned.toLocaleString()}</span>
          <span>
            line{dir.unbinned === 1 ? "" : "s"} have stock on hand and no bin,
            {" "}{dir.unbinned_units.toLocaleString()} unit
            {dir.unbinned_units === 1 ? "" : "s"} in all. Stock nobody can be
            {" "}sent to fetch is stock that gets ordered twice.
          </span>
          <span className="bins-loose-go">Put them on shelves</span>
        </Link>
      )}

      <Refreshable loading={loading} hasData={shown.length > 0}
                   skeleton={<TableSkeleton cols={4} rows={8}
                                            widths={["10ch", "10ch", "12ch", "14ch"]} />}>
        <div className="bins-grid">
          {shown.map((b) => (
            <div key={b.bin} className="bins-card-wrap">
            {/* A LINK, NOT A DRAWER.
                Opening the shelf under the grid meant the address bar still
                said Inventory: "check bin A14" could not be sent to anybody,
                the browser's back button did nothing, and a panel had
                nowhere to put the actions somebody standing at the shelf
                actually wants. */}
            <Link to={`/bins/${encodeURIComponent(b.bin)}`} className="bins-card">
              <span className="bins-card-name">Bin {b.bin}</span>
              <span className="bins-card-lines">
                {b.lines.toLocaleString()} line{b.lines === 1 ? "" : "s"}
              </span>
              {/* Less than nothing on a shelf is a record that is wrong,
                  not a quantity. Printing "-55 units" passes it off as a
                  reading and the count that needs correcting is the one
                  nobody notices. */}
              <span className={`bins-card-units${b.units < 0 ? " is-wrong" : ""}`}>
                {b.units < 0
                  ? `${Math.abs(b.units).toLocaleString()} over-issued`
                  : `${b.units.toLocaleString()} unit${b.units === 1 ? "" : "s"}`}
              </span>
              <span className="bins-card-value">{money(b.value)}</span>
              {/* Two spellings of one bin means two shelf labels, or a typing
                  mistake, and either is worth seeing rather than quietly
                  merging. */}
              {b.also > 0 && (
                <span className="muted small bins-card-also">
                  {b.also} also kept here
                </span>
              )}
              {b.spellings.length > 1 && (
                <span className="badge warn bins-card-spell">
                  Spelt {b.spellings.length} ways
                </span>
              )}
            </Link>
            {/* RELABEL, MERGE OR EMPTY A SHELF.
                None of this existed. A shelf gets relabelled, two shelves
                become one, a fixture is taken out — and the only way to
                record any of it was to open the shelf, tick every line by
                hand and retype the name. A hundred-line shelf is a hundred
                ticks and a mistake, so it does not get done and the bin map
                drifts away from the room it describes.

                It is also the answer to the "Spelt N ways" badge, which this
                screen has always shown and never offered to fix. */}
            <button type="button" className="btn-link small bins-card-edit"
                    onClick={() => setRenaming(b.bin)}>
              Rename or merge
            </button>
            </div>
          ))}
        </div>
      </Refreshable>

      {renaming !== null && (
        <RenameBin
          bin={renaming}
          onClose={() => setRenaming(null)}
          onDone={() => { setRenaming(null); load(); }}
        />
      )}
    </>
  );
}

/** Relabel a shelf, merge it into another, or empty it.
 *
 *  All three are the same act, because a bin is not a record: it is whatever
 *  somebody typed into a product's location, so "rename B12 to B14" means
 *  moving every line in B12 to B14, and if B14 already exists that is a
 *  merge. The server decides which of the three it turned out to be and says
 *  so, rather than this screen guessing from what was typed.
 */
function RenameBin({ bin, onClose, onDone }: {
  bin: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [to, setTo] = useState("");
  const [why, setWhy] = useState("");
  const [clear, setClear] = useState(false);

  async function go() {
    try {
      const r = await api.post<{ message: string; merged: boolean }>(
        "/api/stock/bins/rename",
        { from: bin, to: clear ? "" : to.trim(), clear, reason: why.trim() });
      toast.ok(r.message);
      onDone();
    } catch (e) {
      toast.error(errorText(e, "That shelf could not be changed."));
    }
  }

  const ready = clear || to.trim().length > 0;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Bin {bin}</h2>
        <p className="muted">
          Every line kept here moves, in whichever of its three places this
          shelf is. If the new name already exists the two shelves become one.
        </p>

        <div className="field">
          <label htmlFor="bin-to">New name</label>
          <input id="bin-to" value={to} autoFocus maxLength={20}
                 disabled={clear}
                 onChange={(e) => setTo(e.target.value)}
                 placeholder="e.g. B14" />
          <span className="hint">
            Type an existing shelf to merge this one into it.
          </span>
        </div>

        {/* Emptying is a real thing — a fixture is taken out — and it is also
            what an empty form field looks like, so it is asked for rather
            than defaulted into. */}
        <Checkbox checked={clear} onChange={setClear}
                  hint="The lines go back among the unplaced. Nothing is deleted.">
          Empty this shelf instead
        </Checkbox>

        <div className="field">
          <label htmlFor="bin-why">Why <span className="muted">optional</span></label>
          <input id="bin-why" value={why} maxLength={200}
                 onChange={(e) => setWhy(e.target.value)}
                 placeholder="e.g. shelving replaced" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={go} disabled={!ready}
                      busyLabel="Moving…">
            {clear ? "Empty it" : "Move them"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
