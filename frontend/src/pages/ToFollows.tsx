/** To follows — the medicine the pharmacy owes, and who can be telephoned today.
 *
 *  The incumbent has this list. What it cannot do is tell you which of these
 *  can be honoured *now*, because it does not connect a delivery arriving to a
 *  patient waiting. That is what the "Ready to hand over" tab is, and it is the
 *  reason to open this screen in the morning rather than when somebody
 *  complains.
 *
 *  The settle button updates optimistically. Handing over stock that is already
 *  on the shelf is not a request that meaningfully fails, and a pharmacist with
 *  a patient at the counter should not watch a spinner to find that out. If the
 *  server does refuse, the row snaps back and says why.
 */
import { useEffect, useMemo, useState } from "react";
import { api, fmtDate, fmtDateTime, prefetchRoute, errorText  } from "../api";
import { EntityLink } from "../components/Filters";
import { useToast } from "../components/Toast";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import BusyButton from "../components/BusyButton";
import Pagination from "../components/Pagination";
import { useClientPage } from "../hooks/useClientPage";

interface Owed {
  id: number;
  reference: string;
  status: string;
  patient_id: number | null;
  patient_name: string;
  patient_phone: string;
  product_id: number;
  product_name: string;
  quantity_owed: number;
  quantity_settled: number;
  quantity_outstanding: number;
  quantity_on_hand: number;
  can_settle_now: boolean;
  can_settle_partially: boolean;
  promised_for: string | null;
  overdue: boolean;
  notes: string;
  created_at: string;
}

interface Totals {
  outstanding_items: number;
  outstanding_units: number;
  ready_to_hand_over: number;
  overdue: number;
}

type Tab = "ready" | "all" | "settled";

