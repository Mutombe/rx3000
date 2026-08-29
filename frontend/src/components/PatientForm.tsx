/** Add a patient wherever you find out they are not on file.
 *
 *  This form lived inside the Patients page, which meant that every other
 *  place a patient is needed — the dispensary, the till, a claim — could only
 *  say "no match" and leave. The person is at the counter with a script in
 *  their hand; sending the dispenser to another screen to type a name loses
 *  the basket, the queue position and usually the thread of what they were
 *  doing. So the form is a component and the pages that need it open it in
 *  place.
 *
 *  Two things it does that a dialog lifted out of a page usually forgets:
 *
 *  **It hands the saved patient back.** The point of creating somebody
 *  mid-dispensing is to carry straight on dispensing to them, so `onSaved`
 *  receives the record and the caller selects it. A modal that closes and
 *  leaves you to search for what you just made is barely better than the
 *  navigation it replaced.
 *
 *  **It says it is saving.** Creating a patient is one round trip, and on a
 *  Zimbabwean connection one round trip is long enough to press the button
 *  twice — which is how a register acquires duplicates of the people who were
 *  in the biggest hurry.
 */
import { FormEvent, useEffect, useState } from "react";
import { api, errorText } from "../api";
import BusyButton from "./BusyButton";
import Checkbox from "./Checkbox";
import Select from "./Select";
import TermSelect from "./TermSelect";
import { MedicalAid, Patient } from "../types";
import { useToast } from "./Toast";

export const EMPTY_PATIENT = {
  first_name: "", last_name: "", id_number: "", date_of_birth: "",
  phone: "", email: "", address: "", allergies: "", chronic_conditions: "",
  medical_aid_id: "" as string | number, medical_aid_number: "", dependent_code: "00",
  caregiver_name: "", caregiver_phone: "", caregiver_relationship: "",
  contact_caregiver_first: false,
};

export type PatientDraft = typeof EMPTY_PATIENT;

/** Turn whatever was typed into the search box into a first and last name.
 *
 *  Somebody who has already typed "Tendai Moyo" looking for a patient should
 *  not have to type it again in two fields. One word is a surname, because
 *  that is how a pharmacy queue is called.
 */
