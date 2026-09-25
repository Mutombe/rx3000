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
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowClockwise, Check, ShoppingCart, Warning } from "@phosphor-icons/react";

import { api, errorText, fmtDate, money } from "../api";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { EntityLink, FilterToggle } from "./Filters";
import { useToast } from "./Toast";
import BusyButton from "./BusyButton";
import { useConfirm } from "./Confirm";
import Th from "./Th";

/** What the morning sweep can find, worst first. Labelled the way a person
 *  would say them rather than the way they are stored.
 *
 *  "At another branch" is the one with a remedy attached: the medicine exists,
 *  it is just in the wrong shop, and the fix is a transfer this afternoon
 *  rather than an order next week. A single-shop pharmacy never sees it. */
const KINDS: [string, string][] = [
  ["expired", "Expired"],
  ["out_of_stock", "Out of stock"],
  ["empty_here", "At another branch"],
  ["expiring", "Expiring soon"],
  ["below_reorder", "Running low"],
];

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
  const confirm = useConfirm();
  const [items, setItems] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [unseenOnly, setUnseenOnly] = useState(false);
  const [kind, setKind] = useState("all");

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

  // WHAT KIND OF FINDING, AND HOW MANY OF EACH.
  //
  // Two hundred findings of four different kinds in one list is a list
  // nobody works: expired stock, an empty shelf and a line near its reorder
  // level are three different jobs done by three different people at three
  // different times. Counted here rather than asked of the server, because
  // the whole standing list is already in hand and a round trip to filter
  // two hundred rows somebody is looking at is a round trip for nothing.
  const kinds = useMemo(() => {
    const seen = new Map<string, number>();
    for (const a of items) seen.set(a.kind, (seen.get(a.kind) ?? 0) + 1);
    return seen;
  }, [items]);

  const shown = useMemo(
    () => (kind === "all" ? items : items.filter((a) => a.kind === kind)),
    [items, kind]);

  const worth = shown.reduce((sum, a) => sum + a.worth, 0);
  const urgent = shown.filter((a) => a.urgency >= 3).length;

  /** Say "I have read all of these" in one go.
   *
   *  A list of two hundred acknowledged one row at a time is a list nobody
   *  acknowledges, so the unread count stops meaning anything and the
   *  filter built on it stops being useful. */
  async function readAll() {
    const unread = shown.filter((a) => !a.seen);
    if (!unread.length) return;
    const ok = await confirm({
      title: `Mark ${unread.length} finding(s) as read?`,
      body: "They stay on the list. Marking one read says somebody has seen "
          + "it, not that it has been dealt with: a finding disappears when "
          + "it stops being true, which the morning sweep decides.",
      confirmLabel: "Mark them read",
    });
    if (!ok) return;
    setItems((all) => all.map((x) =>
      unread.some((u) => u.id === x.id) ? { ...x, seen: true } : x));
    let failed = 0;
    for (const a of unread) {
      try { await api.post(`/api/stock/alerts/${a.id}/seen`, {}); }
      catch { failed += 1; }
    }
    if (failed) {
      toast.error(`${failed} of them could not be marked. The list will say `
                  + "which when it reloads.");
      load();
    } else {
      toast.ok(`${unread.length} marked as read.`);
    }
  }

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
          <FilterToggle checked={unseenOnly} onChange={setUnseenOnly}
                        hint="Hide findings somebody has already looked at">
            Only what nobody has read
          </FilterToggle>
          <button type="button" className="btn secondary"
                  onClick={readAll}
                  disabled={!shown.some((a) => !a.seen)}>
            <Check size={13} /> Mark these read
          </button>
          <Link className="btn secondary" to="/orders">
            <ShoppingCart size={13} /> Order what is short
          </Link>
          <BusyButton className="btn secondary" onClick={lookNow}
                      icon={ArrowClockwise} busyLabel="Looking…">
            Look now
          </BusyButton>
        </div>
      </div>

      {/* NARROWED BY THE JOB, NOT BY A SEARCH BOX.
          Expired stock, an empty shelf and a line near its reorder level are
          three different jobs done by different people at different times,
          and a single list of two hundred is one nobody works down. Each
          carries its own count, so the choice is made knowing what is
          behind it. */}
      {items.length > 0 && (
        <div className="seg sw-kinds" role="group" aria-label="Which findings">
          <button type="button" className={kind === "all" ? "on" : ""}
                  onClick={() => setKind("all")}>
            Everything <span className="tab-count">{items.length}</span>
          </button>
          {KINDS.filter(([key]) => kinds.get(key)).map(([key, label]) => (
            <button key={key} type="button"
                    className={kind === key ? "on" : ""}
                    onClick={() => setKind(key)}>
              {label} <span className="tab-count">{kinds.get(key)}</span>
            </button>
          ))}
        </div>
      )}

      <Refreshable
        loading={loading}
        hasData={shown.length > 0}
        skeleton={<TableSkeleton cols={5} rows={8}
                                 widths={["26ch", "30ch", "10ch", "12ch", "8ch"]} />}
      >
        <div className="dt-scroll">
          <table className="dt sw-table">
            {/* WIDTHS, BECAUSE THE TABLE IS LAID OUT FIXED.
                Without them a fixed layout divides the width equally, and
                five equal columns at 1366 gave every one of them 217px: the
                finding needed 491 and was cut off mid-word, the two buttons
                needed 201 and lost the second one, while a money figure and
                a date sat in 217px each with room to spare.

                The finding takes what is left over, which is the column
                somebody actually reads. */}
            <colgroup>
              <col />
              <col className="sw-col-med" />
              <col className="sw-col-worth" />
              <col className="sw-col-since" />
              <col className="sw-col-acts" />
            </colgroup>
            <thead>
              <tr>
                <Th>What</Th>
                <Th>Medicine</Th>
                <Th className="num">Worth</Th>
                <Th>Since</Th>
                <th className="actions" />
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => (
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
                  <td className="num">{a.worth > 0.005 ? money(a.worth) : "none"}</td>
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
