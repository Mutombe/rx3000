/** Add a patient wherever you find out they are not on file.
 *
 *  This form lived inside the Patients page, which meant that every other
 *  place a patient is needed, the dispensary, the till, a claim, could only
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
 *  twice, which is how a register acquires duplicates of the people who were
 *  in the biggest hurry.
 */
import { FormEvent, useEffect, useRef, useState } from "react";
import { api, errorText, fmtDate } from "../api";
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

/** Somebody on file who may be the person being registered, and why. */
interface DuplicateMatch {
  id: number;
  profile_number: string | null;
  first_name: string;
  last_name: string;
  id_number: string;
  date_of_birth: string | null;
  phone: string;
  reasons: string[];
  strength: "strong" | "likely";
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
  /** Who on file may already be this person — null until asked.
   *
   *  Registration used to save without looking, and with fourteen thousand
   *  patients a second record is not hypothetical: a surname typed with a
   *  trailing space, an ID without its hyphens. A second record splits one
   *  person's allergies, repeat counts and claims across two, and nobody sees
   *  the whole of either. (CareXpress To-Be blueprint §6, §7.) */
  const [matches, setMatches] = useState<DuplicateMatch[] | null>(null);
  const reviewRef = useRef<HTMLElement>(null);
  // Brought into view when it appears. Somebody who scrolled down to fill in
  // the caregiver has the top of the form out of sight, and a review they
  // cannot see is the same as no review — the button just changes its words.
  useEffect(() => {
    if (matches && matches.length) {
      reviewRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [matches]);

  // Reset every time it opens. A dialog that keeps the last person's details
  // is how a nurse's telephone number ends up on a stranger's record.
  useEffect(() => {
    if (!open) return;
    setMatches(null);
    setForm({ ...EMPTY_PATIENT, ...(initial ?? {}) });
  }, [open, JSON.stringify(initial ?? {})]);

  useEffect(() => {
    if (!open) return;
    api.get<MedicalAid[]>("/api/medical-aids").then(setAids).catch(() => setAids([]));
  }, [open]);

  if (!open) return null;

  function bodyOf() {
    return {
      ...form,
      date_of_birth: form.date_of_birth || null,
      medical_aid_id: form.medical_aid_id === "" ? null : Number(form.medical_aid_id),
    };
  }

  async function register(confirmedDistinct: boolean) {
    const saved = await api.post<Patient>("/api/patients", {
      ...bodyOf(),
      confirmed_distinct: confirmedDistinct,
      possible_duplicate_of_id: confirmedDistinct ? (matches?.[0]?.id ?? null) : null,
    });
    toast.ok(`${form.first_name} ${form.last_name} added`
      + (saved.profile_number ? ` as ${saved.profile_number}.` : "."));
    onSaved(saved);
    onClose();
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    try {
      if (editing) {
        const saved = await api.put<Patient>(`/api/patients/${editing.id}`, bodyOf());
        toast.ok(`${form.first_name} ${form.last_name} updated.`);
        onSaved(saved);
        onClose();
        return;
      }
      // Look before registering. The server refuses a match that has not been
      // reviewed, but it can only say so in a sentence; the list of who matched
      // and why has to be asked for, so that it can be shown.
      if (matches === null) {
        const found = await api.post<DuplicateMatch[]>("/api/patients/duplicates", bodyOf());
        if (found.length) { setMatches(found); return; }
      } else if (matches.length) {
        return;                       // the choice is waiting in the panel
      }
      await register(false);
    } catch (err) {
      // Left open with what was typed still in it. Closing on a failure means
      // retyping a whole record because a member number was too long.
      toast.error(errorText(err, "That patient could not be saved."));
    }
  }

  /** It is them: carry on with the record that already exists. */
  async function useExisting(id: number) {
    try {
      const existing = await api.get<Patient>(`/api/patients/${id}`);
      toast.ok(`Using ${existing.first_name} ${existing.last_name}, already on file.`);
      onSaved(existing);
      onClose();
    } catch (err) {
      toast.error(errorText(err, "That record could not be opened."));
    }
  }

  /** It is not them: register, and keep the match for a merge review. */
  async function registerAnyway() {
    try {
      await register(true);
    } catch (err) {
      toast.error(errorText(err, "That patient could not be saved."));
    }
  }

  // Changing what was typed changes who it might match, so the last answer
  // stops applying and the next save asks again.
  const set = (k: keyof PatientDraft) => (e: any) => {
    setForm({ ...form, [k]: e.target.value });
    setMatches(null);
  };
  const ready = form.first_name.trim() !== "" && form.last_name.trim() !== "";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal modal-wide" onClick={(e) => e.stopPropagation()}
            onSubmit={save}>
        <h2>{title ?? (editing ? "Edit patient" : "New patient")}</h2>

        {/* Who may already be this person — at the top, where the eye already
            is. It sat above the buttons at first, which on this form is below
            the caregiver section: the panel was on the page and out of sight,
            and all a dispenser saw was the button changing to "They're a
            different person" with no reason visible. */}
        {matches && matches.length > 0 && (
          <section className="dup-review" aria-live="polite" ref={reviewRef}>
            <h3>
              {matches.length === 1
                ? "This may be someone already on file"
                : `These ${matches.length} may already be on file`}
            </h3>
            <p className="muted">
              A second record splits one person's allergies, repeats and claims.
              If it's them, use their record.
            </p>
            <ul className="dup-list">
              {matches.map((m) => (
                <li key={m.id} className={`dup-item is-${m.strength}`}>
                  <div className="dup-who">
                    <div>
                      <b>{m.first_name} {m.last_name}</b>
                      {m.profile_number && <span className="mono muted"> {m.profile_number}</span>}
                    </div>
                    <div className="muted dup-facts">
                      {[m.id_number && `ID ${m.id_number}`,
                        m.date_of_birth && `Born ${fmtDate(m.date_of_birth)}`,
                        m.phone].filter(Boolean).join(" · ")}
                    </div>
                    <div className="dup-reasons">
                      {m.reasons.map((r) => (
                        <span key={r} className={`badge ${m.strength === "strong" ? "danger" : "warn"}`}>{r}</span>
                      ))}
                    </div>
                  </div>
                  <button type="button" className="btn secondary" onClick={() => useExisting(m.id)}>
                    Use this patient
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}


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
          {matches && matches.length > 0 ? (
            // Registering past a match is allowed — namesakes exist — but it is
            // a stated choice, not the same button pressed a second time.
            <BusyButton type="button" className="btn primary" disabled={!ready}
                        busyLabel="Adding…" onClick={registerAnyway}>
              They're a different person — add them
            </BusyButton>
          ) : (
            <BusyButton type="submit" className="btn primary" disabled={!ready}
                        busyLabel={editing ? "Saving…" : "Checking…"}
                        onClick={() => save()}>
              {editing ? "Save patient" : "Add patient"}
            </BusyButton>
          )}
        </div>
      </form>
    </div>
  );
}
