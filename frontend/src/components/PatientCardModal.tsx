/** Who this patient is, at a glance, without leaving the dispensary.
 *
 *  Two balanced columns: on the left who they are and how to reach them; on
 *  the right what the counter has to act on — their cover, what they are
 *  allergic to, what they live with, and who to speak to when it is not them.
 *
 *  DOUBLE-CLICK A VALUE AND TYPE OVER IT.
 *
 *  A phone number or a member number is learned at the counter, mid-script,
 *  and asked for by the person standing there. Opening a form to change one
 *  field is more ceremony than the fact deserves, so the facts are the fields:
 *  double-click, type, Enter. The same gesture the script table already uses
 *  for a quantity or an amount, for the same reason.
 *
 *  Not everything. A scheme is a list, allergies are a vocabulary, and a
 *  birthday is a date — those open the full form, which knows how to ask. The
 *  rule is that a value a person would simply TYPE is typed here, and anything
 *  needing a control to choose from is not pretended otherwise.
 *
 *  Two are never editable and say so by not offering: the profile number is
 *  issued by the register and the loyalty points are earned.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowSquareOut, PencilSimpleLine, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate } from "../api";
import { draftOf, payloadOf } from "./PatientForm";
import { useToast } from "./Toast";
import type { Patient } from "../types";

function ageFrom(dob: string | null): number | null {
  if (!dob) return null;
  const born = new Date(dob);
  if (Number.isNaN(born.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - born.getFullYear();
  const before = now.getMonth() < born.getMonth()
    || (now.getMonth() === born.getMonth() && now.getDate() < born.getDate());
  if (before) age -= 1;
  return age;
}

const listOf = (text: string) =>
  (text || "").split(/[,;]+/).map((x) => x.trim()).filter(Boolean);

/** Fields a person simply types. Anything needing a control to choose from is
 *  deliberately absent and opens the form instead. */
const TYPEABLE: Record<string, { label: string; kind?: string }> = {
  id_number: { label: "ID number" },
  phone: { label: "Phone", kind: "tel" },
  email: { label: "Email", kind: "email" },
  address: { label: "Address" },
  medical_aid_number: { label: "Member no." },
  dependent_code: { label: "Dependant" },
  caregiver_name: { label: "Caregiver" },
  caregiver_phone: { label: "Caregiver phone", kind: "tel" },
  caregiver_relationship: { label: "Relationship" },
};

