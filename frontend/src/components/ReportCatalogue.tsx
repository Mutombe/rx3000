/** Every report the system can run, in one place.
 *
 *  This screen exists because of how a pharmacy manager evaluates software:
 *  they open the Reports menu and count. The incumbent's four applications have
 *  roughly a hundred and twenty reports between them, and a short list reads as
 *  an unfinished product no matter how good the individual screens are.
 *
 *  So the count is stated plainly at the top, the list is searchable — a
 *  hundred and twenty items is past what anyone will scan, and every entry
 *  carries a sentence saying what question it answers. A list of report titles
 *  alone is a filing cabinet; a list with purposes is something a manager can
 *  actually choose from.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import ReportRunner, { ReportDef } from "./ReportRunner";
import { TableSkeleton } from "./Skeleton";

export default function ReportCatalogue() {
  const [reports, setReports] = useState<ReportDef[] | null>(null);
  const [open, setOpen] = useState<ReportDef | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.get<{ reports: ReportDef[] }>("/api/reports/catalogue")
      .then((r) => setReports(r.reports))
      .catch(() => setReports([]));
  }, []);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const matched = (reports ?? []).filter(
      (r) => !needle
        || r.title.toLowerCase().includes(needle)
        || r.purpose.toLowerCase().includes(needle)
        || r.module.toLowerCase().includes(needle),
    );
    const out: Record<string, ReportDef[]> = {};
    matched.forEach((r) => { (out[r.module] ||= []).push(r); });
    return out;
  }, [reports, q]);

  if (open) return <ReportRunner report={open} onBack={() => setOpen(null)} />;

  if (!reports) {
    return <div className="card"><TableSkeleton cols={2} rows={8} /></div>;
  }

  const count = reports.length;
  const shown = Object.values(groups).reduce((n, g) => n + g.length, 0);

  return (
    <div className="card">
      <div className="rc-head">
        <div>
          <h3 style={{ margin: 0 }}>{count} reports</h3>
          <p className="muted" style={{ margin: "4px 0 0" }}>
            Every one exports to Excel and CSV, and prints.
          </p>
        </div>
        <input
          className="rc-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search reports…"
          aria-label="Search reports"
        />
      </div>

      {shown === 0 ? (
        <div className="empty">No report matches “{q}”.</div>
      ) : (
        Object.entries(groups).map(([module, items]) => (
          <div key={module} className="rc-group">
            <h4 className="rc-module">
              {module} <span className="muted">{items.length}</span>
            </h4>
            <div className="rc-list">
              {items.map((r) => (
                <button key={r.key} className="rc-item" onClick={() => setOpen(r)}>
                  <span className="rc-item-title">
                    {r.title}
                    {r.step_up && (
                      // Said here rather than discovered at the point of
                      // clicking, so nobody queues up behind a report they
                      // cannot open.
                      <span className="badge muted rc-lock">manager</span>
                    )}
                  </span>
                  {r.purpose && <span className="rc-item-purpose">{r.purpose}</span>}
                </button>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
