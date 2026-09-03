/**
 * What each role may do in THIS pharmacy.
 *
 * The built-in defaults are defaults, and a default is all they can be. One
 * shop lets any cashier take a return because it is small and the owner is
 * always there; another lets nobody but a manager touch one because it had a
 * problem two years ago. Both are right about their own shop.
 *
 * Without this screen the first shop grants "take a return" to eleven people
 * one at a time, and again to every new starter — and what actually happens is
 * that the eleven people are made managers, after which the role column means
 * nothing and the audit trail says "manager" for everybody.
 *
 * WHAT THIS IS NOT
 *
 * It is the floor, not the ceiling. Per-person grants still sit on top of it
 * with their limits, hours and expiry, and a denial by name still beats
 * everything here. Moving a cell changes what a role gets by default; it does
 * not touch anybody's individual arrangement.
 *
 * ONE CELL AT A TIME
 *
 * Each toggle saves itself. The alternative — a draft grid and a Save button —
 * posts fifty booleans and overwrites whatever somebody else changed while the
 * screen was open, and a permissions screen is the last place a silent
 * overwrite should be possible.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "../api";
import { Panel } from "./RecordPage";
import { useToast } from "./Toast";
import { useSession } from "../session";

interface Cell {
  allowed: boolean;
  /** What the software ships with, so a change from standard can be marked. */
  default: boolean;
  /** Administrators cannot be reduced here. */
  fixed: boolean;
}

interface Row {
  capability: string;
  name: string;
  roles: Record<string, Cell>;
}

export default function RoleMatrix() {
  const session = useSession();
  // Optimistic until the server says otherwise.
  //
  // `can()` is false while the session is still loading, so gating the fetch on
  // it meant this panel was absent for as long as that took — tens of seconds
  // on a cold server, and permanently if the read failed. An administrator
  // reads that as the feature having been removed.
  //
  // The endpoint behind it requires staff.manage, so asking is safe: somebody
  // who may not gets a 403, the catch leaves this empty, and nothing renders.
  // The same outcome, reached by asking instead of by assuming the worst.
  const may = !session.known || session.can("staff.manage");
  const toast = useToast();

  const [roles, setRoles] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [saving, setSaving] = useState("");

  const load = useCallback(() => {
    if (!may) return;
    api.get<{ roles: string[]; rows: Row[] }>("/api/auth/role-matrix")
      .then((d) => { setRoles(d.roles); setRows(d.rows); })
      .catch(() => setRows([]));
  }, [may]);
  useEffect(load, [load]);

  if (session.known && !session.can("staff.manage")) return null;

  async function toggle(row: Row, role: string) {
    const cell = row.roles[role];
    if (cell.fixed) return;
    const key = `${row.capability}:${role}`;
    const wanted = !cell.allowed;

    // Moved on screen before the round trip, and put back if the server
    // refuses. A permission toggle that lags is one somebody clicks twice.
    setRows((prev) => prev.map((r) => r.capability !== row.capability ? r : {
      ...r, roles: { ...r.roles, [role]: { ...cell, allowed: wanted } },
    }));
    setSaving(key);
    try {
      const fresh = await api.put<{ rows: Row[] }>("/api/auth/role-matrix", {
        role, capability: row.capability, allowed: wanted,
      });
      setRows(fresh.rows);
      // Their own capabilities may have just changed.
      session.refresh();
    } catch (e) {
      setRows((prev) => prev.map((r) => r.capability !== row.capability ? r : {
        ...r, roles: { ...r.roles, [role]: cell },
      }));
      toast.error(errorText(e, "That could not be changed. Nothing was saved."));
    } finally {
      setSaving("");
    }
  }

  const changed = rows.reduce((n, r) => n + Object.values(r.roles)
    .filter((c) => c.allowed !== c.default).length, 0);

  return (
    <Panel
      title="What each role may do"
      aside={changed > 0 ? (
        <span className="badge muted">
          {changed} changed from standard
        </span>
      ) : undefined}
    >
      <p className="hint">
        The default for everybody in a role. Individual arrangements — a limit,
        a set of hours, an end date, or a refusal for one person — are set on
        that person's record and still take precedence over this.
      </p>
      <div className="dt-scroll">
        <table className="dt matrix">
          <caption className="sr-only">
            Capabilities against roles. Each cell is what that role may do by
            default in this pharmacy.
          </caption>
          <thead>
            <tr>
              <th scope="col">Can</th>
              {roles.map((r) => (
                <th key={r} scope="col" className="num">{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.capability}>
                <th scope="row">
                  {row.name}
                  <span className="mono muted cap-key">{row.capability}</span>
                </th>
                {roles.map((role) => {
                  const cell = row.roles[role];
                  if (!cell) return <td key={role} className="num">—</td>;
                  const key = `${row.capability}:${role}`;
                  const moved = cell.allowed !== cell.default;
                  return (
                    <td key={role} className="num">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={cell.allowed}
                        aria-label={`${row.name}: ${role}`}
                        disabled={cell.fixed || saving === key}
                        onClick={() => toggle(row, role)}
                        className={"perm-cell"
                          + (cell.allowed ? " is-on" : "")
                          + (cell.fixed ? " is-fixed" : "")
                          + (moved ? " is-moved" : "")}
                        title={cell.fixed
                          ? "An administrator's authority cannot be reduced here"
                          : moved
                            ? `Changed from standard, which is ${cell.default ? "allowed" : "not allowed"}`
                            : undefined}
                      >
                        {cell.allowed ? "Yes" : "No"}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
