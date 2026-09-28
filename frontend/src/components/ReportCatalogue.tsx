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
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import ReportRunner, { ReportDef } from "./ReportRunner";
import { Block, Figure } from "./Skeleton";

/** Six stand-in rows while the catalogue is fetched. Six is about what fits
 *  above the fold, so the list does not grow into the reader as it lands. */
const GHOST_ITEMS = [0, 1, 2, 3, 4, 5];

export default function ReportCatalogue() {
  const [reports, setReports] = useState<ReportDef[] | null>(null);
  const [open, setOpen] = useState<ReportDef | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.get<{ reports: ReportDef[] }>("/api/reports/catalogue")
      .then((r) => setReports(r.reports))
      .catch(() => setReports([]));
  }, []);

  // Opened straight to one report by `?report=<key>`, so another screen can
  // link to the report it is summarising — the operations dashboard to its
  // holds — instead of to a list of a hundred to search. Once, on arrival:
  // pressing Back returns to the catalogue rather than reopening the report.
  const [params] = useSearchParams();
  const wanted = params.get("report");
  useEffect(() => {
    if (!reports || !wanted) return;
    const hit = reports.find((r) => r.key === wanted);
    if (hit) setOpen(hit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports, wanted]);

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

  const count = reports?.length ?? 0;
  const shown = Object.values(groups).reduce((n, g) => n + g.length, 0);

  return (
    <div className="card">
      {/* SCOPED LOADING.
          This used to return a grey table INSTEAD of the screen, so arriving at
          Reports showed neither the heading nor the search box, and the one
          thing a manager does here first is type a word into that box. The
          heading, its sentence and the search are written in this file and are
          the same on every visit. Only the count and the list are fetched. */}
      <div className="rc-head">
        <div>
          <h3 style={{ margin: 0 }}>
            <Figure ready={!!reports} w="3ch">{count}</Figure> reports
          </h3>
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

      {/* "No report matches" is only true once the catalogue has arrived. Before
          that the list is unknown, not empty, and the two must not read alike. */}
      {!reports ? (
        <div className="rc-group" aria-busy="true">
          <h4 className="rc-module"><Block w="14ch" h="1em" className="sk-val" /></h4>
          <div className="rc-list">
            {GHOST_ITEMS.map((i) => (
              <div key={i} className="rc-item" aria-hidden="true">
                <span className="rc-item-title">
                  <Block w="22ch" h="1em" className="sk-val" />
                </span>
                <span className="rc-item-purpose">
                  <Block w="36ch" h="1em" className="sk-val" />
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : shown === 0 ? (
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
                      <span className="badge muted rc-lock">Manager</span>
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
