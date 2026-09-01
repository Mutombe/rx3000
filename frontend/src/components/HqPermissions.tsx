/** Granting one person one bounded authority.
 *
 *  "May void a sale" is not how anybody in a pharmacy delegates. It is "may
 *  void a sale under twenty dollars, at Avondale, until the locum leaves, and
 *  anything larger needs me", and a system that can only say yes or no forces
 *  every one of those into a yes.
 *
 *  What follows from that is not stricter practice. It is that somebody hands
 *  out an administrator's login because it is the only thing that works, and
 *  from then on the audit trail says "admin" for everything and the controlled
 *  register cannot say who checked what. **A permission model that is too
 *  coarse does not make a pharmacy tighter; it makes its records false.**
 *
 *  So every grant carries its bounds on the same row: the capability, where,
 *  how much, how much in a day, whether a second signature is needed, which
 *  hours and days, and when it dies.
 */
import { useCallback, useEffect, useState } from "react";
import { Info } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money } from "../api";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";
import Select from "./Select";
import { TableSkeleton } from "./Skeleton";
import { useConfirm } from "./Confirm";
import { useToast } from "./Toast";

interface Capability { capability: string; name: string; roles: string[] }
interface Grant {
  id: number; capability: string; allow: boolean;
  branch_id: number | null; branch: string;
  limit_value: number; daily_limit: number;
  escalates: boolean; dual_approval: boolean;
  hours: string; days: string; reason: string;
  expires_on: string | null; granted_by: string;
}
interface Standing {
  capability: string; name: string; allowed: boolean; why: string;
  role_grants_it: boolean; granted_by_name: boolean; denied_by_name: boolean;
}
interface Detail {
  user: { id: number; full_name: string; role: string; active: boolean };
  capabilities: Standing[]; grants: Grant[];
}
interface Person { id: number; full_name: string; role: string }
interface Branch { id: number; name: string }

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

