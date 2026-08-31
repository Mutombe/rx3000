/** Drivers — the people who carry medicine out of the shop.
 *
 *  A driver used to be a foreign key to `users`, which meant a driver needed a
 *  login. Most do not have one and should not: the runner on the motorbike
 *  never touches the dispensing system, and the courier used on Saturdays is
 *  not staff at all. So a delivery said "Driver: —" and there was nowhere to
 *  keep a phone number, a vehicle, or a licence that expires.
 *
 *  The list is ordered by what somebody is carrying rather than alphabetically,
 *  because the question at four in the afternoon is never "who works here", it
 *  is "who is still out and holding how much of my money".
 */
import { useEffect, useState } from "react";
import { Plus, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money, prefetchRoute } from "../api";
import { EntityLink } from "../components/Filters";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import DriverForm from "../components/DriverForm";

export interface Driver {
  id: number; code: string; full_name: string; phone: string;
  alternate_phone: string; national_id: string;
  user_id: number | null; branch_id: number | null; branch: string;
  vehicle_type: string; vehicle_registration: string;
  licence_number: string; licence_expiry: string | null;
  licence_expired: boolean; licence_days_left: number | null;
  cash_float: number; cod_limit: number; active: boolean; notes: string;
  out: number; delivered: number; failed: number; total_runs: number;
  failure_rate: number | null;
  cash_holding: number; cod_to_collect: number; over_cod_limit: boolean;
}

interface Road {
  drivers: {
    driver_id: number | null; driver: string; phone: string;
    deliveries: number; to_collect: number; holding: number;
    fees: number; oldest: string | null;
  }[];
  deliveries: number; to_collect: number;
  uncollected_cash: number; fees_out: number;
}

type Tab = "working" | "road" | "retired";

const VEHICLE: Record<string, string> = {
  motorbike: "Motorbike", car: "Car", van: "Van",
  bicycle: "Bicycle", on_foot: "On foot",
};

