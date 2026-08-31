/** Adding or editing a driver.
 *
 *  Two fields are compulsory and both are refused by the server as well as
 *  here: a name, because somebody has to be findable when a delivery goes
 *  missing, and a phone number, because half of what this record is for is
 *  ringing them.
 *
 *  The COD limit is the one field worth explaining rather than labelling. A
 *  round carrying eight hundred dollars is a different risk from one carrying
 *  forty, and the point of setting the line in advance is that it gets set
 *  calmly rather than during an argument about a missing round.
 */
import { useState } from "react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import Select from "./Select";
import { useToast } from "./Toast";
import type { Driver } from "../pages/Drivers";

const VEHICLES = [
  { value: "motorbike", label: "Motorbike" },
  { value: "car", label: "Car" },
  { value: "van", label: "Van" },
  { value: "bicycle", label: "Bicycle" },
  { value: "on_foot", label: "On foot" },
];

export default function DriverForm(
  { driver, onClose, onSaved }:
  { driver?: Driver; onClose: () => void; onSaved: (d: Driver) => void },
) {
  const [form, setForm] = useState({
    full_name: driver?.full_name ?? "",
    phone: driver?.phone ?? "",
    alternate_phone: driver?.alternate_phone ?? "",
    national_id: driver?.national_id ?? "",
    code: driver?.code ?? "",
    vehicle_type: driver?.vehicle_type ?? "motorbike",
    vehicle_registration: driver?.vehicle_registration ?? "",
    licence_number: driver?.licence_number ?? "",
    licence_expiry: driver?.licence_expiry ?? "",
    cash_float: String(driver?.cash_float ?? ""),
    cod_limit: String(driver?.cod_limit ?? ""),
    notes: driver?.notes ?? "",
  });
  const toast = useToast();

  const set = (k: keyof typeof form) => (v: string) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    try {
      const body = {
        ...form,
        cash_float: Number(form.cash_float) || 0,
        cod_limit: Number(form.cod_limit) || 0,
        licence_expiry: form.licence_expiry || null,
      };
      const saved = driver
        ? await api.put<Driver>(`/api/drivers/${driver.id}`, body)
        : await api.post<Driver>("/api/drivers", body);
      toast.ok(`${saved.full_name} saved.`);
      onSaved(saved);
    } catch (e) {
      toast.error(errorText(e, "That driver could not be saved."));
    }
  }

  const ready = form.full_name.trim() && form.phone.trim();

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <h2>{driver ? `Edit ${driver.full_name}` : "New driver"}</h2>
        <p className="muted">
          A driver does not need a login. Most do not have one — the runner on
          the motorbike never touches the dispensing system.
        </p>

        <div className="form-row">
          <div className="field span-6">
            <label>Full name</label>
            <input value={form.full_name} autoFocus maxLength={120}
              onChange={(e) => set("full_name")(e.target.value)} />
          </div>
          <div className="field span-6">
            <label>Phone</label>
            <input value={form.phone} maxLength={30}
              onChange={(e) => set("phone")(e.target.value)}
              placeholder="0779 000 000" />
          </div>
          <div className="field span-6">
            <label>Other number <span className="muted">optional</span></label>
            <input value={form.alternate_phone} maxLength={30}
              onChange={(e) => set("alternate_phone")(e.target.value)} />
          </div>
          <div className="field span-6">
            <label>National ID <span className="muted">optional</span></label>
            <input value={form.national_id} maxLength={30}
              onChange={(e) => set("national_id")(e.target.value)} />
          </div>

          <div className="field span-4">
            <label>Vehicle</label>
            <Select value={form.vehicle_type} onChange={set("vehicle_type")}
              options={VEHICLES} />
          </div>
          <div className="field span-4">
            <label>Registration</label>
            <input value={form.vehicle_registration} maxLength={20}
              onChange={(e) => set("vehicle_registration")(e.target.value)}
              placeholder="AEB 4471" />
          </div>
          <div className="field span-4">
            <label>Licence number</label>
            <input value={form.licence_number} maxLength={40}
              onChange={(e) => set("licence_number")(e.target.value)} />
          </div>
          <div className="field span-4">
            <label>Licence expires</label>
            <input type="date" value={form.licence_expiry ?? ""}
              onChange={(e) => set("licence_expiry")(e.target.value)} />
            <span className="hint">
              A delivery cannot be dispatched to a driver whose licence has
              expired — the refusal happens at dispatch, when it still matters.
            </span>
          </div>

          <div className="field span-6">
            <label>Cash float</label>
            <input type="number" step="0.01" value={form.cash_float}
              onChange={(e) => set("cash_float")(e.target.value)}
              placeholder="0.00" />
            <span className="hint">What they carry to make change with.</span>
          </div>
          <div className="field span-6">
            <label>Cash-on-delivery limit</label>
            <input type="number" step="0.01" value={form.cod_limit}
              onChange={(e) => set("cod_limit")(e.target.value)}
              placeholder="0.00" />
            <span className="hint">
              Above this in uncollected cash they should be back at the shop.
              Leave at zero for no limit.
            </span>
          </div>

          <div className="field span-12">
            <label>Notes <span className="muted">optional</span></label>
            <input value={form.notes} maxLength={400}
              onChange={(e) => set("notes")(e.target.value)}
              placeholder="Works Saturdays only, knows the northern suburbs" />
          </div>
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={save} disabled={!ready}
            busyLabel="Saving…">
            {driver ? "Save changes" : "Add driver"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
