/** This till, its licence, and whether the pharmacy is actually protected.
 *
 *  The backup panel leads because it is the one thing on this screen that ends
 *  a business if it is neglected. A pharmacy will not run its own backups; if
 *  the button is buried, nobody presses it, and the software may as well not
 *  have the feature.
 *
 *  The station panel exists for support. "It does not work" is unanswerable
 *  without knowing which of four tills, on what version, against which
 *  database — and a screenshot of this page answers all of it at once.
 */
import { useEffect, useState } from "react";
import { api, fmtDateTime, errorText  } from "../api";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

interface Licence {
  state: string; licensed_to: string; expires_on: string | null;
  days_remaining: number | null; tills_licensed: number | null;
  blocking: boolean; message: string; key_fingerprint?: string;
}
interface Info {
  product: string; version: string; build: string; station_id: string;
  computer_name: string; platform: string; python: string;
  environment: string; is_production: boolean; jurisdiction: string;
  pharmacy: string; registration_no: string; database: string;
  trading_period: string | null; next_rx_number: number | null;
  next_sale_number: number | null; server_time: string; licence: Licence;
}
interface BackupFile { name: string; size_mb: number; taken_at: string; note: string }
interface BackupStatus {
  directory: string; count: number; keep: number; age_hours: number | null;
  protected: boolean; message: string; latest: BackupFile | null;
}

const LICENCE_TONE: Record<string, string> = {
  active: "ok", perpetual: "ok", expiring: "warn",
  grace: "warn", expired: "error", unlicensed: "warn",
};

export default function System() {
  const [info, setInfo] = useState<Info | null>(null);
  const [backups, setBackups] = useState<{ status: BackupStatus; files: BackupFile[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const toast = useToast();

  function load() {
    setLoading(true);
    api.get<Info>("/api/system/info").then(setInfo).catch((e) => toast.error(errorText(e)));
    api
      .get<{ status: BackupStatus; files: BackupFile[] }>("/api/system/backups")
      .then(setBackups)
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function takeBackup() {
    setBusy(true);
    try {
      const res = await api.post<{ name: string; size_mb: number; tables: number }>(
        "/api/system/backups", { note });
      toast.ok(`${res.name} taken and verified — ${res.size_mb} MB, ${res.tables} tables.`);
      setNote("");
      load();
    } catch (e: any) {
      // A failed backup deletes itself rather than leaving something to rely
      // on, so the message is the whole story and is shown as written.
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const lic = info?.licence;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>This till</h1>
          <p className="muted">
            {info ? `${info.product} ${info.version} (build ${info.build}) · ${info.station_id}` : ""}
          </p>
        </div>
      </header>

      {/* Backups first: the only thing here that ends a business if neglected. */}
      <section className="card">
        <h3>Backups</h3>
        <p className={backups?.status.protected ? "muted" : "alert error"}>
          {backups?.status.message}
        </p>
        <div className="dt-filters">
          <label>
            Note
            <input value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="Before the month-end close" />
          </label>
          <button className="btn primary" disabled={busy} onClick={takeBackup}>
            {busy ? "Taking and verifying…" : "Back up now"}
          </button>
        </div>
        <p className="muted small">
          Every backup is opened, integrity-checked and its row counts compared
          against the live database before it is kept. One that fails is deleted
          rather than left to be relied on. Holding {backups?.status.keep} in{" "}
          {backups?.status.directory}.
        </p>

        <Refreshable
          loading={loading}
          hasData={!!backups?.files.length}
          skeleton={<TableSkeleton cols={3} rows={4} widths={["26ch", "10ch", "22ch"]} />}
        >
          <table className="dt">
            <thead>
              <tr><th>File</th><th className="num">Size</th><th>Taken</th></tr>
            </thead>
            <tbody>
              {backups?.files.map((f) => (
                <tr key={f.name}>
                  <td className="mono">
                    {f.name}
                    {f.note && <div className="muted small">{f.note}</div>}
                  </td>
                  <td className="num">{f.size_mb} MB</td>
                  <td>{fmtDateTime(f.taken_at)}</td>
                </tr>
              ))}
              {!backups?.files.length && !loading && (
                <tr><td colSpan={3} className="muted pad">
                  No backup has ever been taken.
                </td></tr>
              )}
            </tbody>
          </table>
        </Refreshable>
      </section>

      <section className="card">
        <h3>Licence</h3>
        {lic && (
          <>
            <p className={`alert ${LICENCE_TONE[lic.state] ?? ""}`}>
              <strong>{lic.state}</strong>
              {lic.message ? ` — ${lic.message}` : " — nothing to do."}
            </p>
            <dl className="kv">
              <dt>Licensed to</dt><dd>{lic.licensed_to}</dd>
              {lic.key_fingerprint && (<><dt>Key</dt><dd className="mono">{lic.key_fingerprint}</dd></>)}
              {lic.expires_on && (<><dt>Expires</dt><dd>{lic.expires_on}</dd></>)}
              {lic.tills_licensed && (<><dt>Tills</dt><dd className="num">{lic.tills_licensed}</dd></>)}
            </dl>
            <p className="muted small">
              A licence matter never stops this till dispensing. Refusing to open
              a till over an invoice puts patients between a vendor and its
              billing, which is not where they belong.
            </p>
          </>
        )}
      </section>

      <section className="card">
        <h3>Station</h3>
        <dl className="kv">
          <dt>Station</dt><dd className="mono">{info?.station_id}</dd>
          <dt>Computer</dt><dd>{info?.computer_name}</dd>
          <dt>Platform</dt><dd>{info?.platform} · Python {info?.python}</dd>
          <dt>Environment</dt>
          <dd>
            {info?.environment}
            {info && !info.is_production && (
              <span className="badge warn">simulators permitted</span>
            )}
          </dd>
          <dt>Jurisdiction</dt><dd>{info?.jurisdiction}</dd>
          <dt>Pharmacy</dt><dd>{info?.pharmacy} · {info?.registration_no}</dd>
          <dt>Database</dt><dd className="mono">{info?.database}</dd>
          <dt>Trading period</dt><dd className="mono">{info?.trading_period}</dd>
          <dt>Next Rx / sale</dt>
          <dd className="num">{info?.next_rx_number} / {info?.next_sale_number}</dd>
          <dt>Server time</dt><dd>{fmtDateTime(info?.server_time)}</dd>
        </dl>
      </section>
    </div>
  );
}
