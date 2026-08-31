/** A member of staff, as a record of work rather than a permissions screen.
 *
 *  Who dispensed what, and which tills they cashed up. The account settings
 *  live in the control panel; repeating them here would mean two places to keep
 *  right, and this page answers a different question — "what has this person
 *  actually done", which is what you want when a query lands on a dispensing
 *  from three weeks ago.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import BusyButton from "../components/BusyButton";
import { useAsk, useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";
import { useParams } from "react-router-dom";

interface Dispensed {
  id: number; dispensed_at: string; quantity: number; schedule: number;
  product_id: number | null; product: string;
  prescription_id: number | null; rx_number: string;
  patient: { id: number | null; name: string };
}
interface ShiftRow {
  id: number; opened_at: string; closed_at: string | null;
  status: string; variance: number;
}
interface Data {
  id: number; username: string; full_name: string; role: string;
  active: boolean; is_demo: boolean;
  dispensed_count: number; shift_count: number;
  dispensings: Dispensed[]; shifts: ShiftRow[];
}

export default function StaffDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.get<Data>(`/api/users/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That member of staff could not be opened.")));
  }, [id]);
  useEffect(load, [load]);

  const toast = useToast();
  const ask = useAsk();
  const confirm = useConfirm();
  /** A staff member who leaves must stop being able to sign in.
   *
   *  The endpoint was built and no screen called it, so the most ordinary
   *  security failure a small business has — the departed employee whose login
   *  still works — had no cure in the application.
   */
  async function deactivate() {
    if (!d) return;
    const ok = await confirm({
      title: `Stop ${d.full_name} signing in?`,
      body: (
        <>
          <p>
            Their name stays on the {d.dispensed_count} dispensing(s) they
            checked and the {d.shift_count} till(s) they cashed up — those are
            the record of who did them.
          </p>
          <p className="muted">
            They are retired, never deleted. Deleting the row would not remove
            the work; it would remove the ability to say who did it.
          </p>
        </>
      ),
      confirmLabel: "Stop the login",
      destructive: true,
    });
    if (!ok) return;
    try {
      const r = await api.delete<{ message: string }>(`/api/auth/users/${d.id}`);
      toast.ok(r.message);
      load();
    } catch (e) {
      // The server refuses the last administrator and the signed-in account,
      // and says which. Shown as written.
      toast.error(errorText(e));
    }
  }

  async function changeRole() {
    if (!d) return;
    const answer = await ask({
      title: `What is ${d.full_name}'s role?`,
      body: "admin, pharmacist, manager, assistant or cashier. A role typed "
          + "wrong used to be permanent, so a qualified pharmacist set up as "
          + "an assistant needed a second account — and then two logins "
          + "belonged to one person and the register could not say which of "
          + "them checked a controlled item.",
      field: "Role",
      placeholder: d.role,
      required: true,
      maxLength: 20,
      confirmLabel: "Change it",
    });
    if (!answer.ok) return;
    try {
      await api.put(`/api/auth/users/${d.id}`, { role: answer.value.toLowerCase() });
      toast.ok(`${d.full_name} is now a ${answer.value.toLowerCase()}.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  async function reactivate() {
    if (!d) return;
    try {
      await api.put(`/api/auth/users/${d.id}`, { active: true });
      toast.ok(`${d.full_name} can sign in again.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    }
  }
  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Control Panel", to: "/admin" },
              { label: d?.full_name ?? "This person" }]}
      eyebrow="Staff"
      title={d?.full_name ?? ""}
      subtitle={d && `${d.role}${d.active ? "" : " · no longer active"}`}
      loading={!d && !error}
      error={error}
      actions={d && !d.is_demo && (
        <div className="page-actions">
          <BusyButton className="btn" onClick={changeRole} busyLabel="Saving…">
            Change role
          </BusyButton>
          {d.active ? (
            <BusyButton className="btn danger" onClick={deactivate}
                        busyLabel="Stopping…">
              Stop the login
            </BusyButton>
          ) : (
            <BusyButton className="btn primary" onClick={reactivate}
                        busyLabel="Restoring…">
              Let them sign in again
            </BusyButton>
          )}
        </div>
      )}
      facts={d ? [
        { label: "Dispensings", value: d.dispensed_count },
        { label: "Till sessions", value: d.shift_count },
        { label: "Username", value: <span className="mono">{d.username}</span> },
        { label: "Role", value: d.role },
      ] : undefined}
    >
      {d && (
        <>
          <Panel title="Recently dispensed" count={d.dispensings.length}
                 empty="This person has not dispensed anything.">
            <div className="dt-scroll" style={{ maxHeight: "46vh" }}>
              <table className="dt">
                <thead>
                  <tr>
                    <th>When</th><th>Medicine</th><th>Patient</th>
                    <th>Script</th><th className="num">Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {d.dispensings.map((r) => (
                    <tr key={r.id}>
                      <td>{fmtDateTime(r.dispensed_at)}</td>
                      <td>
                        <EntityLink kind="product" id={r.product_id}>
                          {r.product || "—"}
                        </EntityLink>
                        {r.schedule >= 5 && <span className="badge sched">S{r.schedule}</span>}
                      </td>
                      <td>
                        <EntityLink kind="patient" id={r.patient.id}>
                          {r.patient.name}
                        </EntityLink>
                      </td>
                      <td className="mono">
                        <EntityLink kind="prescription" id={r.prescription_id}>
                          {r.rx_number || "—"}
                        </EntityLink>
                      </td>
                      <td className="num">{r.quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Till sessions" count={d.shifts.length}
                 empty="This person has not run a till.">
            <table className="dt">
              <thead>
                <tr><th>Opened</th><th>Closed</th><th>Status</th><th className="num">Variance</th></tr>
              </thead>
              <tbody>
                {d.shifts.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <EntityLink kind="shift" id={s.id}>{fmtDateTime(s.opened_at)}</EntityLink>
                    </td>
                    <td>{s.closed_at ? fmtDateTime(s.closed_at)
                      : <span className="muted">still open</span>}</td>
                    <td><span className="badge">{s.status}</span></td>
                    <td className="num">
                      {Math.abs(s.variance) < 0.005
                        ? <span className="muted">balanced</span>
                        : money(s.variance)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
