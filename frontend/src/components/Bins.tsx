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

import { api, errorText, money } from "../api";
import { Refreshable, TableSkeleton } from "./Skeleton";
import { EntityLink } from "./Filters";
import { useToast } from "./Toast";

interface Bin {
  bin: string;
  lines: number;
  units: number;
  value: number;
  spellings: string[];
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
        { product_ids: ids, bin: where, clear, reason: why.trim() });
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
                    <td className="num">{l.value > 0.005 ? money(l.value) : "—"}</td>
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
        <button type="button" className="bins-loose" onClick={() => openShelf("?")}>
          <span className="bins-loose-n">{dir.unbinned.toLocaleString()}</span>
          <span>
            line{dir.unbinned === 1 ? "" : "s"} have stock on hand and no bin,
            {" "}{dir.unbinned_units.toLocaleString()} unit
            {dir.unbinned_units === 1 ? "" : "s"} in all. Stock nobody can be
            {" "}sent to fetch is stock that gets ordered twice.
          </span>
        </button>
      )}

      <Refreshable loading={loading} hasData={shown.length > 0}
                   skeleton={<TableSkeleton cols={4} rows={8}
                                            widths={["10ch", "10ch", "12ch", "14ch"]} />}>
        <div className="bins-grid">
          {shown.map((b) => (
            <button type="button" key={b.bin} className="bins-card"
                    onClick={() => openShelf(b.bin)}>
              <span className="bins-card-name">Bin {b.bin}</span>
              <span className="bins-card-lines">
                {b.lines.toLocaleString()} line{b.lines === 1 ? "" : "s"}
              </span>
              <span className="bins-card-units">
                {b.units.toLocaleString()} unit{b.units === 1 ? "" : "s"}
              </span>
              <span className="bins-card-value">{money(b.value)}</span>
              {/* Two spellings of one bin means two shelf labels, or a typing
                  mistake, and either is worth seeing rather than quietly
                  merging. */}
              {b.spellings.length > 1 && (
                <span className="badge warn bins-card-spell">
                  Spelt {b.spellings.length} ways
                </span>
              )}
            </button>
          ))}
        </div>
      </Refreshable>
    </>
  );
}
