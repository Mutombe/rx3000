/** One driver: what they are carrying, what they have carried, and their record.
 *
 *  The page a name in a delivery list should open onto, and did not — a driver
 *  was a string on a waybill and led nowhere.
 *
 *  Three questions, in the order somebody actually asks them:
 *
 *    is there a problem right now — money uncollected, a licence expired, a
 *    round that went out three hours ago and has not come back;
 *    how do I reach them;
 *    are they any good — how many deliveries fail, and why.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ArrowLeft, PencilSimple, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money, prefetchRoute } from "../api";
import { EntityLink } from "../components/Filters";
import RowLink from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import BusyButton from "../components/BusyButton";
import { useToast } from "../components/Toast";
import DriverForm from "../components/DriverForm";
import type { Driver } from "./Drivers";

interface Waybill {
  id: number; waybill_number: string; status: string;
  patient_id: number | null; patient: string;
  recipient: string; address: string;
  delivery_fee: number; cod_amount: number; cod_collected: number;
  cod_outstanding: number; cod_settled_at: string | null;
  created_at: string; dispatched_at: string | null; delivered_at: string | null;
  failure_reason: string; received_by: string;
}
type Detail = Driver & { waybills: Waybill[]; fees_earned: number };

const STATUS: Record<string, string> = {
  pending: "muted", out: "warn", delivered: "ok", failed: "bad",
  cancelled: "muted",
};

const VEHICLE: Record<string, string> = {
  motorbike: "Motorbike", car: "Car", van: "Van",
  bicycle: "Bicycle", on_foot: "On foot",
};

export default function DriverDetail() {
  const { id } = useParams();
  const [driver, setDriver] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [handingIn, setHandingIn] = useState(false);
  const [counted, setCounted] = useState("");
  const toast = useToast();

  const load = useCallback(() => {
    setLoading(true);
    api.get<Detail>(`/api/drivers/${id}`)
      .then(setDriver)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(load, [load]);

  async function handIn() {
    try {
      const r = await api.post<{ message: string }>("/api/deliveries/hand-in", {
        driver_profile_id: Number(id),
        // Counted, not assumed. The whole reason to count at a hand-over is
        // that the two figures sometimes differ, and a system that writes the
        // expected figure over the counted one has thrown the difference away.
        counted: counted === "" ? null : Number(counted),
      });
      toast.ok(r.message);
      setHandingIn(false); setCounted("");
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  if (loading && !driver) {
    return <div className="page"><TableSkeleton cols={5} rows={6} /></div>;
  }
  if (!driver) return <div className="page"><div className="empty">Driver not found.</div></div>;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <a href="/drivers" className="back-link">
            <ArrowLeft size={14} weight="bold" /> Drivers
          </a>
          <h1>{driver.full_name}</h1>
          <p className="muted">
            {VEHICLE[driver.vehicle_type] || driver.vehicle_type}
            {driver.vehicle_registration && ` · ${driver.vehicle_registration}`}
            {driver.branch && ` · ${driver.branch}`}
            {!driver.active && " · retired"}
          </p>
        </div>
        <div className="page-actions">
          {driver.cash_holding > 0 && (
            <button className="btn primary" onClick={() => setHandingIn(true)}>
              Hand in {money(driver.cash_holding)}
            </button>
          )}
          <button className="btn" onClick={() => setEditing(true)}>
            <PencilSimple size={14} weight="bold" /> Edit
          </button>
        </div>
      </header>

      {/* Anything that should stop a round leaving, said before the numbers.
          Both of these are refused at dispatch as well — a warning nothing
          enforces is a warning people learn to scroll past. */}
      {driver.licence_expired && (
        <p className="alert bad">
          <Warning size={16} weight="fill" />
          <span>
            This licence expired on {fmtDate(driver.licence_expiry!)}. Deliveries
            cannot be dispatched to {driver.full_name} until it is renewed.
          </span>
        </p>
      )}
      {driver.over_cod_limit && (
        <p className="alert warn">
          <Warning size={16} weight="fill" />
          <span>
            Carrying {money(driver.cash_holding)} against a limit of{" "}
            {money(driver.cod_limit)}. Nothing further will be dispatched until
            this is handed in.
          </span>
        </p>
      )}

      <div className="wc-bands">
        <div className="wl-stat">
          <b>{driver.out}</b><span>out right now</span>
        </div>
        <div className={`wl-stat${driver.cash_holding ? " wc-abandoned" : ""}`}>
          <b className={driver.cash_holding ? "tone-danger" : undefined}>
            {money(driver.cash_holding)}
          </b>
          <span>collected, not handed in</span>
        </div>
        <div className="wl-stat">
          <b>{money(driver.cod_to_collect)}</b><span>still to collect</span>
        </div>
        <div className="wl-stat">
          <b>{driver.delivered}</b><span>delivered</span>
        </div>
        <div className="wl-stat">
          <b className={driver.failure_rate && driver.failure_rate > 10
            ? "tone-danger" : undefined}>
            {driver.failure_rate === null ? "—" : `${driver.failure_rate}%`}
          </b>
          <span>of attempts failed</span>
        </div>
        <div className="wl-stat">
          <b>{money(driver.fees_earned)}</b><span>in delivery fees carried</span>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h3>Contact and vehicle</h3></div>
        <dl className="kv">
          <dt>Phone</dt><dd><a href={`tel:${driver.phone}`}>{driver.phone}</a></dd>
          {driver.alternate_phone && (
            <>
              <dt>Other number</dt>
              <dd><a href={`tel:${driver.alternate_phone}`}>{driver.alternate_phone}</a></dd>
            </>
          )}
          {driver.national_id && (<><dt>National ID</dt><dd className="mono">{driver.national_id}</dd></>)}
          <dt>Licence</dt>
          <dd>
            {driver.licence_number || <span className="muted">not recorded</span>}
            {driver.licence_expiry && ` · expires ${fmtDate(driver.licence_expiry)}`}
          </dd>
          <dt>Cash float</dt><dd className="mono">{money(driver.cash_float)}</dd>
          <dt>COD limit</dt>
          <dd className="mono">
            {driver.cod_limit ? money(driver.cod_limit)
              : <span className="muted">no limit set</span>}
          </dd>
          {driver.notes && (<><dt>Notes</dt><dd>{driver.notes}</dd></>)}
        </dl>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Deliveries</h3>
          <span className="muted small">
            {driver.total_runs} carried, most recent first
          </span>
        </div>
        <Refreshable loading={loading} hasData={driver.waybills.length > 0}
          skeleton={<TableSkeleton cols={6} rows={5} />}>
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Waybill</th><th>To</th><th>Status</th>
                  <th className="num">Fee</th>
                  <th className="num">To collect</th>
                  <th className="num">Collected</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {driver.waybills.map((w) => (
                  <RowLink key={w.id} to={`/waybills/${w.id}`} prefetch={prefetchRoute}>
                    <td className="mono">
                      <EntityLink kind="waybill" id={w.id}>{w.waybill_number}</EntityLink>
                    </td>
                    <td>
                      {w.patient_id
                        ? <EntityLink kind="patient" id={w.patient_id}>
                            {w.patient || w.recipient}
                          </EntityLink>
                        : w.recipient}
                      <div className="muted small">{w.address}</div>
                    </td>
                    <td>
                      <span className={`badge ${STATUS[w.status] ?? "muted"}`}>
                        {w.status}
                      </span>
                      {w.failure_reason && (
                        <div className="muted small">{w.failure_reason}</div>
                      )}
                    </td>
                    <td className="num mono">
                      {w.delivery_fee ? money(w.delivery_fee) : <span className="muted">—</span>}
                    </td>
                    <td className="num mono">
                      {w.cod_amount ? money(w.cod_amount) : <span className="muted">—</span>}
                    </td>
                    <td className="num mono">
                      {w.cod_collected ? money(w.cod_collected) : <span className="muted">—</span>}
                      {/* Handed in or still on them. The distinction is the
                          entire reason both figures are kept. */}
                      {w.cod_collected > 0 && !w.cod_settled_at && (
                        <div><span className="badge warn">not handed in</span></div>
                      )}
                    </td>
                    <td className="muted small">
                      {fmtDateTime(w.delivered_at || w.dispatched_at || w.created_at)}
                    </td>
                  </RowLink>
                ))}
                {!driver.waybills.length && (
                  <tr><td colSpan={7} className="muted pad">
                    Nothing carried yet.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Refreshable>
      </div>

      {editing && (
        <DriverForm driver={driver} onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); load(); }} />
      )}

      {handingIn && (
        <div className="modal-backdrop" onClick={() => setHandingIn(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Hand in the round</h2>
            <p className="muted">
              {driver.full_name} is holding {money(driver.cash_holding)} from
              deliveries already made. It lands in your open till and the
              deliveries are stamped with which cash-up received them.
            </p>
            <label>
              Counted at the hand-over
              <input type="number" step="0.01" autoFocus value={counted}
                onChange={(e) => setCounted(e.target.value)}
                placeholder={String(driver.cash_holding.toFixed(2))} />
            </label>
            <p className="muted small">
              Count it rather than accepting the figure. If the two differ, the
              difference is recorded — that is the only fact a hand-over
              produces that is worth keeping.
            </p>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setHandingIn(false)}>Cancel</button>
              <BusyButton className="btn primary" onClick={handIn} busyLabel="Recording…">
                Record the hand-in
              </BusyButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
