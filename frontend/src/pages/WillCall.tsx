/** The will-call shelf: bagged, and nobody has come for it.
 *
 *  Every pharmacy has this shelf and no system here modelled it, so a bag nobody
 *  came back for was indistinguishable from one handed over and the only way to
 *  find it was to read the names on the shelf.
 *
 *  Ordered oldest first, deliberately. The point of the screen is the bag that
 *  has been there longest; a list opening on this morning's dispensings puts the
 *  thing you need at the bottom.
 *
 *  The band, not the day count, is what the row leads with. "Forty-one days" asks
 *  the reader to decide what that means on a Saturday morning with a queue; "over
 *  a month, return it to stock and reverse the claim" does not.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Phone } from "@phosphor-icons/react";
import { api, errorText, fmtDateTime } from "../api";
import BusyButton from "../components/BusyButton";
import { useConfirm } from "../components/Confirm";
import Pagination from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";
import { useToast } from "../components/Toast";
import { TableSkeleton } from "../components/Skeleton";

interface Bag {
  dispensing_id: number;
  rx_number: string;
  patient_id: number | null;
  patient: string;
  phone: string;
  product: string;
  quantity: number;
  schedule: number | null;
  dispensed_at: string;
  dispensed_by: string;
  days_waiting: number;
  band: "fresh" | "waiting" | "stale" | "abandoned";
  action: string;
  needs_id: boolean;
}

interface Shelf {
  items: Bag[];
  more: boolean;
  total: number;
  bands: Record<string, number>;
}

const BAND_LABEL: Record<string, string> = {
  fresh: "Today or yesterday",
  waiting: "Waiting",
  stale: "A week or more",
  abandoned: "Over a month",
};

export default function WillCall() {
  const [shelf, setShelf] = useState<Shelf | null>(null);
  const [failed, setFailed] = useState("");
  const [band, setBand] = useState("");
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(() =>
    api.get<Shelf>("/api/dispensing/will-call?limit=400")
      .then((s) => { setShelf(s); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "The shelf could not be read."))),
  []);

  useEffect(() => { load(); }, [load]);

  const rows = (shelf?.items ?? []).filter((b) => !band || b.band === band);
  const page = useClientPage(rows, 25);

  async function collect(bag: Bag) {
    /* Who took it is asked, not assumed. Often it is not the patient — a
       relative, a driver, a neighbour going that way — and on a controlled item
       it is the answer to "who had it", so there the name is required. */
    const ok = await confirm({
      title: `Hand over ${bag.product}?`,
      body: (
        <>
          {bag.quantity} for <b>{bag.patient}</b>, bagged {fmtDateTime(bag.dispensed_at)}.
          {bag.needs_id && (
            <> This is a Schedule {bag.schedule} item, so who takes it must be recorded.</>
          )}
        </>
      ),
      confirmLabel: "Handed over",
    });
    if (!ok) return;

    const takenBy = bag.needs_id
      ? window.prompt("Who is taking it? (name as given)")?.trim() ?? ""
      : "";
    if (bag.needs_id && !takenBy) {
      toast.error("A Schedule 5 or 6 item cannot be handed over without a name.");
      return;
    }
    try {
      await api.post(`/api/dispensing/will-call/${bag.dispensing_id}/collect`,
                     { taken_by: takenBy, id_seen: "" });
      toast.ok(`${bag.product} handed over.`);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That could not be recorded."));
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Will call</h1>
          <div className="sub">
            Dispensed, bagged and not yet collected. Oldest first
          </div>
        </div>
      </div>

      {failed && <div className="alert error">{failed}</div>}

      {/* The bands are the summary and the filter at once. Counted over the whole
          shelf rather than the visible page. */}
      <div className="wl-stats">
        <button className={`wl-stat${band === "" ? " is-on" : ""}`} onClick={() => setBand("")}>
          <b>{shelf?.total ?? "—"}</b><span>on the shelf</span>
        </button>
        {["fresh", "waiting", "stale", "abandoned"].map((b) => (
          <button key={b} className={`wl-stat wc-${b}${band === b ? " is-on" : ""}`}
                  onClick={() => setBand(band === b ? "" : b)}>
            <b>{shelf?.bands?.[b] ?? 0}</b><span>{BAND_LABEL[b]}</span>
          </button>
        ))}
      </div>

      <div className="card">
        {!shelf && !failed && <TableSkeleton cols={6} rows={6} />}
        {/* Two different empties, said differently.
            A filtered view with nothing in it is a filter result and should offer
            the way back out. An empty shelf is an achievement and should read
            like one — "no results" under a heading called Will call tells a
            pharmacist nothing about whether the feature is working, whether they
            have set it up, or whether they are simply on top of their bags. */}
        {shelf && rows.length === 0 && band && (
          <div className="empty">
            <b>Nothing {BAND_LABEL[band].toLowerCase()}.</b>
            <p>
              {shelf.total > 0
                ? `${shelf.total} bag${shelf.total === 1 ? " is" : "s are"} waiting in other bands.`
                : "The shelf is empty altogether."}
            </p>
            <button className="btn secondary small" onClick={() => setBand("")}>
              Show the whole shelf
            </button>
          </div>
        )}
        {shelf && rows.length === 0 && !band && (
          <div className="empty">
            <b>Nothing is waiting to be collected.</b>
            <p>
              Every bag dispensed has been handed over. Anything dispensed from
              now on appears here until somebody marks it collected, and a bag
              still here after a week is worth a telephone call.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th>Patient</th><th>Medicine</th><th className="num">Qty</th>
                    <th>Bagged</th><th>Waiting</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((b) => (
                    <tr key={b.dispensing_id}>
                      <td>
                        {b.patient_id
                          ? <Link to={`/patients/${b.patient_id}`}>{b.patient}</Link>
                          : b.patient}
                        {b.phone && (
                          <div className="muted small">
                            <Phone size={11} /> {b.phone}
                          </div>
                        )}
                      </td>
                      <td>
                        {b.product}
                        {b.needs_id && <span className="badge sched">S{b.schedule}</span>}
                        <div className="muted small">{b.rx_number} · {b.dispensed_by}</div>
                      </td>
                      <td className="num">{b.quantity}</td>
                      <td>{fmtDateTime(b.dispensed_at)}</td>
                      <td>
                        {/* The band leads, not the number. "Forty-one days" asks
                            the reader to decide what that means on a Saturday
                            morning with a queue behind them. */}
                        <span className={`badge wc-badge wc-${b.band}`}>{BAND_LABEL[b.band]}</span>
                        <div className="muted small">{b.action}</div>
                      </td>
                      <td className="actions">
                        <BusyButton className="btn small" onClick={() => collect(b)}>
                          Handed over
                        </BusyButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={page.meta} onPage={page.setPage} />
          </>
        )}
      </div>
    </>
  );
}
