/** Stock that is on the shelf somewhere and nobody knows where.
 *
 *  WHY THIS IS A SCREEN AND NOT A NUMBER
 *
 *  The bins tab said "196 lines have stock on hand and no bin" in a large
 *  yellow slab, and the slab opened a drawer listing them. Reading the number
 *  is not the job. The job is putting those lines on shelves, and doing that
 *  one product form at a time is why the field stayed empty in the first
 *  place: a hundred lines is a hundred forms and an afternoon.
 *
 *  DEAREST FIRST, AND THAT IS DELIBERATE
 *
 *  This is a list somebody works down until they run out of afternoon, so the
 *  money is at the top of it. Ordered alphabetically it would be worked from
 *  A, and the expensive lines nobody can find would sit at the bottom
 *  untouched.
 *
 *  WHAT IT IS FOR
 *
 *  Stock nobody can be sent to fetch gets ordered twice: once because it
 *  cannot be found, and again when the first order arrives. The cost of an
 *  empty bin field is paid in duplicate stock, not in tidiness.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, MapPin } from "@phosphor-icons/react";

import { api, errorText, money } from "../api";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

interface Loose {
  product_id: number;
  name: string;
  stock_code: string;
  on_hand: number;
  value: number;
}

export default function BinsUnassigned() {
  const toast = useToast();
  const [rows, setRows] = useState<Loose[] | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [q, setQ] = useState("");
  const [bin, setBin] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.get<{ lines: Loose[] }>("/api/stock/bins/unbinned")
      .then((r) => { setRows(r.lines); setPicked(new Set()); })
      .catch((e) => setError(errorText(e, "That list could not be read.")));
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows ?? [];
    return (rows ?? []).filter((r) =>
      r.name.toLowerCase().includes(needle)
      || r.stock_code.toLowerCase().includes(needle));
  }, [rows, q]);

  function toggle(id: number) {
    setPicked((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  /** Every line the search is currently showing, which is the useful "all":
   *  somebody searches "amox", ticks the lot, and puts them on one shelf. */
  function chooseShown() {
    setPicked(new Set(shown.map((r) => r.product_id)));
  }

  async function place() {
    const ids = [...picked];
    if (!ids.length || !bin.trim()) return;
    setSaving(true);
    try {
      const said = await api.post<{ message: string }>("/api/stock/bins/move", {
        product_ids: ids, bin: bin.trim(), slot: 1,
        reason: "Placed from the unplaced list",
      });
      toast.ok(said.message);
      setBin("");
      load();
    } catch (e) {
      toast.error(errorText(e, "Those lines could not be placed."));
    } finally {
      setSaving(false);
    }
  }

  const worth = (rows ?? []).reduce((sum, r) => sum + r.value, 0);
  const chosenWorth = (rows ?? [])
    .filter((r) => picked.has(r.product_id))
    .reduce((sum, r) => sum + r.value, 0);

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Inventory", to: "/stock" },
              { label: "Bins", to: "/stock?tab=bins" },
              { label: "Not on any shelf" }]}
      eyebrow="Shelf locations"
      title="Stock with no shelf"
      subtitle={rows ? `${rows.length} line(s) nobody can be sent to fetch` : undefined}
      loading={!rows && !error}
      error={error}
      actions={
        <Link to="/stock?tab=bins" className="btn secondary">
          <ArrowLeft size={13} weight="bold" /> Bins
        </Link>
      }
      facts={rows ? [
        { label: "Lines", value: rows.length, hint: "with stock and no shelf",
          tone: rows.length ? "warn" : "ok" },
        { label: "Units", value: rows.reduce((s, r) => s + r.on_hand, 0).toLocaleString(),
          hint: "sitting somewhere" },
        { label: "Worth", value: money(worth), hint: "at cost" },
      ] : []}
    >
      {rows && rows.length === 0 && (
        <div className="alert ok">
          Every line with stock on it has a shelf. Somebody can be sent to
          fetch anything in this pharmacy.
        </div>
      )}

      {rows && rows.length > 0 && (
        <>
          <Panel
            title="Nobody can be sent to fetch these"
            count={shown.length}
            empty="Nothing matches that."
            aside={
              <div className="ub-tools">
                <input className="st-control" value={q} placeholder="Find a line"
                       onChange={(e) => setQ(e.target.value)} />
                <button type="button" className="btn secondary small"
                        onClick={chooseShown} disabled={!shown.length}>
                  Choose these {shown.length}
                </button>
              </div>
            }
          >
            <Refreshable loading={rows === null} hasData={shown.length > 0}
                         skeleton={<TableSkeleton cols={4} rows={8} />}>
              <div className="dt-scroll">
                <table className="dt dt-wide">
                  <thead>
                    <tr>
                      <th className="bulk-tick" />
                      <th className="col-med">Line</th>
                      <th className="mono col-code">Code</th>
                      <th className="num">On hand</th>
                      <th className="num">Worth</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => (
                      <tr key={r.product_id}>
                        <td className="bulk-tick">
                          <input type="checkbox" checked={picked.has(r.product_id)}
                                 aria-label={`Choose ${r.name}`}
                                 onChange={() => toggle(r.product_id)} />
                        </td>
                        <td>
                          <EntityLink to={`/products/${r.product_id}`}>
                            {r.name}
                          </EntityLink>
                        </td>
                        <td className="mono small">
                          {r.stock_code || <span className="muted">None</span>}
                        </td>
                        <td className="num"><Units n={r.on_hand} /></td>
                        <td className="num">{money(r.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Refreshable>
          </Panel>

          {/* THE POINT OF THE SCREEN, AND IT STAYS PUT.
              Ticking forty lines and then hunting for somewhere to type the
              shelf is how somebody gives up halfway down a list. */}
          {picked.size > 0 && (
            <div className="card ub-foot">
              <div>
                <b>{picked.size} line(s) chosen</b>
                {chosenWorth > 0 && (
                  <span className="muted"> · {money(chosenWorth)}</span>
                )}
                <div className="muted small">
                  The stock does not move. What changes is that somebody can
                  now be sent to fetch it.
                </div>
              </div>
              <div className="ub-foot-acts">
                <input className="st-control" value={bin} maxLength={20}
                       aria-label="The shelf they go on"
                       placeholder="Shelf, e.g. A14"
                       onChange={(e) => setBin(e.target.value)} />
                <button type="button" className="btn secondary"
                        onClick={() => setPicked(new Set())}>
                  Clear
                </button>
                <BusyButton className="btn primary" onClick={place}
                            disabled={!bin.trim() || saving}
                            busyLabel="Placing…">
                  <MapPin size={13} /> Put them on {bin.trim() || "a shelf"}
                </BusyButton>
              </div>
            </div>
          )}
        </>
      )}
    </RecordPage>
  );
}

/** A count that has gone below nothing, said rather than printed.
 *
 *  A bin showed "-55 units" and "$-22.60" as though that were an ordinary
 *  reading. It is not: stock cannot be less than nothing, so a negative
 *  count means the record is wrong — more has been sold or dispensed than
 *  was ever booked in. Printing the minus sign quietly passes that off as a
 *  quantity, and the count that needs correcting is the one nobody notices.
 */
export function Units({ n }: { n: number }) {
  if (n < 0) {
    return (
      <span className="badge bad" title={
        "The record says less than nothing, which cannot be true. More has "
        + "gone out than was booked in, so this line needs counting."}>
        {Math.abs(n).toLocaleString()} over-issued
      </span>
    );
  }
  if (n === 0) return <span className="muted">Nothing</span>;
  return <>{n.toLocaleString()}</>;
}
