/** The pharmacies on this deployment, and who belongs to which.
 *
 *  The only screen in the system that looks across tenants, and the only one a
 *  customer's own administrator cannot open. That distinction is the whole
 *  point: `admin` means "runs this pharmacy" and is held by a customer, so an
 *  administrator who could assign users to tenants could read another
 *  pharmacy's patients by moving themselves into it. The server refuses them
 *  with a 403; this page simply says so rather than rendering an empty table
 *  that looks broken.
 *
 *  Creating a pharmacy creates its first branch and first administrator at the
 *  same time, because a tenant with neither cannot hold stock or be signed
 *  into, and a half-made pharmacy looks finished from a list.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowClockwise, Buildings, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate } from "../api";
import BusyButton from "../components/BusyButton";
import Select from "../components/Select";
import { useToast } from "../components/Toast";
import { Refreshable, TableSkeleton } from "../components/Skeleton";

interface Pharmacy {
  id: number; name: string; trading_name: string; registration_no: string;
  phone: string; email: string; city: string; address: string;
  active: boolean; created_at: string; users: number; branches: number;
}
interface Person {
  id: number; username: string; full_name: string; role: string;
  active: boolean; is_platform_admin?: boolean;
}

const BLANK = {
  name: "", city: "", phone: "", registration_no: "",
  branch_name: "Main branch",
  admin_name: "", admin_username: "", admin_password: "",
};

export default function Pharmacies() {
  const [rows, setRows] = useState<Pharmacy[]>([]);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ ...BLANK });
  const [open, setOpen] = useState<Pharmacy | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [loose, setLoose] = useState<Person[]>([]);
  const [moving, setMoving] = useState("");
  const toast = useToast();

  const load = useCallback(() => {
    setSpinning(true);
    api.get<{ items: Pharmacy[] }>("/api/pharmacies")
      .then((d) => { setRows(d.items ?? []); setError(""); setForbidden(false); })
      .catch((e: any) => {
        if (e?.status === 403) setForbidden(true);
        else setError(errorText(e, "The pharmacies could not be loaded."));
      })
      .finally(() => {
        setLoading(false);
        window.setTimeout(() => setSpinning(false), 350);
      });
    api.get<{ items: Person[] }>("/api/pharmacies/unassigned/users")
      .then((d) => setLoose(d.items ?? []))
      .catch(() => setLoose([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  function openPharmacy(p: Pharmacy) {
    setOpen(p);
    setMoving("");
    api.get<{ items: Person[] }>(`/api/pharmacies/${p.id}/users`)
      .then((d) => setPeople(d.items ?? []))
      .catch(() => setPeople([]));
  }

  async function create() {
    try {
      const made = await api.post<Pharmacy>("/api/pharmacies", form);
      toast.ok(`${made.name} created, with its first branch and administrator.`);
      setAdding(false);
      setForm({ ...BLANK });
      load();
    } catch (e) {
      toast.error(errorText(e, "That pharmacy could not be created."));
    }
  }

  async function suspend(p: Pharmacy) {
    try {
      await api.put(`/api/pharmacies/${p.id}`, { active: !p.active });
      toast.ok(p.active
        ? `${p.name} is suspended. Their records are kept.`
        : `${p.name} is active again.`);
      load();
    } catch (e) {
      toast.error(errorText(e, "That could not be changed."));
    }
  }

  async function assign() {
    if (!open || !moving) return;
    try {
      const done = await api.post<{ username: string; pharmacy: string }>(
        `/api/pharmacies/${open.id}/users/${moving}`, {});
      toast.ok(`${done.username} now belongs to ${done.pharmacy}.`);
      setMoving("");
      openPharmacy(open);
      load();
    } catch (e) {
      toast.error(errorText(e, "That person could not be moved."));
    }
  }

  if (forbidden) {
    return (
      <>
        <div className="page-head"><h1>Pharmacies</h1></div>
        <div className="alert warn">
          <Warning size={16} weight="fill" />
          <span>
            This screen is for whoever operates RX5000, not for a pharmacy&rsquo;s
            own administrator. Being an administrator of this pharmacy does not
            include creating others or moving people between them — an account
            that could do that could read another pharmacy&rsquo;s patients.
          </span>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Pharmacies</h1>
          <div className="sub">Every business on this deployment, and who belongs to which</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={load}>
            <ArrowClockwise size={15} className={spinning ? "spin" : ""} /> Refresh
          </button>
          <button className="btn" onClick={() => setAdding(true)}>
            <Buildings size={15} /> New pharmacy
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      {/* People who belong to no pharmacy can sign in and then see nothing,
          because the scoping fails closed. Safe, but baffling for whoever it
          happens to, so it is surfaced here rather than reported as "the
          system is empty". */}
      {loose.length > 0 && (
        <div className="alert warn">
          <Warning size={16} weight="fill" />
          <span>
            <b>{loose.length} {loose.length === 1 ? "person belongs" : "people belong"} to
            no pharmacy</b> ({loose.map((p) => p.username).join(", ")}). They can sign
            in and will see nothing at all, because data is only visible to the
            pharmacy it belongs to. Open a pharmacy below to move them.
          </span>
        </div>
      )}

      <div className="card">
        <Refreshable
          loading={loading}
          hasData={rows.length > 0}
          skeleton={<TableSkeleton cols={5} rows={4}
                                   widths={["22ch", "14ch", "8ch", "10ch", "10ch"]} />}
        >
        <table className="dt">
          <thead>
            <tr>
              <th>Pharmacy</th><th>City</th><th className="num">Branches</th>
              <th className="num">People</th><th>Since</th><th>State</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className={p.active ? "" : "row-flag"}>
                <td>
                  <b>{p.name}</b>
                  <div className="muted small">
                    {p.registration_no || "no registration number"}
                    {p.phone ? ` · ${p.phone}` : ""}
                  </div>
                </td>
                <td>{p.city || <span className="muted">—</span>}</td>
                <td className="num">{p.branches}</td>
                <td className="num">{p.users}</td>
                <td className="muted">{fmtDate(p.created_at)}</td>
                <td>
                  {p.active
                    ? <span className="badge ok">active</span>
                    : <span className="badge bad">suspended</span>}
                </td>
                <td className="actions">
                  <button className="btn small secondary" onClick={() => openPharmacy(p)}>
                    People
                  </button>
                  <BusyButton className="btn small ghost" onClick={() => suspend(p)}>
                    {p.active ? "Suspend" : "Restore"}
                  </BusyButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && !loading && (
          <div className="empty">
            <b>No pharmacies yet</b>
            <p>
              Every branch, user and figure in this system belongs to one. Add
              the first to give them somewhere to live.
            </p>
          </div>
        )}
        </Refreshable>
      </div>

      {adding && (
        <div className="modal-backdrop" onClick={() => setAdding(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New pharmacy</h2>
            <p className="muted">
              This creates the business, its first branch and its first
              administrator together. A pharmacy with no branch cannot hold
              stock and one with no user cannot be signed into.
            </p>
            <label className="field">
              Pharmacy name
              <input value={form.name} autoFocus
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="e.g. Chitungwiza Chemists" />
            </label>
            <div className="form-row">
              <div className="field">
                <label>City</label>
                <input value={form.city}
                       onChange={(e) => setForm({ ...form, city: e.target.value })} />
              </div>
              <div className="field">
                <label>Phone</label>
                <input value={form.phone}
                       onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>Registration number</label>
                <input value={form.registration_no}
                       onChange={(e) => setForm({ ...form, registration_no: e.target.value })} />
              </div>
              <div className="field">
                <label>First branch</label>
                <input value={form.branch_name}
                       onChange={(e) => setForm({ ...form, branch_name: e.target.value })} />
              </div>
            </div>

            <h3>Their first administrator</h3>
            <p className="muted small">
              Sign-in names are shared across every pharmacy on this system, so
              this one has to be unique here — not only within their pharmacy.
            </p>
            <div className="form-row">
              <div className="field">
                <label>Full name</label>
                <input value={form.admin_name}
                       onChange={(e) => setForm({ ...form, admin_name: e.target.value })} />
              </div>
              <div className="field">
                <label>Username</label>
                <input value={form.admin_username}
                       onChange={(e) => setForm({ ...form, admin_username: e.target.value })} />
              </div>
            </div>
            <label className="field">
              Password
              <input type="password" value={form.admin_password}
                     onChange={(e) => setForm({ ...form, admin_password: e.target.value })}
                     placeholder="at least eight characters" />
            </label>

            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
              <BusyButton
                disabled={form.name.trim().length < 2
                          || form.admin_username.trim().length < 3
                          || form.admin_password.length < 8}
                onClick={create}
              >
                Create the pharmacy
              </BusyButton>
            </div>
          </div>
        </div>
      )}

      {open && (
        <div className="modal-backdrop" onClick={() => setOpen(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{open.name}</h2>
            <p className="muted">
              {people.length} {people.length === 1 ? "person" : "people"} belong here.
            </p>
            <table className="dt">
              <thead>
                <tr><th>Name</th><th>Username</th><th>Role</th><th>State</th></tr>
              </thead>
              <tbody>
                {people.map((u) => (
                  <tr key={u.id}>
                    <td>
                      {u.full_name || u.username}
                      {u.is_platform_admin && (
                        <div className="muted small">operates RX5000</div>
                      )}
                    </td>
                    <td className="mono">{u.username}</td>
                    <td>{u.role}</td>
                    <td>{u.active
                      ? <span className="badge ok">active</span>
                      : <span className="badge">inactive</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {people.length === 0 && (
              <div className="empty">Nobody belongs to this pharmacy yet.</div>
            )}

            {loose.length > 0 && (
              <>
                <h3>Move somebody here</h3>
                <p className="muted small">
                  Their existing work stays where it happened. The sales they
                  rang up belong to the pharmacy they were rung up in, and
                  moving those too would take one pharmacy&rsquo;s records into
                  another&rsquo;s books.
                </p>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Select
                    value={moving}
                    onChange={setMoving}
                    options={[{ value: "", label: "Choose a person…" },
                              ...loose.map((u) => ({
                                value: String(u.id),
                                label: `${u.full_name || u.username} (${u.username})`,
                              }))]}
                  />
                  <BusyButton disabled={!moving} onClick={assign}>Move them here</BusyButton>
                </div>
              </>
            )}

            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setOpen(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
