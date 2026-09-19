/** What the shelves are trying to say, without being asked.
 *
 *  Everything here was already visible somewhere: a badge counts lines below
 *  reorder level, the dashboard lists what to do today, and there is a report
 *  for each of it. All of that needs somebody to open the screen on the day it
 *  matters. This is the list of what is NEWLY wrong, which no report can say,
 *  because only a record of what was already known can tell the difference.
 *
 *  RANKED BY MONEY, NOT BY CATEGORY
 *
 *  The same rule the dashboard uses. A pharmacy with nine hundred lines at
 *  their reorder level does not need them alphabetically; it needs the one
 *  worth forty thousand first. Urgency breaks the tie above money, so expired
 *  stock and an empty shelf of something people still ask for come before a
 *  line that is merely low.
 *
 *  ACKNOWLEDGING IS NOT FIXING
 *
 *  Reading that a batch expires in a fortnight does not make it stop expiring.
 *  Seen dims the row and keeps it; the finding leaves the list when it stops
 *  being true, which the sweep decides, not the reader.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowClockwise, Check, Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { EntityLink } from "./Filters";
import { useToast } from "./Toast";
import BusyButton from "./BusyButton";

interface Alert {
  id: number;
  kind: string;
  what: string;
  product_id: number;
  product: string;
  branch_id: number | null;
  branch: string;
  detail: string;
  worth: number;
  urgency: number;
  since: string;
  seen: boolean;
  to: string;
}

const TONE: Record<number, string> = { 3: "danger", 2: "warn", 1: "muted" };

export default function StockWatch() {
  const toast = useToast();
  const [items, setItems] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [unseenOnly, setUnseenOnly] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get<{ items: Alert[] }>(`/api/stock/alerts?unseen_only=${unseenOnly}`)
      .then((r) => setItems(r.items))
      .catch((e) => toast.error(errorText(e, "The stock findings could not be read.")))
      .finally(() => setLoading(false));
  }, [unseenOnly, toast]);

  useEffect(load, [load]);

  async function lookNow() {
    // Somebody who has just booked in a delivery wants the list to stop saying
    // they are out of it. Telling them to wait until tomorrow morning is how a
    // screen loses its credibility.
    try {
      const r = await api.post<{ new_total: number; resolved: number }>(
        "/api/stock/alerts/sweep", {});
      toast.ok(r.new_total || r.resolved
        ? `${r.new_total} new, ${r.resolved} no longer true.`
        : "Nothing has changed since the last look.");
      load();
    } catch (e) {
      toast.error(errorText(e, "The shelves could not be checked just now."));
    }
  }

  async function acknowledge(a: Alert) {
    // Optimistic: the row dims on the click. This says "I have read it", and
    // being wrong about that costs nothing anybody can measure.
    setItems((all) => all.map((x) => (x.id === a.id ? { ...x, seen: true } : x)));
    try {
      await api.post(`/api/stock/alerts/${a.id}/seen`, {});
    } catch (e) {
      setItems((all) => all.map((x) => (x.id === a.id ? { ...x, seen: false } : x)));
      toast.error(errorText(e, "That could not be marked as seen."));
    }
  }

  const worth = items.reduce((sum, a) => sum + a.worth, 0);
  const urgent = items.filter((a) => a.urgency >= 3).length;

  return (
    <>
      <div className="sw-head">
        <div>
          <p className="muted sw-say">
            {items.length === 0 && !loading
              ? "Nothing on the shelves needs saying. The sweep runs each morning at ten past seven."
              : <>
                  <b>{items.length.toLocaleString()}</b> finding
                  {items.length === 1 ? "" : "s"} standing
                  {urgent > 0 && <>, <b>{urgent}</b> needing something done today</>}
                  {worth > 0.005 && <>, {money(worth)} of stock behind them</>}.
                </>}
          </p>
        </div>
        <div className="sw-acts">
          <label className="sw-only">
            <input type="checkbox" checked={unseenOnly}
                   onChange={(e) => setUnseenOnly(e.target.checked)} />
            Only what nobody has read
          </label>
          <BusyButton className="btn secondary" onClick={lookNow}
                      icon={ArrowClockwise} busyLabel="Looking…">
            Look now
          </BusyButton>
        </div>
      </div>

      <Refreshable
        loading={loading}
        hasData={items.length > 0}
        skeleton={<TableSkeleton cols={5} rows={8}
                                 widths={["26ch", "30ch", "10ch", "12ch", "8ch"]} />}
      >
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>What</th>
                <th>Medicine</th>
                <th className="num">Worth</th>
                <th>Since</th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className={a.seen ? "row-muted" : undefined}>
                  <td className="sw-what">
                    <span className={`badge ${TONE[a.urgency] ?? "muted"}`}>
                      {a.urgency >= 3 && <Warning size={11} weight="fill" />} {a.what}
                    </span>
                    <div className="muted small sw-detail">{a.detail}</div>
                    {a.branch && <div className="muted small">{a.branch}</div>}
                  </td>
                  <td>
                    <EntityLink kind="product" id={a.product_id}>{a.product}</EntityLink>
                  </td>
                  <td className="num">{a.worth > 0.005 ? money(a.worth) : "—"}</td>
                  <td className="nowrap">{fmtDate(a.since)}</td>
                  <td className="actions">
                    {/* Somewhere to go and do something about it. An alert
                        that does not lead anywhere is a complaint. */}
                    <Link className="btn small ghost" to={a.to}>Deal with it</Link>
                    {!a.seen && (
                      <button type="button" className="btn small ghost"
                              onClick={() => acknowledge(a)}
                              title="I have read this. It stays until it stops being true.">
                        <Check size={13} /> Read
                      </button>
                    )}
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