export default function PatientCardModal({ patient, onClose, onEdit, onSaved }: {
  patient: Patient;
  onClose: () => void;
  /** The saved patient, so the lane and everything reading it keeps up. */
  onSaved?: (patient: Patient) => void;
  /** Change these details here, without leaving what is on the screen.
   *
   *  Given by the dispensary and by nothing else so far. A phone number, a
   *  member number or a new allergy is most often learned WHILE a script is
   *  being dispensed, which is exactly when "Open full record" is disabled
   *  because leaving would drop the script. So the one moment the pharmacy
   *  hears the change was the one moment this screen could not take it, and
   *  the dispenser either wrote it on paper or lost the basket. */
  onEdit?: () => void;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  /** Which field is being typed over, and what has been typed. */
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  /** Keep what was typed into one field.
   *
   *  Sends the WHOLE record, because `PUT /api/patients/{id}` replaces rather
   *  than patches: anything left out of the body is cleared on the patient. So
   *  it is this patient as the form would send them, with the one field
   *  replaced, through the same two helpers the form itself uses.
   *
   *  An empty value is allowed and means the field is now blank. Somebody
   *  deleting a wrong phone number is doing it on purpose.
   */
  async function keep(field: string) {
    const typed = draft.trim();
    setEditing(null);
    const was = String((patient as unknown as Record<string, unknown>)[field] ?? "");
    if (typed === was) return;
    setSaving(true);
    try {
      const saved = await api.put<Patient>(`/api/patients/${patient.id}`,
        { ...payloadOf(draftOf(patient)), [field]: typed });
      onSaved?.(saved);
      toast.ok(`${TYPEABLE[field]?.label ?? "That"} saved.`);
    } catch (e) {
      // Said, and the old value stays on screen, because a value that silently
      // did not save is one somebody will swear they changed.
      toast.error(errorText(e, "That could not be saved. It is unchanged."));
    } finally {
      setSaving(false);
    }
  }

  /** A value that can be typed over, or the plain value where it cannot. */
  function cell(field: string, shown: React.ReactNode) {
    const spec = TYPEABLE[field];
    if (!spec) return shown;
    if (editing === field) {
      return (
        <input className="pt-edit" autoFocus type={spec.kind ?? "text"}
               aria-label={spec.label}
               value={draft}
               onChange={(e) => setDraft(e.target.value)}
               onBlur={() => keep(field)}
               onKeyDown={(e) => {
                 if (e.key === "Enter") { e.preventDefault(); keep(field); }
                 if (e.key === "Escape") { e.preventDefault(); setEditing(null); }
               }} />
      );
    }
    return (
      <span className="pt-typeable"
            title={`Double-click to change the ${spec.label.toLowerCase()}`}
            onDoubleClick={() => {
              setDraft(String((patient as unknown as Record<string, unknown>)[field] ?? ""));
              setEditing(field);
            }}>
        {shown}
      </span>
    );
  }
  const name = `${patient.first_name} ${patient.last_name}`;
  const age = ageFrom(patient.date_of_birth);
  const allergies = listOf(patient.allergies);
  const conditions = listOf(patient.chronic_conditions);
  /** What is missing, in that field's own words.
   *
   *  One shared "None" sat under Date of birth and ID number, where it is
   *  simply wrong: every patient has both and this pharmacy has not written
   *  them down. "None" answers a different question — how many allergies —
   *  and reusing it here makes "not recorded" and "there are none" look
   *  identical, which is the whole reason this product does not print a dash. */
  const absent = (what: string) => <span className="muted">{what}</span>;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Patient: ${name}`}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal pt-modal pt-card">
        <h2>
          {name}
          <span className="disp-entry-of">
            {patient.medical_aid ? patient.medical_aid.name : "Private patient"}
          </span>
        </h2>

        <div className="pt-card-grid">
          <div>
            <section className="ed-sec">
              <h4>Identity</h4>
              <dl className="ed-facts pt-facts">
                <dt>Profile no.</dt><dd className="mono">{patient.profile_number || absent("Not issued")}</dd>
                <dt>ID number</dt><dd>{cell("id_number", patient.id_number || absent("Not on file"))}</dd>
                <dt>Date of birth</dt>
                <dd>{patient.date_of_birth ? `${fmtDate(patient.date_of_birth)}${age !== null ? ` · ${age} yrs` : ""}` : absent("Not recorded")}</dd>
                <dt>Loyalty points</dt><dd>{patient.loyalty_points ?? 0}</dd>
              </dl>
            </section>
            <section className="ed-sec">
              <h4>Contact</h4>
              <dl className="ed-facts pt-facts">
                <dt>Phone</dt><dd>{cell("phone", patient.phone || absent("Not on file"))}</dd>
                <dt>Email</dt><dd className="pt-wrap">{cell("email", patient.email || absent("Not on file"))}</dd>
                <dt>Address</dt><dd className="pt-wrap">{cell("address", patient.address || absent("Not on file"))}</dd>
              </dl>
            </section>
          </div>

          <div>
            <section className="ed-sec">
              <h4>Cover</h4>
              <dl className="ed-facts pt-facts">
                <dt>Medical aid</dt><dd>{patient.medical_aid ? patient.medical_aid.name : "Private"}</dd>
                <dt>Member no.</dt><dd className="mono">{cell("medical_aid_number", patient.medical_aid_number || absent("Not on file"))}</dd>
                <dt>Dependant</dt><dd>{cell("dependent_code", patient.dependent_code || absent("Not set"))}</dd>
              </dl>
            </section>
            <section className="ed-sec">
              <h4>Allergies</h4>
              {allergies.length ? (
                <div className="pt-chips">
                  {allergies.map((a) => (
                    <span key={a} className="ctx-chip is-allergy">
                      <Warning size={12} weight="fill" /> {a}
                    </span>
                  ))}
                </div>
              ) : <p className="chk-coverage">None recorded.</p>}
            </section>
            <section className="ed-sec">
              <h4>Chronic conditions</h4>
              {conditions.length ? (
                <div className="pt-chips">
                  {conditions.map((c) => <span key={c} className="ctx-chip">{c}</span>)}
                </div>
              ) : <p className="chk-coverage">None recorded.</p>}
            </section>
            {patient.caregiver_name && (
              <section className="ed-sec">
                <h4>Caregiver</h4>
                <dl className="ed-facts pt-facts">
                  <dt>Name</dt><dd>{cell("caregiver_name", patient.caregiver_name)}</dd>
                  <dt>Relationship</dt><dd>{cell("caregiver_relationship", patient.caregiver_relationship || absent("Not recorded"))}</dd>
                  <dt>Phone</dt><dd>{cell("caregiver_phone", patient.caregiver_phone || absent("Not on file"))}</dd>
                  <dt>Contact first</dt><dd>{patient.contact_caregiver_first ? "Yes" : "No"}</dd>
                </dl>
              </section>
            )}
          </div>
        </div>

        <div className="disp-edit-actions">
          {saving && <span className="muted small">Saving…</span>}
          <span className="finish-spacer" />
          {onEdit && (
            <button type="button" className="btn secondary" onClick={onEdit}>
              <PencilSimpleLine size={14} /> Edit details
            </button>
          )}
          {/* ALWAYS LIVE.
              This was disabled whenever anything was on the script, with
              "Finish or save the script to open the full record" beside it,
              because leaving the dispensary used to drop a half-built capture.

              It does not any more. The script is kept and restored — see the
              draft note in Dispense.tsx, which says so at length — and coming
              back picks it up with a toast saying how many lines. The button
              stayed disabled on a premise that stopped being true, which is
              the worst kind of dead control: it is right, it is where somebody
              looks, and it refuses.

              What a round trip does lose is the compliance ticks and the
              initials, deliberately: those are somebody's statement that they
              checked something, not typing, and they are made again. */}
          <button type="button" className="btn secondary"
                  onClick={() => navigate(`/patients/${patient.id}`)}>
            <ArrowSquareOut size={14} /> Open full record
          </button>
          <button type="button" className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