export default function ToFollows() {
  const [ready, setReady] = useState<Owed[]>([]);
  const [all, setAll] = useState<Owed[]>([]);
  const [settled, setSettled] = useState<Owed[]>([]);
  const [totals, setTotals] = useState<Totals | null>(null);
  const toast = useToast();
  const [cancelling, setCancelling] = useState<Owed | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  // Rows the server has not confirmed yet. They are dimmed and made
  // non-interactive, because acting on one could only fail.
  const [saving, setSaving] = useState<Set<number>>(new Set());

  const TABS: TabDef<Tab>[] = [
    {
      key: "ready",
      label: "Ready to hand over",
      count: ready.length,
      hint: "Owed, and now in stock, the patients to telephone",
    },
    { key: "all", label: "Everything owed", count: all.length },
    { key: "settled", label: "Settled", count: settled.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "ready");

  function load() {
    setLoading(true);
    api
      .get<Owed[]>("/api/to-follows/ready")
      .then(setReady)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
    api.get<Owed[]>("/api/to-follows").then(setAll).catch(() => undefined);
    api.get<Owed[]>("/api/to-follows?status=settled").then(setSettled).catch(() => undefined);
    api.get<Totals>("/api/to-follows/summary").then(setTotals).catch(() => undefined);
  }

  useEffect(load, []);

  const rows = tab === "ready" ? ready : tab === "settled" ? settled : all;
  /* Paged in the browser. The endpoint returns everything on purpose — the
     totals above this table are the pharmacy's whole outstanding debt, and a
     page at a time would either make them wrong or cost a second round trip.
     The data stays whole; only the render is bounded. */
  const page = useClientPage(rows, 25);

  async function settle(owed: Owed, quantity?: number) {
    const amount = quantity ?? owed.quantity_outstanding;
    // Optimistic: the stock is on the shelf and the patient is at the counter.
    const before = { ready, all };
    const apply = (list: Owed[]) =>
      list
        .map((o) =>
          o.id === owed.id
            ? {
                ...o,
                quantity_settled: o.quantity_settled + amount,
                quantity_outstanding: o.quantity_outstanding - amount,
                status: o.quantity_outstanding - amount <= 0 ? "settled" : o.status,
              }
            : o,
        )
        .filter((o) => o.status !== "settled" || tab === "settled");
    setReady(apply(ready));
    setAll(apply(all));
    setSaving(new Set([...saving, owed.id]));
        try {
      await api.post(`/api/to-follows/${owed.id}/settle`, { quantity: amount });
      toast.ok(`${amount} of ${owed.product_name} handed to ${owed.patient_name}.`);
      load();
    } catch (e: any) {
      // Snap back and say why, rather than leaving a lie on the screen.
      setReady(before.ready);
      setAll(before.all);
      toast.error(errorText(e));
    } finally {
      const next = new Set(saving);
      next.delete(owed.id);
      setSaving(next);
    }
  }

  async function cancel() {
    if (!cancelling) return;
    try {
      await api.post(`/api/to-follows/${cancelling.id}/cancel`, { reason });
      toast.ok(`${cancelling.reference} written off.`);
      setCancelling(null);
      setReason("");
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  const headline = useMemo(() => {
    if (!totals) return "";
    if (!totals.outstanding_items) return "Nothing is owed.";
    const parts = [
      `${totals.outstanding_items} owed (${totals.outstanding_units} units)`,
    ];
    if (totals.ready_to_hand_over) parts.push(`${totals.ready_to_hand_over} ready now`);
    if (totals.overdue) parts.push(`${totals.overdue} past the promised date`);
    return parts.join(" · ");
  }, [totals]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>To follows</h1>
          <p className="muted">{headline}</p>
        </div>
      </header>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "ready" && !ready.length && (
        <p className="muted pad">
          Nothing owed is currently in stock. This list fills itself when a delivery
          arrives.
        </p>
      )}

      <Refreshable
        loading={loading}
        hasData={rows.length > 0}
        skeleton={
          /* Seven columns, six rows — the same footprint the real table takes,
             so nothing moves when the data lands. */
          <TableSkeleton cols={7} rows={6}
            widths={["10ch", "14ch", "18ch", "5ch", "5ch", "10ch", "16ch"]} />
        }
      >
      <div className="dt-scroll">
        <table className="dt">
          <thead>
            <tr>
              <th>Reference</th>
              <th>Patient</th>
              <th>Medicine</th>
              <th className="num">Owed</th>
              <th className="num">In stock</th>
              <th>Promised</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {page.items.map((o) => (
              <RowLink
                key={o.id}
                /* A walk-in has no patient record, so the row leads to the
                   medicine instead. Fabricating /patients/ for a missing id
                   would land on a page that cannot exist. */
                to={o.patient_id ? `/patients/${o.patient_id}` : `/products/${o.product_id}`}
                prefetch={prefetchRoute}
                className={[o.overdue ? "row-flag" : "",
                            saving.has(o.id) ? "is-saving" : ""].filter(Boolean).join(" ")}
              >
                <td className="mono">{o.reference}</td>
                <td>
                  {o.patient_id ? (
                    <EntityLink to={`/patients/${o.patient_id}`}>{o.patient_name}</EntityLink>
                  ) : (
                    <span className="muted">Walk-in</span>
                  )}
                  {o.patient_phone && <div className="muted small">{o.patient_phone}</div>}
                </td>
                <td>
                  <EntityLink to={`/products/${o.product_id}`}>{o.product_name}</EntityLink>
                </td>
                <td className="num">{o.quantity_outstanding}</td>
                <td className="num">{o.quantity_on_hand}</td>
                <td>
                  {o.promised_for ? fmtDate(o.promised_for) : <span className="muted">—</span>}
                  {o.overdue && <span className="badge warn">overdue</span>}
                </td>
                <RowActions>
                  {/* The verb is constant and the quantity is a chip beside it.
                      Written as one sentence — "Hand over 2" — the label changed
                      width on every row, so the column read as a ragged
                      paragraph and the number, which is the part being checked
                      against what is in your hand, was the least distinct thing
                      in it. */}
                  {o.status === "outstanding" && o.can_settle_now && (
                    <BusyButton className="btn primary sm" onClick={() => settle(o)}>
                      Hand over
                      <span className="btn-count">{o.quantity_outstanding}</span>
                    </BusyButton>
                  )}
                  {o.status === "outstanding" && o.can_settle_partially && (
                    <BusyButton className="btn sm" onClick={() => settle(o, o.quantity_on_hand)}>
                      Hand over
                      {/* A part-settlement says what it is against what is owed,
                          which is the whole reason to offer it. */}
                      <span className="btn-count">
                        {o.quantity_on_hand}<i>of</i>{o.quantity_outstanding}
                      </span>
                    </BusyButton>
                  )}
                  {o.status === "outstanding" && (
                    <button className="btn ghost sm" onClick={() => setCancelling(o)}>
                      Write off
                    </button>
                  )}
                  {o.status !== "outstanding" && (
                    <span className="badge">{o.status}</span>
                  )}
                </RowActions>
              </RowLink>
            ))}
            {!rows.length && tab !== "ready" && (
              <tr>
                <td colSpan={7} className="muted pad">
                  Nothing here.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <Pagination meta={page.meta} onPage={page.setPage} />
      </div>
      </Refreshable>

      {cancelling && (
        <div className="modal-backdrop" onClick={() => setCancelling(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Write off {cancelling.reference}</h2>
            <p className="muted">
              {cancelling.quantity_outstanding} × {cancelling.product_name} owed to{" "}
              {cancelling.patient_name || "a walk-in customer"}. Writing it off says the
              pharmacy no longer owes it. The patient got it elsewhere, or no longer
              needs it.
            </p>
            <label>
              Reason
              <input
                value={reason}
                autoFocus
                onChange={(e) => setReason(e.target.value)}
                placeholder="Patient sourced it elsewhere"
              />
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setCancelling(null)}>
                Keep it
              </button>
              <button className="btn danger" disabled={!reason.trim()} onClick={cancel}>
                Write off
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
