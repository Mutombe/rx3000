/** Who this patient is, at a glance, without leaving the dispensary.
 *
 *  Two balanced columns: on the left who they are and how to reach them; on
 *  the right what the counter has to act on — their cover, what they are
 *  allergic to, what they live with, and who to speak to when it is not them.
 *
 *  The full record is one press away, but only when there is no script on the
 *  screen: leaving the dispensary drops a half-built script, and a button that
 *  quietly throws away somebody's work is the wrong kind of shortcut.
 */
import { useNavigate } from "react-router-dom";
import { ArrowSquareOut, PencilSimpleLine, Warning } from "@phosphor-icons/react";
import { fmtDate } from "../api";
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

export default function PatientCardModal({ patient, canLeave, onClose, onEdit }: {
  patient: Patient;
  /** Whether leaving the dispensary is safe — nothing on the script yet. */
  canLeave: boolean;
  onClose: () => void;
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
                <dt>ID number</dt><dd>{patient.id_number || absent("Not on file")}</dd>
                <dt>Date of birth</dt>
                <dd>{patient.date_of_birth ? `${fmtDate(patient.date_of_birth)}${age !== null ? ` · ${age} yrs` : ""}` : absent("Not recorded")}</dd>
                <dt>Loyalty points</dt><dd>{patient.loyalty_points ?? 0}</dd>
              </dl>
            </section>
            <section className="ed-sec">
              <h4>Contact</h4>
              <dl className="ed-facts pt-facts">
                <dt>Phone</dt><dd>{patient.phone || absent("Not on file")}</dd>
                <dt>Email</dt><dd className="pt-wrap">{patient.email || absent("Not on file")}</dd>
                <dt>Address</dt><dd className="pt-wrap">{patient.address || absent("Not on file")}</dd>
              </dl>
            </section>
          </div>

          <div>
            <section className="ed-sec">
              <h4>Cover</h4>
              <dl className="ed-facts pt-facts">
                <dt>Medical aid</dt><dd>{patient.medical_aid ? patient.medical_aid.name : "Private"}</dd>
                <dt>Member no.</dt><dd className="mono">{patient.medical_aid_number || absent("Not on file")}</dd>
                <dt>Dependant</dt><dd>{patient.dependent_code || absent("Not set")}</dd>
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
                  <dt>Name</dt><dd>{patient.caregiver_name}</dd>
                  <dt>Relationship</dt><dd>{patient.caregiver_relationship || absent("Not recorded")}</dd>
                  <dt>Phone</dt><dd>{patient.caregiver_phone || absent("Not on file")}</dd>
                  <dt>Contact first</dt><dd>{patient.contact_caregiver_first ? "Yes" : "No"}</dd>
                </dl>
              </section>
            )}
          </div>
        </div>

        <div className="disp-edit-actions">
          {!canLeave && (
            <p className="disp-blocked">
              <Warning size={14} weight="fill" />
              <span>Finish or save the script to open the full record.</span>
            </p>
          )}
          <span className="finish-spacer" />
          {onEdit && (
            <button type="button" className="btn secondary" onClick={onEdit}>
              <PencilSimpleLine size={14} /> Edit details
            </button>
          )}
          <button type="button" className="btn secondary" disabled={!canLeave}
                  onClick={() => navigate(`/patients/${patient.id}`)}>
            <ArrowSquareOut size={14} /> Open full record
          </button>
          <button type="button" className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