export default function Drivers() {
  const [rows, setRows] = useState<Driver[]>([]);
  const [retired, setRetired] = useState<Driver[]>([]);
  const [road, setRoad] = useState<Road | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const toast = useToast();

  const TABS: TabDef<Tab>[] = [
    { key: "working", label: "Drivers", count: rows.length },
    { key: "road", label: "On the road", count: road?.deliveries,
      hint: "Out now, and what they are carrying" },
    { key: "retired", label: "Retired", count: retired.length },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "working");

  function load() {
    setLoading(true);
    Promise.all([
      api.get<Driver[]>("/api/drivers"),
      api.get<Driver[]>("/api/drivers?include_retired=true"),
      api.get<Road>("/api/deliveries/on-the-road"),
    ])
      .then(([active, all, r]) => {
        setRows(active);
        setRetired(all.filter((d) => !d.active));
        setRoad(r);
      })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function retire(d: Driver) {
    try {
      const r = await api.delete<{ message: string }>(`/api/drivers/${d.id}`);
      toast.ok(r.message);
      load();
    } catch (e) {
      // The server refuses while a driver is out with money, and says how
      // much. Shown as written — "settle the round first" is the answer.
      toast.error(errorText(e));
    }
  }

  const holding = rows.reduce((s, d) => s + d.cash_holding, 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Drivers</h1>
          <p className="muted">
            {rows.length
              ? `${rows.length} driver${rows.length === 1 ? "" : "s"}`
                + (road?.deliveries ? `, ${road.deliveries} delivery(ies) out` : "")
                + (holding ? `, ${money(holding)} of shop money being carried` : "")
              : "Nobody is set up to deliver yet."}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => setAdding(true)}>
            <Plus size={14} weight="bold" /> New driver
          </button>
        </div>
      </header>

      {adding && (
        <DriverForm onClose={() => setAdding(false)} onSaved={() => { setAdding(false); load(); }} />
      )}

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "road" ? (
        <Refreshable loading={loading} hasData={!!road?.drivers.length}
          skeleton={<TableSkeleton cols={5} rows={4} />}>
          {road && (
            <>
              <div className="wc-bands" style={{ marginBottom: 14 }}>
                <div className="wl-stat">
                  <b>{road.deliveries}</b><span>out now</span>
                </div>
                <div className="wl-stat">
                  <b>{money(road.to_collect)}</b><span>still to collect</span>
                </div>
                <div className={`wl-stat${road.uncollected_cash ? " wc-abandoned" : ""}`}>
                  <b className={road.uncollected_cash ? "tone-danger" : undefined}>
                    {money(road.uncollected_cash)}
                  </b>
                  <span>collected, not handed in</span>
                </div>
                <div className="wl-stat">
                  <b>{money(road.fees_out)}</b><span>delivery fees riding on it</span>
                </div>
              </div>
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Driver</th><th className="num">Out</th>
                      <th className="num">To collect</th>
                      <th className="num">Holding</th>
                      <th>Longest out since</th>
                    </tr>
                  </thead>
                  <tbody>
                    {road.drivers.map((d) => (
                      <tr key={d.driver_id ?? "none"}>
                        <td>
                          {d.driver_id
                            ? <EntityLink kind="driver" id={d.driver_id}>{d.driver}</EntityLink>
                            : <span className="muted">{d.driver}</span>}
                          {d.phone && <div className="muted small">{d.phone}</div>}
                        </td>
                        <td className="num">{d.deliveries}</td>
                        <td className="num mono">{money(d.to_collect)}</td>
                        <td className="num mono">{money(d.holding)}</td>
                        <td>{d.oldest ? fmtDate(d.oldest) : <span className="muted">—</span>}</td>
                      </tr>
                    ))}
                    {!road.drivers.length && (
                      <tr><td colSpan={5} className="muted pad">
                        Nothing is out.
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Refreshable>
      ) : (
        <Refreshable
          loading={loading}
          hasData={(tab === "retired" ? retired : rows).length > 0}
          skeleton={<TableSkeleton cols={6} rows={5} />}
        >
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <th>Driver</th><th>Vehicle</th><th>Licence</th>
                  <th className="num">Out</th>
                  <th className="num">Holding</th>
                  <th className="num">Failed</th>
                  <th className="actions" />
                </tr>
              </thead>
              <tbody>
                {(tab === "retired" ? retired : rows).map((d) => (
                  <RowLink key={d.id} to={`/drivers/${d.id}`} prefetch={prefetchRoute}
                    className={d.licence_expired || d.over_cod_limit ? "row-flag" : ""}>
                    <td>
                      <b>{d.full_name}</b>
                      <div className="muted small">
                        {d.phone}{d.branch && ` · ${d.branch}`}
                      </div>
                    </td>
                    <td>
                      {VEHICLE[d.vehicle_type] || d.vehicle_type}
                      {d.vehicle_registration && (
                        <div className="muted small mono">{d.vehicle_registration}</div>
                      )}
                    </td>
                    <td>
                      {d.licence_expiry ? (
                        <>
                          {fmtDate(d.licence_expiry)}
                          {/* An expired licence is a driver who should not be
                              on the road, and nobody finds that out from a
                              filing cabinet at half past four. */}
                          {d.licence_expired && (
                            <div><span className="badge bad">
                              <Warning size={12} weight="fill" /> expired
                            </span></div>
                          )}
                          {!d.licence_expired && d.licence_days_left !== null
                            && d.licence_days_left < 30 && (
                            <div><span className="badge warn">
                              {d.licence_days_left} days left
                            </span></div>
                          )}
                        </>
                      ) : <span className="muted">not recorded</span>}
                    </td>
                    <td className="num">{d.out || <span className="muted">—</span>}</td>
                    <td className="num mono">
                      {d.cash_holding ? money(d.cash_holding) : <span className="muted">—</span>}
                      {d.over_cod_limit && (
                        <div><span className="badge bad">over limit</span></div>
                      )}
                    </td>
                    <td className="num">
                      {d.failure_rate === null
                        ? <span className="muted">—</span>
                        : `${d.failure_rate}%`}
                    </td>
                    <RowActions>
                      {d.active && (
                        <button className="btn ghost sm"
                          onClick={() => retire(d)}>Retire</button>
                      )}
                    </RowActions>
                  </RowLink>
                ))}
                {!(tab === "retired" ? retired : rows).length && !loading && (
                  <tr><td colSpan={7} className="muted pad">
                    {tab === "retired"
                      ? "Nobody has been retired."
                      : "No drivers yet. Add one and deliveries can be assigned."}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Refreshable>
      )}
    </div>
  );
}