export default function HqPermissions() {
  const [people, setPeople] = useState<Person[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [caps, setCaps] = useState<Capability[]>([]);
  const [who, setWho] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [adding, setAdding] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  useEffect(() => {
    Promise.all([
      api.get<Person[]>("/api/auth/users"),
      api.get<Branch[]>("/api/branches"),
      api.get<Capability[]>("/api/hq/capabilities"),
    ])
      .then(([p, b, c]) => {
        setPeople(p); setBranches(b); setCaps(c);
        if (p.length) setWho(p[0].id);
      })
      .catch((e) => toast.error(errorText(e)));
  }, []);

  const load = useCallback(() => {
    if (!who) return;
    setDetail(null);
    api.get<Detail>(`/api/hq/users/${who}/permissions`)
      .then(setDetail)
      .catch((e) => toast.error(errorText(e)));
  }, [who]);
  useEffect(load, [load]);

  async function revoke(g: Grant) {
    const ok = await confirm({
      title: `Withdraw ${g.capability}?`,
      body: "The record of it stays — it was true while it stood, and an audit "
          + "asks about periods rather than about today.",
      confirmLabel: "Withdraw it",
      destructive: true,
    });
    if (!ok) return;
    try {
      const r = await api.delete<{ message: string }>(
        `/api/hq/permissions/${g.id}`);
      toast.ok(r.message);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  return (
    <>
      <div className="form-row">
        <div className="field span-6">
          <label>Whose authority</label>
          <Select value={String(who ?? "")} onChange={(v) => setWho(Number(v))}
            options={people.map((p) => ({
              value: String(p.id), label: `${p.full_name} — ${p.role}` }))} />
        </div>
        <div className="field span-6" style={{ alignSelf: "end" }}>
          <button className="btn primary" onClick={() => setAdding(true)}
                  disabled={!who}>
            Grant something
          </button>
        </div>
      </div>

      {!detail ? <TableSkeleton cols={4} rows={6} /> : (
        <>
          {detail.grants.length > 0 && (
            <>
              <h4 className="cu-section">Granted by name</h4>
              <div className="dt-scroll">
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Capability</th><th>Where</th>
                      <th className="num">Ceiling</th>
                      <th>When</th><th>Until</th><th>Why</th>
                      <th className="actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {detail.grants.map((g) => (
                      <tr key={g.id}
                          className={g.allow ? undefined : "row-danger"}>
                        <td>
                          <b>{g.capability}</b>
                          {!g.allow && (
                            <div><span className="badge bad">
                              prevented — beats any grant
                            </span></div>
                          )}
                          {g.dual_approval && (
                            <div><span className="badge warn">
                              never alone
                            </span></div>
                          )}
                        </td>
                        <td>{g.branch || <span className="muted">anywhere</span>}</td>
                        <td className="num mono">
                          {g.limit_value ? money(g.limit_value)
                            : <span className="muted">—</span>}
                          {g.daily_limit > 0 && (
                            <div className="muted small">
                              {money(g.daily_limit)}/day
                            </div>
                          )}
                          {g.limit_value > 0 && !g.escalates && (
                            <div className="muted small">cannot be approved up</div>
                          )}
                        </td>
                        <td className="small">
                          {g.days || g.hours
                            ? <>{g.days}{g.days && g.hours && " · "}{g.hours}</>
                            : <span className="muted">any time</span>}
                        </td>
                        <td>
                          {g.expires_on ? fmtDate(g.expires_on)
                            : <span className="muted">standing</span>}
                        </td>
                        <td className="wrap muted small">
                          {g.reason}
                          {g.granted_by && (
                            <div>by {g.granted_by}</div>
                          )}
                        </td>
                        <td className="actions">
                          <button className="btn ghost sm"
                                  onClick={() => revoke(g)}>Withdraw</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h4 className="cu-section">
            Everything {detail.user.full_name} may and may not do
          </h4>
          <p className="muted small">
            <Info size={13} /> A permission check that can only say no is one
            nobody can administer. The question asked at a counter is never
            "am I allowed" — it is "who do I ask, and why not".
          </p>
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr><th>Can they</th><th>Answer</th><th>Why</th></tr>
              </thead>
              <tbody>
                {detail.capabilities.map((c) => (
                  <tr key={c.capability}>
                    <td>
                      <b>{c.name}</b>
                      <div className="muted small mono">{c.capability}</div>
                    </td>
                    <td>
                      <span className={`badge ${c.allowed ? "ok" : "muted"}`}>
                        {c.allowed ? "yes" : "no"}
                      </span>
                      {c.denied_by_name && (
                        <div><span className="badge bad">by name</span></div>
                      )}
                      {c.granted_by_name && !c.role_grants_it && (
                        <div><span className="badge warn">by name</span></div>
                      )}
                    </td>
                    <td className="wrap muted small">{c.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {adding && who && (
        <GrantForm userId={who} caps={caps} branches={branches}
          onClose={() => setAdding(false)}
          onSaved={() => { setAdding(false); load(); }} />
      )}
    </>
  );
}

function GrantForm({ userId, caps, branches, onClose, onSaved }: {
  userId: number; caps: Capability[]; branches: Branch[];
  onClose: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState({
    capability: caps[0]?.capability ?? "", allow: true,
    branch_id: "", limit_value: "", daily_limit: "",
    escalates: true, dual_approval: false,
    hours: "", days: "", reason: "", expires_on: "",
  });
  const [days, setDays] = useState<boolean[]>(Array(7).fill(true));
  const toast = useToast();
  const chosen = caps.find((c) => c.capability === f.capability);

  async function save() {
    try {
      const r = await api.post<{ message: string }>(
        `/api/hq/users/${userId}/permissions`, {
          ...f,
          branch_id: f.branch_id ? Number(f.branch_id) : null,
          limit_value: Number(f.limit_value) || 0,
          daily_limit: Number(f.daily_limit) || 0,
          // "MTWTFSS" with a dash for a day off, which is what the server
          // reads. Every day on is sent as blank — a grant with no day
          // restriction should not carry one.
          days: days.every(Boolean) ? ""
            : days.map((on, i) => (on ? DAYS[i] : "-")).join(""),
          expires_on: f.expires_on || null,
        });
      toast.ok(r.message);
      onSaved();
    } catch (e) {
      toast.error(errorText(e, "That could not be granted."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <h2>{f.allow ? "Grant an authority" : "Prevent something"}</h2>
        {chosen && (
          <p className="muted">
            {chosen.name}. Held already by: {chosen.roles.join(", ")}.
          </p>
        )}

        <div className="form-row">
          <div className="field span-8">
            <label>What</label>
            <Select value={f.capability}
              onChange={(v) => setF((x) => ({ ...x, capability: v }))}
              options={caps.map((c) => ({
                value: c.capability, label: `${c.name} (${c.capability})` }))} />
          </div>
          <div className="field span-4">
            <label>Direction</label>
            <Select value={f.allow ? "allow" : "deny"}
              onChange={(v) => setF((x) => ({ ...x, allow: v === "allow" }))}
              options={[
                { value: "allow", label: "Allow them to" },
                { value: "deny", label: "Prevent them from" },
              ]} />
            <span className="hint">
              A denial beats every grant, including the one their role gives —
              or nobody could rely on a denial meaning anything.
            </span>
          </div>

          <div className="field span-6">
            <label>Where</label>
            <Select value={f.branch_id}
              onChange={(v) => setF((x) => ({ ...x, branch_id: v }))}
              options={[{ value: "", label: "Every branch" },
                        ...branches.map((b) => ({
                          value: String(b.id), label: b.name }))]} />
            <span className="hint">
              A manager who may authorise a write-off at Avondale should not
              thereby authorise one in Bulawayo.
            </span>
          </div>
          <div className="field span-3">
            <label>Ceiling <span className="muted">optional</span></label>
            <input type="number" step="0.01" value={f.limit_value}
              disabled={!f.allow}
              onChange={(e) => setF((x) => ({ ...x, limit_value: e.target.value }))}
              placeholder="0.00" />
            <span className="hint">Nought means no ceiling.</span>
          </div>
          <div className="field span-3">
            <label>In a day <span className="muted">optional</span></label>
            <input type="number" step="0.01" value={f.daily_limit}
              disabled={!f.allow}
              onChange={(e) => setF((x) => ({ ...x, daily_limit: e.target.value }))}
              placeholder="0.00" />
            <span className="hint">
              Four small voids in an afternoon is a pattern a per-act ceiling
              cannot see.
            </span>
          </div>

          <div className="field span-6">
            <label>Hours <span className="muted">optional</span></label>
            <input value={f.hours} disabled={!f.allow} maxLength={20}
              onChange={(e) => setF((x) => ({ ...x, hours: e.target.value }))}
              placeholder="08:00-17:00" />
            <span className="hint">
              An authority that only exists during a shift cannot be used with
              somebody's card after they have gone home.
            </span>
          </div>
          <div className="field span-6">
            <label>Days</label>
            <div className="bulk-actions">
              {DAYS.map((d, i) => (
                <button key={i} type="button" disabled={!f.allow}
                  className={`btn sm ${days[i] ? "primary" : "ghost"}`}
                  onClick={() => setDays((cur) =>
                    cur.map((on, n) => (n === i ? !on : on)))}>
                  {d}
                </button>
              ))}
            </div>
          </div>

          <div className="field span-12">
            <Checkbox checked={f.dual_approval} onChange={(v) =>
              setF((x) => ({ ...x, dual_approval: v }))}>
              Never alone — a second named person every time, whatever the
              amount.
            </Checkbox>
            <Checkbox checked={f.escalates} onChange={(v) =>
              setF((x) => ({ ...x, escalates: v }))}>
              Over the ceiling, somebody senior may approve it.{" "}
              <span className="muted">
                Off means it cannot be approved up at all — a refusal that
                cannot be escalated is one people work around.
              </span>
            </Checkbox>
          </div>

          <div className="field span-6">
            <label>Until <span className="muted">optional</span></label>
            <input type="date" value={f.expires_on}
              onChange={(e) => setF((x) => ({ ...x, expires_on: e.target.value }))} />
            <span className="hint">A locum's authority should die with the locum.</span>
          </div>
          <div className="field span-6">
            <label>Why</label>
            <input value={f.reason} maxLength={300}
              onChange={(e) => setF((x) => ({ ...x, reason: e.target.value }))}
              placeholder="Covers the till on Saturdays" />
            <span className="hint">
              These are reviewed exactly when something has gone wrong.
            </span>
          </div>
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className={`btn ${f.allow ? "primary" : "danger"}`}
            onClick={save} disabled={!f.capability || !f.reason.trim()}
            busyLabel="Saving…">
            {f.allow ? "Grant it" : "Prevent it"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