export function draftFrom(query: string): PatientDraft {
  const words = (query || "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return { ...EMPTY_PATIENT };
  if (words.length === 1) return { ...EMPTY_PATIENT, last_name: words[0] };
  return {
    ...EMPTY_PATIENT,
    first_name: words[0],
    last_name: words.slice(1).join(" "),
  };
}

export default function PatientForm({
  open, initial, editing, onClose, onSaved, title,
}: {
  open: boolean;
  /** Prefill — usually what somebody had already typed into a search box. */
  initial?: Partial<PatientDraft>;
  /** The record being changed, where this is an edit rather than a creation. */
  editing?: Patient | null;
  onClose: () => void;
  /** The saved patient, so the caller can carry on with them. */
  onSaved: (patient: Patient) => void;
  title?: string;
}) {
  const [form, setForm] = useState<PatientDraft>({ ...EMPTY_PATIENT });
  const [aids, setAids] = useState<MedicalAid[]>([]);
  const toast = useToast();

  // Reset every time it opens. A dialog that keeps the last person's details
  // is how a nurse's telephone number ends up on a stranger's record.
  useEffect(() => {
    if (!open) return;
    setForm({ ...EMPTY_PATIENT, ...(initial ?? {}) });
  }, [open, JSON.stringify(initial ?? {})]);

  useEffect(() => {
    if (!open) return;
    api.get<MedicalAid[]>("/api/medical-aids").then(setAids).catch(() => setAids([]));
  }, [open]);

  if (!open) return null;

  async function save(e?: FormEvent) {
    e?.preventDefault();
    const body = {
      ...form,
      date_of_birth: form.date_of_birth || null,
      medical_aid_id: form.medical_aid_id === "" ? null : Number(form.medical_aid_id),
    };
    try {
      const saved = editing
        ? await api.put<Patient>(`/api/patients/${editing.id}`, body)
        : await api.post<Patient>("/api/patients", body);
      toast.ok(editing
        ? `${form.first_name} ${form.last_name} updated.`
        : `${form.first_name} ${form.last_name} added.`);
      onSaved(saved);
      onClose();
    } catch (err) {
      // Left open with what was typed still in it. Closing on a failure means
      // retyping a whole record because a member number was too long.
      toast.error(errorText(err, "That patient could not be saved."));
    }
  }

  const set = (k: keyof PatientDraft) => (e: any) =>
    setForm({ ...form, [k]: e.target.value });
  const ready = form.first_name.trim() !== "" && form.last_name.trim() !== "";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal modal-wide" onClick={(e) => e.stopPropagation()}
            onSubmit={save}>
        <h2>{title ?? (editing ? "Edit patient" : "New patient")}</h2>

        <div className="form-row">
          <div className="field span-6"><label>First name</label>
            <input required autoFocus value={form.first_name} onChange={set("first_name")} /></div>
          <div className="field span-6"><label>Last name</label>
            <input required value={form.last_name} onChange={set("last_name")} /></div>
        </div>
        <div className="form-row">
          <div className="field span-6"><label>ID number</label>
            <input value={form.id_number} onChange={set("id_number")} /></div>
          <div className="field span-6"><label>Date of birth</label>
            <input type="date" value={form.date_of_birth} onChange={set("date_of_birth")} /></div>
        </div>
        <div className="form-row">
          <div className="field span-6"><label>Phone</label>
            <input value={form.phone} onChange={set("phone")} placeholder="07…" /></div>
          <div className="field span-6"><label>Email</label>
            <input type="email" value={form.email} onChange={set("email")} /></div>
        </div>
        <div className="field"><label>Address</label>
          <input value={form.address} onChange={set("address")} /></div>

        <div className="form-row">
          {/* Picked, not typed. The dispensing check reads this field and
              matches it against product names and ingredients, so a misspelt
              allergy is a blocking warning that never fires. */}
          <div className="field span-6">
            <label>Allergies</label>
            <TermSelect kind="allergy" value={form.allergies}
              onChange={(v) => setForm((f) => ({ ...f, allergies: v }))}
              placeholder="Search allergies, or add a new one" />
          </div>
          <div className="field span-6">
            <label>Chronic conditions</label>
            <TermSelect kind="condition" value={form.chronic_conditions}
              onChange={(v) => setForm((f) => ({ ...f, chronic_conditions: v }))}
              placeholder="Search conditions, or add a new one" />
          </div>
        </div>

        <div className="form-row">
          <div className="field span-6">
            <label>Medical aid</label>
            <Select
              value={String(form.medical_aid_id ?? "")}
              onChange={(v) => setForm((f) => ({ ...f, medical_aid_id: v }))}
              options={[{ value: "", label: "Private (none)" },
                        ...aids.map((a) => ({ value: String(a.id), label: a.name }))]}
            />
          </div>
          <div className="field span-4"><label>Member number</label>
            <input value={form.medical_aid_number} onChange={set("medical_aid_number")} /></div>
          <div className="field span-2"><label>Dep.</label>
            <input value={form.dependent_code} onChange={set("dependent_code")} /></div>
        </div>

        <h4 className="form-section">Caregiver</h4>
        <p className="muted small">
          Left blank for a patient who manages their own medicine. Filled in,
          this is who gets the reminder, signs for a delivery and takes the
          follow-up call.
        </p>
        <div className="form-row">
          <div className="field span-4"><label>Name</label>
            <input value={form.caregiver_name} onChange={set("caregiver_name")} /></div>
          <div className="field span-4"><label>Phone</label>
            <input value={form.caregiver_phone} onChange={set("caregiver_phone")} placeholder="+263…" /></div>
          <div className="field span-4"><label>Relationship</label>
            <input value={form.caregiver_relationship} onChange={set("caregiver_relationship")} placeholder="e.g. daughter" /></div>
        </div>
        <div className="check-row">
          <Checkbox
            checked={form.contact_caregiver_first}
            onChange={(v) => setForm({ ...form, contact_caregiver_first: v })}
            disabled={!form.caregiver_phone.trim()}
          >
            Contact the caregiver first
            {/* Meaningless without a number to ring, so it cannot be ticked
                until there is one. */}
            {!form.caregiver_phone.trim() && (
              <span className="muted">, needs a caregiver phone number</span>
            )}
          </Checkbox>
        </div>

        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton type="submit" className="btn primary" disabled={!ready}
                      busyLabel={editing ? "Saving…" : "Adding…"}
                      onClick={() => save()}>
            {editing ? "Save patient" : "Add patient"}
          </BusyButton>
        </div>
      </form>
    </div>
  );
}
