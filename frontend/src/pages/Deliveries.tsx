/** Deliveries — medicine that has left the shop and not yet reached the patient.
 *
 *  The queue is ordered by where a parcel is in its journey rather than by date,
 *  because the question at eight in the morning is "what goes out today" and the
 *  question at five is "what has not come back signed".
 *
 *  A delivery carrying a controlled substance is marked on the row, not buried
 *  in the detail: the driver needs to know before they leave that they have to
 *  check identity at the door.
 */
import { useEffect, useMemo, useState } from "react";
import { api, fmtDateTime, prefetchRoute, errorText  } from "../api";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import BusyButton from "../components/BusyButton";
import NewDelivery from "../components/NewDelivery";
import { Plus } from "@phosphor-icons/react";

interface Waybill {
  id: number; waybill_number: string; status: string;
  sale_id: number | null; patient_id: number | null;
  recipient: string; address: string; phone: string; instructions: string;
  driver: string; received_by: string; failure_reason: string;
  requires_id_check: boolean; id_number_seen: string;
  created_at: string; dispatched_at: string | null; delivered_at: string | null;
}

type Tab = "pending" | "out" | "delivered" | "failed";

export default function Deliveries() {
  const [rows, setRows] = useState<Record<string, Waybill[]>>({});
  const [raising, setRaising] = useState(false);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState<Waybill | null>(null);
  const [failing, setFailing] = useState<Waybill | null>(null);
  const [receivedBy, setReceivedBy] = useState("");
  const [idSeen, setIdSeen] = useState("");
  const [reason, setReason] = useState("");
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "pending", label: "To go out", count: rows.pending?.length,
      hint: "Raised and not yet dispatched" },
    { key: "out", label: "Out with a driver", count: rows.out?.length },
    { key: "delivered", label: "Delivered", count: rows.delivered?.length },
    { key: "failed", label: "Failed", count: rows.failed?.length,
      hint: "The medicine is still the pharmacy's" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "pending");

  function load() {
    setLoading(true);
    Promise.all(
      (["pending", "out", "delivered", "failed"] as Tab[]).map((status) =>
        api.get<Waybill[]>(`/api/waybills?status=${status}`).then((r) => [status, r] as const),
      ),
    )
      .then((all) => setRows(Object.fromEntries(all)))
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const list = rows[tab] ?? [];

  async function dispatch(w: Waybill) {
    try {
      await api.post(`/api/waybills/${w.id}/dispatch`, {});
      toast.ok(`${w.waybill_number} is out for delivery.`);
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  async function sign() {
    if (!signing) return;
    try {
      await api.post(`/api/waybills/${signing.id}/deliver`, {
        received_by: receivedBy, id_number_seen: idSeen,
      });
      toast.ok(`${signing.waybill_number} signed for by ${receivedBy}.`);
      setSigning(null); setReceivedBy(""); setIdSeen("");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  async function markFailed() {
    if (!failing) return;
    try {
      await api.post(`/api/waybills/${failing.id}/fail`, { reason });
      toast.warn(`${failing.waybill_number} did not deliver. The medicine is still ours.`);
      setFailing(null); setReason("");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  const headline = useMemo(() => {
    const out = rows.out?.length ?? 0;
    const pending = rows.pending?.length ?? 0;
    if (!out && !pending) return "Nothing is out.";
    return `${pending} to go out, ${out} with a driver.`;
  }, [rows]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Deliveries</h1>
          <p className="muted">{headline}</p>
        </div>
        {/* Deliveries only ever arrived here already made. The request usually
            arrives by telephone, and the endpoint to raise one has existed
            since deliveries were built with nothing calling it. */}
        <div className="page-actions">
          <button className="btn" onClick={() => setRaising(true)}>
            <Plus size={14} weight="bold" /> New delivery
          </button>
        </div>
      </header>

      {raising && (
        <NewDelivery onClose={() => setRaising(false)} onRaised={load} />
      )}

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      <Refreshable
        loading={loading}
        hasData={list.length > 0}
        skeleton={<TableSkeleton cols={6} rows={6}
          widths={["12ch", "18ch", "26ch", "12ch", "16ch", "18ch"]} />}
      >
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Waybill</th><th>Recipient</th><th>Address</th>
                <th>Driver</th><th>Raised</th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((w) => (
                <RowLink
                  key={w.id}
                  to={w.patient_id ? `/patients/${w.patient_id}` : `/sales/${w.sale_id}`}
                  prefetch={prefetchRoute}
                  className={w.requires_id_check ? "row-flag" : ""}
                >
                  <td className="mono">
                    {w.waybill_number}
                    {/* The driver needs to know this before they leave, not on
                        arrival at a locked gate. */}
                    {w.requires_id_check && (
                      <div><span className="badge warn">check ID at the door</span></div>
                    )}
                  </td>
                  <td>
                    {w.recipient}
                    {w.phone && <div className="muted small">{w.phone}</div>}
                  </td>
                  <td>
                    {w.address}
                    {w.instructions && <div className="muted small">{w.instructions}</div>}
                  </td>
                  <td>{w.driver || <span className="muted">—</span>}</td>
                  <td>{fmtDateTime(w.created_at)}</td>
                  <RowActions>
                    {w.status === "pending" && (
                      <BusyButton className="btn primary sm" onClick={() => dispatch(w)}>
                        Send out
                      </BusyButton>
                    )}
                    {w.status === "out" && (
                      <button className="btn primary sm" onClick={() => setSigning(w)}>
                        Sign for
                      </button>
                    )}
                    {(w.status === "pending" || w.status === "out") && (
                      <button className="btn ghost sm" onClick={() => setFailing(w)}>
                        Did not deliver
                      </button>
                    )}
                    {w.status === "delivered" && (
                      <span className="muted small">
                        {w.received_by}
                        {w.id_number_seen && ` · ID ${w.id_number_seen}`}
                      </span>
                    )}
                    {w.status === "failed" && (
                      <span className="muted small">{w.failure_reason}</span>
                    )}
                  </RowActions>
                </RowLink>
              ))}
              {!list.length && !loading && (
                <tr><td colSpan={6} className="muted pad">Nothing here.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Refreshable>

      {signing && (
        <div className="modal-backdrop" onClick={() => setSigning(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Sign for {signing.waybill_number}</h2>
            <p className="muted">
              Record who actually took it. A parcel signed for by nobody is a
              missing parcel with a tick against it.
            </p>
            {signing.requires_id_check && (
              <p className="alert warn">
                This delivery contains a controlled substance. The recipient's
                identity must be checked at the door and recorded.
              </p>
            )}
            <label>
              Received by
              <input value={receivedBy} autoFocus
                onChange={(e) => setReceivedBy(e.target.value)}
                placeholder="Full name of whoever took it" />
            </label>
            {signing.requires_id_check && (
              <label>
                Identity number seen
                <input value={idSeen} onChange={(e) => setIdSeen(e.target.value)} />
              </label>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setSigning(null)}>Cancel</button>
              <button className="btn primary"
                disabled={!receivedBy.trim() ||
                          (signing.requires_id_check && !idSeen.trim())}
                onClick={sign}>
                Delivered
              </button>
            </div>
          </div>
        </div>
      )}

      {failing && (
        <div className="modal-backdrop" onClick={() => setFailing(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{failing.waybill_number} did not deliver</h2>
            <p className="muted">
              The medicine is still the pharmacy's and still owed to the patient.
              Say what happened so somebody can try again.
            </p>
            <label>
              What happened
              <input value={reason} autoFocus onChange={(e) => setReason(e.target.value)}
                placeholder="Nobody home, gate locked" />
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setFailing(null)}>Cancel</button>
              <button className="btn danger" disabled={!reason.trim()} onClick={markFailed}>
                Record the failure
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
