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
import { api, fmtDateTime, money, prefetchRoute, errorText  } from "../api";
import { EntityLink } from "../components/Filters";
import Select from "../components/Select";
import BulkBar, { SelectAll, SelectRow } from "../components/BulkBar";
import { useSelection } from "../hooks/useSelection";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConfirm } from "../components/Confirm";
import BusyButton from "../components/BusyButton";
import NewDelivery from "../components/NewDelivery";
import { Plus } from "@phosphor-icons/react";

interface Waybill {
  id: number; waybill_number: string; status: string;
  sale_id: number | null; patient_id: number | null;
  recipient: string; address: string; phone: string; instructions: string;
  driver: string; driver_profile_id: number | null; driver_phone: string;
  received_by: string; failure_reason: string;
  requires_id_check: boolean; id_number_seen: string;
  delivery_fee: number; cod_amount: number; cod_collected: number;
  cod_outstanding: number; cod_settled_at: string | null;
  created_at: string; dispatched_at: string | null; delivered_at: string | null;
}
interface DriverOption {
  id: number; full_name: string; phone: string;
  licence_expired: boolean; over_cod_limit: boolean; cash_holding: number;
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
  // What the driver came back with. Separate from what they were sent to
  // collect, because the two are not always the same number and the difference
  // is the only thing worth recording.
  const [collected, setCollected] = useState("");
  const [drivers, setDrivers] = useState<DriverOption[]>([]);
  const [sending, setSending] = useState<Waybill | null>(null);
  const [driverId, setDriverId] = useState("");
  const [bulkDriver, setBulkDriver] = useState("");
  const toast = useToast();
  const confirm = useConfirm();

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
    api.get<DriverOption[]>("/api/drivers").then(setDrivers).catch(() => {});
  }
  useEffect(load, []);

  const list = rows[tab] ?? [];

  // A driver's round IS a bulk operation. Sending twelve deliveries out one at
  // a time is why the assignment gets written on paper instead, and a round
  // recorded on paper is a round the system cannot tell you the value of, or
  // who is holding the cash from.
  const picked = useSelection(list, (w) => w.id);

  /** Send the whole round out to one driver. */
  async function dispatchAll() {
    if (!bulkDriver) return;
    const driver = drivers.find((d) => String(d.id) === bulkDriver);
    const round = picked.rows.filter((w) => w.status === "pending");
    const cod = round.reduce((n, w) => n + (w.cod_amount ?? 0), 0);

    const ok = await confirm({
      title: `Send ${round.length} out with ${driver?.full_name ?? "this driver"}?`,
      body: (
        <>
          <p>
            {round.length} deliver{round.length === 1 ? "y" : "ies"} go out on
            one round.
          </p>
          {cod > 0 && (
            <p>
              They are to collect <b>{money(cod)}</b> between them. That stays
              with the driver until the round is handed in — it is not counted
              against the counter's till.
            </p>
          )}
        </>
      ),
      confirmLabel: `Send ${round.length} out`,
    });
    if (!ok) return;

    // One at a time, because each dispatch is checked separately — an expired
    // licence or a driver already over their cash limit must refuse the round
    // rather than have it slip through as part of a batch. The refusals are
    // collected and shown, so a partial send is visible as a partial send.
    let sent = 0;
    const refused: string[] = [];
    for (const w of round) {
      try {
        await api.post(`/api/waybills/${w.id}/dispatch`, {
          driver_profile_id: Number(bulkDriver),
        });
        sent += 1;
      } catch (e: any) {
        refused.push(`${w.waybill_number}: ${errorText(e)}`);
      }
    }
    picked.clear();
    setBulkDriver("");
    if (refused.length) {
      // Said in full rather than as a count. "3 failed" on a delivery round is
      // three parcels nobody can name.
      toast.warn(`${sent} sent. ${refused.length} refused — ${refused[0]}`);
    } else {
      toast.ok(`${sent} deliver${sent === 1 ? "y" : "ies"} out with `
               + `${driver?.full_name ?? "the driver"}.`);
    }
    load();
  }

  async function dispatch() {
    if (!sending) return;
    try {
      await api.post(`/api/waybills/${sending.id}/dispatch`, {
        driver_profile_id: driverId ? Number(driverId) : null,
      });
      toast.ok(`${sending.waybill_number} is out for delivery.`);
      setSending(null); setDriverId("");
      load();
    } catch (e: any) {
      // The server refuses an expired licence and a driver already over their
      // cash limit, and says which. Shown as written.
      toast.error(errorText(e));
    }
  }

  async function sign() {
    if (!signing) return;
    try {
      await api.post(`/api/waybills/${signing.id}/deliver`, {
        received_by: receivedBy, id_number_seen: idSeen,
        collected: signing.cod_amount
          ? (collected === "" ? signing.cod_amount : Number(collected))
          : null,
      });
      toast.ok(`${signing.waybill_number} signed for by ${receivedBy}.`);
      setSigning(null); setReceivedBy(""); setIdSeen(""); setCollected("");
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
                <SelectAll checked={picked.allChosen} onChange={picked.all} />
                <th>Waybill</th><th>Recipient</th><th>Address</th>
                <th>Driver</th><th className="num">To collect</th>
                <th>Raised</th><th className="actions" />
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
                  <SelectRow checked={picked.has(w.id)}
                             onChange={() => picked.toggle(w.id)} />
                  <td className="mono">
                    {/* The waybill, not the patient. The row already opens the
                        patient; the chain of custody — dispatched when, signed
                        by whom, why it failed — lives only on the waybill, and
                        nothing linked to it. */}
                    <EntityLink kind="waybill" id={w.id}>{w.waybill_number}</EntityLink>
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
                  <td>
                    {/* The driver's name opens the driver. It was a string
                        that led nowhere, which is no use when the question is
                        "ring them" or "what else are they carrying". */}
                    {w.driver_profile_id
                      ? <EntityLink kind="driver" id={w.driver_profile_id}>
                          {w.driver}
                        </EntityLink>
                      : w.driver || <span className="muted">—</span>}
                    {w.driver_phone && (
                      <div className="muted small">{w.driver_phone}</div>
                    )}
                  </td>
                  <td className="num mono">
                    {w.cod_amount
                      ? <>
                          {money(w.cod_amount)}
                          {w.delivery_fee > 0 && (
                            <div className="muted small">
                              incl. {money(w.delivery_fee)} delivery
                            </div>
                          )}
                        </>
                      : w.delivery_fee
                        ? <span className="muted small">
                            {money(w.delivery_fee)} fee
                          </span>
                        : <span className="muted">—</span>}
                    {w.cod_collected > 0 && !w.cod_settled_at && (
                      <div><span className="badge warn">
                        {money(w.cod_collected)} not handed in
                      </span></div>
                    )}
                  </td>
                  <td>{fmtDateTime(w.created_at)}</td>
                  <RowActions>
                    {w.status === "pending" && (
                      <button className="btn primary sm"
                        onClick={() => { setSending(w); setDriverId(""); }}>
                        Send out
                      </button>
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
                <tr><td colSpan={8} className="muted pad">Nothing here.</td></tr>
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
            {signing.cod_amount > 0 && (
              <>
                <label>
                  Collected at the door
                  <input type="number" step="0.01" value={collected}
                    onChange={(e) => setCollected(e.target.value)}
                    placeholder={signing.cod_amount.toFixed(2)} />
                </label>
                <p className="muted small">
                  {money(signing.cod_amount)} to collect
                  {signing.delivery_fee > 0
                    && `, including ${money(signing.delivery_fee)} for the delivery`}.
                  This stays with the driver until the round is handed in — it
                  is not counted against the counter's till, because it is not
                  in the counter's till.
                </p>
              </>
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

      {sending && (
        <div className="modal-backdrop" onClick={() => setSending(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Send out {sending.waybill_number}</h2>
            <p className="muted">
              To {sending.recipient} · {sending.address}
            </p>
            {sending.cod_amount > 0 && (
              <p className="alert warn">
                The driver is to collect {money(sending.cod_amount)} at the door
                {sending.delivery_fee > 0
                  && `, of which ${money(sending.delivery_fee)} is the delivery fee`}.
              </p>
            )}
            <label>
              Driver
              <Select
                value={driverId}
                onChange={setDriverId}
                options={[
                  { value: "", label: "Not assigned yet" },
                  ...drivers.map((d) => ({
                    value: String(d.id),
                    // Said here rather than only in the refusal, so nobody
                    // picks a name and then finds out why they cannot.
                    label: d.full_name
                      + (d.licence_expired ? " · licence expired" : "")
                      + (d.over_cod_limit ? " · over cash limit" : ""),
                  })),
                ]}
              />
            </label>
            {!drivers.length && (
              <p className="muted small">
                No drivers are set up. A delivery can still go out unassigned,
                but nothing then records who had it.
              </p>
            )}
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setSending(null)}>Cancel</button>
              <BusyButton className="btn primary" onClick={dispatch}
                busyLabel="Sending…">
                Send out
              </BusyButton>
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
      <BulkBar count={picked.count} noun="delivery" onClear={picked.clear}>
        <Select
          value={bulkDriver}
          onChange={setBulkDriver}
          ariaLabel="Driver for the round"
          options={[
            { value: "", label: "Pick a driver…" },
            ...drivers.map((d) => ({
              value: String(d.id),
              label: d.full_name
                + (d.licence_expired ? " · licence expired" : "")
                + (d.over_cod_limit ? " · over cash limit" : ""),
            })),
          ]}
        />
        <BusyButton className="btn primary sm" onClick={dispatchAll}
                    disabled={!bulkDriver
                      || !picked.rows.some((w) => w.status === "pending")}
                    busyLabel="Sending…">
          Send the round out
        </BusyButton>
        {/* What the round is carrying. A supervisor deciding who to send
            should see the number before they choose, not after. */}
        {picked.rows.some((w) => w.cod_amount) && (
          <span className="bulk-count">
            collecting{" "}
            <b>{money(picked.rows.reduce((n, w) => n + (w.cod_amount ?? 0), 0))}</b>
          </span>
        )}
      </BulkBar>
    </div>
  );
}
