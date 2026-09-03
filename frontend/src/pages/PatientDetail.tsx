import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import BusyButton from "../components/BusyButton";
import TermSelect from "../components/TermSelect";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText, prefetchRoute } from "../api";
import { printDocument } from "../document";
import { letterhead } from "../letterhead";
import AiStreamBlock from "../components/AiStreamBlock";
import ConsentPanel from "../components/ConsentPanel";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { printLabels } from "../print";
import { Label, Patient, Prescription, Sale, TimelineEntry } from "../types";
import { DRAFT_SCRIPT } from "../terms";
import Select from "../components/Select";
import { useToast } from "../components/Toast";
import ClaudeIcon from "../components/ClaudeIcon";
import { CalendarBlank, CheckSquare, PencilSimpleLine, PhoneCall } from "@phosphor-icons/react";

import { EntityLink } from "../components/Filters";
import RowLink from "../components/RowLink";
import { usePharmacy } from "../hooks/usePharmacy";
import SharePortalLink, { PortalLink } from "../components/SharePortalLink";
import PatientPortalPreview from "../components/PatientPortalPreview";
import RepeatValue from "../components/RepeatValue";
type Tab = "scripts" | "history" | "sales" | "contact" | "tax" | "consent";

interface HistoryLine {
  id: number;
  collected_at: string | null;
  date: string; product: string; strength: string; quantity: number;
  dosage: string; is_repeat: boolean; rx_number: string; dispensed_by: string;
  // The ids behind the three names above. The endpoint held all of them and
  // sent none, so every name in the history table was a dead end.
  product_id: number | null;
  prescription_id: number | null;
  dispensed_by_id: number | null;
}

export default function PatientDetail() {
  const { id } = useParams();
  const toast = useToast();
  const pharmacy = usePharmacy();
  const [link, setLink] = useState<PortalLink | null>(null);
  const [asPatient, setAsPatient] = useState<any | null>(null);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [clinical, setClinical] =
    useState<{ allergies: string; chronic_conditions: string } | null>(null);
  const [scripts, setScripts] = useState<Prescription[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [history, setHistory] = useState<HistoryLine[]>([]);
  const [tax, setTax] = useState<any>(null);
  const [log, setLog] = useState<TimelineEntry[]>([]);
  const [logForm, setLogForm] = useState(
    { activity_type: "call", subject: "", body: "", due_at: "" });
  const TABS: TabDef<Tab>[] = [
    { key: "scripts", label: "Prescriptions", count: scripts.length },
    { key: "history", label: "Dispensing history", count: history.length },
    { key: "sales", label: "Purchases", count: sales.length },
    // Every conversation this pharmacy has had with them. The record of the
    // medicine was here; the record of the phone calls about it was not, so
    // "I rang her twice about that repeat" lived in one person's memory.
    { key: "contact", label: "Contact log", count: log.length },
    { key: "tax", label: "Tax statement" },
    // On the patient record, because that is where somebody stands when they
    // say "stop sending me those" — not buried in a settings screen.
    { key: "consent", label: "Consent" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "scripts");

  useEffect(() => {
    api.get<Patient>(`/api/patients/${id}`).then(setPatient);
    api.get<Prescription[]>(`/api/prescriptions?patient_id=${id}`).then(setScripts);
    api.get<Sale[]>(`/api/patients/${id}/sales`).then(setSales);
    api.get<HistoryLine[]>(`/api/reports/patient/${id}/history`).then(setHistory);
    api.get(`/api/reports/patient/${id}/tax`).then(setTax);
    loadLog();
  }, [id]);

  if (!patient) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Patients", to: "/patients" }, { label: "This record" }]}
        eyebrow="Patient"
        tabs={["Prescriptions", "Dispensing history", "Purchases", "Tax statement"]}
        cards={3}
        avatar
        table={5}
      />;

  function loadLog() {
    api.get<TimelineEntry[]>(`/api/crm/timeline?patient_id=${id}`)
      // A patient nobody has ever rung has no timeline, and that is not an
      // error worth showing anybody.
      .then(setLog).catch(() => setLog([]));
  }

  async function logContact() {
    try {
      await api.post("/api/crm/activities", {
        activity_type: logForm.activity_type,
        subject: logForm.subject.trim(),
        body: logForm.body.trim(),
        // A date turns it from something that happened into something owed.
        due_at: logForm.due_at ? `${logForm.due_at}T09:00:00` : null,
        patient_id: Number(id),
      });
      toast.ok(logForm.due_at ? "Saved, and it will come up on that date."
                              : "Logged against this patient.");
      setLogForm({ activity_type: "call", subject: "", body: "", due_at: "" });
      loadLog();
    } catch (e) {
      toast.error(errorText(e, "That could not be logged. Nothing was saved."));
    }
  }

  /** Open the share sheet, rather than copying silently.
   *
   *  This used to put the URL on the clipboard and say so in a toast, which
   *  asks the person at the counter to remember the number, open WhatsApp,
   *  find the chat and paste — four steps with a patient standing there, and
   *  the message that eventually goes is a bare URL nobody opens.
   */
  async function sendPortalLink() {
    try {
      setLink(await api.post<PortalLink>(
        `/api/portal-admin/links/patient/${id}`));
    } catch (e: any) {
      toast.error(errorText(e));
    }
  }

  /** See the portal as they see it.
   *
   *  "It does not show my tablets" cannot be answered from a description, and
   *  asking the patient to read their code down the telephone teaches them to
   *  give it away. Their record, through a staff session already audited.
   */
  async function viewAsPatient() {
    try {
      setAsPatient(await api.get<any>(
        `/api/portal-admin/patient/${id}/preview`));
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  function openClinical() {
    if (!patient) return;
    setClinical({
      allergies: patient.allergies ?? "",
      chronic_conditions: patient.chronic_conditions ?? "",
    });
  }

  /** Save the two clinical fields without disturbing the rest of the record.
   *
   *  The patient endpoint replaces the whole object, so this sends the patient
   *  it already has with the two fields changed. Sending only the two would
   *  answer 422 for the missing name, and worse, a partial write here would
   *  quietly blank a caregiver's phone number.
   */
  async function saveClinical() {
    if (!patient || !clinical) return;
    try {
      // Closed before the write, not after it. A record being created
      // or edited costs a click if it fails, and the list is what
      // confirms it either way.
      setClinical(null);
      const saved = await api.put<Patient>(`/api/patients/${patient.id}`, {
        ...patient,
        medical_aid_id: patient.medical_aid_id ?? null,
        allergies: clinical.allergies,
        chronic_conditions: clinical.chronic_conditions,
      });
      setPatient(saved);
      toast.ok("Updated.");
    } catch (e) {
      toast.error(errorText(e, "That could not be saved. Nothing was saved."));
    }
  }

  /** The medical expense statement, as something a patient can hand to ZIMRA.
   *
   *  A tax authority is the least forgiving reader a pharmacy has. A screen
   *  print with a browser header on it is not a statement from a pharmacy; it
   *  is a picture of one, and a patient who submits it gets the deduction
   *  refused and comes back cross. This is the same figures on the pharmacy's
   *  letterhead, addressed to the patient, with the tax year stated.
   */
  async function printTaxStatement() {
    if (!tax) return;
    const head = await letterhead();
    printDocument(head, {
      kind: "Medical expense statement",
      to: [patient ? `${patient.first_name} ${patient.last_name}` : "Patient",
           patient?.address ?? "", patient?.phone ?? ""].filter(Boolean),
      meta: [
        { label: "Tax year", value: String(tax.tax_year) },
        { label: "Total spent", value: money(tax.total_spent) },
        { label: "Medical aid paid", value: money(tax.total_medical_aid_paid) },
        { label: "Out of pocket", value: money(tax.total_out_of_pocket),
          strong: true },
      ],
      columns: [
        { key: "date", label: "Date", width: "24mm" },
        { key: "invoice", label: "Invoice", width: "28mm" },
        { key: "items", label: "Dispensed" },
        { key: "total", label: "Total", numeric: true, width: "24mm" },
        { key: "aid", label: "Aid paid", numeric: true, width: "24mm" },
        { key: "own", label: "Out of pocket", numeric: true, width: "28mm" },
      ],
      rows: tax.lines.map((l: any) => ({
        date: l.date, invoice: l.invoice, items: l.items.join(", "),
        total: money(l.total), aid: money(l.medical_aid_paid),
        own: money(l.out_of_pocket),
      })),
      totals: {
        items: "Total for the year",
        total: money(tax.total_spent),
        aid: money(tax.total_medical_aid_paid),
        own: money(tax.total_out_of_pocket),
      },
      note: "Issued at the patient's request in support of a medical expenses "
          + "claim. Only amounts actually paid by the patient appear in the "
          + "out-of-pocket column.",
    });
  }

  return (
    <>
      <Breadcrumbs
        trail={[{ label: "Dashboard", to: "/" }, { label: "Patients", to: "/patients" }, { label: "This record" }]}
        actions={
          <button className="ghost small" onClick={sendPortalLink}>
            Send portal link
          </button>
        }
      />
      <div className="page-head">
        <div>
          <h1>{patient.first_name} {patient.last_name}</h1>
          <div className="sub">
            {patient.id_number && <>ID {patient.id_number} · </>}
            DOB {fmtDate(patient.date_of_birth)} · {patient.phone || "no phone"} ·{" "}
            {patient.medical_aid ? `${patient.medical_aid.name} #${patient.medical_aid_number}` : "Private patient"} ·{" "}
            <b>{patient.loyalty_points} loyalty pts</b>
          </div>
        </div>
        {/* The patient travels with the link. This was a bare `/dispense`,
            so pressing it from somebody's record opened an empty dispensary
            and the first thing you did was search for the person you had just
            been reading about. */}
        <Link to={`/dispense?patient=${patient.id}`} className="btn">New Script</Link>
        <button className="btn secondary" onClick={viewAsPatient}>
          See it as they do
        </button>
      </div>

      {/* The banner is where anybody looks for this, so it is also where it is
          changed. Editing a patient's allergies used to be possible only from a
          small icon on the list page, and once the list rows became links,
          clicking a patient took you here, to a screen that showed the allergy
          and gave you no way to correct it. */}
      {(patient.allergies || patient.chronic_conditions) ? (
        <div className="error-banner">
          {patient.allergies && <>⚠ Allergies: <b>{patient.allergies}</b>&nbsp;&nbsp;</>}
          {patient.chronic_conditions && <>· Chronic: {patient.chronic_conditions}</>}
          <button className="btn ghost small" onClick={openClinical}>Change</button>
        </div>
      ) : (
        <p className="muted">
          No allergies or chronic conditions recorded.{" "}
          <button className="btn ghost small" onClick={openClinical}>Record them</button>
        </p>
      )}

      {clinical && (
        <div className="modal-backdrop" onClick={() => setClinical(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{patient.first_name} {patient.last_name}</h2>
            <p className="muted">
              Both of these are read by the system, not only by people. An
              allergy here stops a dispensing of anything that matches it, and a
              chronic condition moves this patient's repeats up the queue — so
              they are picked from a list rather than typed, and a spelling
              cannot quietly switch the check off.
            </p>
            <label className="field">
              Allergies
              <TermSelect
                kind="allergy"
                value={clinical.allergies}
                onChange={(v) => setClinical({ ...clinical, allergies: v })}
                placeholder="Search allergies, or add a new one"
              />
            </label>
            <label className="field">
              Chronic conditions
              <TermSelect
                kind="condition"
                value={clinical.chronic_conditions}
                onChange={(v) => setClinical({ ...clinical, chronic_conditions: v })}
                placeholder="Search conditions, or add a new one"
              />
            </label>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setClinical(null)}>Cancel</button>
              <BusyButton onClick={saveClinical}>Save</BusyButton>
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h3><ClaudeIcon size={16} /> AI clinical summary</h3>
        <AiStreamBlock
          path={`/api/ai/patient-summary/${id}/stream`}
          label="Generate summary"
          title="Patient summary"
          context={`Patient #${id}`}
          empty="A hand-over summary of this patient's medication history and counselling points, written as it is thought."
        />
      </div>

      <PageTabs tabs={TABS} tab={tab} setTab={setTab} />

      {tab === "scripts" && (
        <div className="card">
          {scripts.length === 0 && <div className="empty">No prescriptions on file</div>}
          {scripts.map((rx) => (
            <div key={rx.id} style={{ marginBottom: 18 }}>
              {/* The number was plain text on the one screen where somebody is
                  looking at a patient's scripts and wants to open one. Every
                  other screen in the product links an Rx number; this did not.
                  An N-Repeat carries a draft reference instead of an Rx number,
                  and rendered blank here, so a half-captured script showed as
                  a date and a doctor with nothing to identify it. */}
              <EntityLink kind="prescription" id={rx.id}>
                <b className="script-id">
                  {rx.rx_number || rx.draft_ref || `#${rx.id}`}
                </b>
              </EntityLink>
              {!rx.rx_number && (
                <span className="badge warn" style={{ marginLeft: 6 }}>
                  {DRAFT_SCRIPT}
                </span>
              )}
              {" · "}{fmtDate(rx.date_prescribed)} · {rx.doctor?.name}
              <button className="ghost small" onClick={() =>
                api.get<Label[]>(`/api/prescriptions/${rx.id}/labels`).then(printLabels)}>
                🖨 Labels
              </button>
              <table style={{ marginTop: 6 }}>
                {/* What each line is worth per collection, and what the rest
                    of the script is worth behind it. A patient record that
                    lists four repeats and no money cannot answer the one
                    question a shop asks about a patient — what they are worth
                    if they keep coming back, and what walks out with them if
                    they do not. */}
                <thead><tr><th>Medication</th><th>Dosage</th><th className="num">Qty</th><th>Repeats</th><th className="num">Worth</th><th>Next repeat</th><th>Auto-refill</th></tr></thead>
                <tbody>
                  {rx.items.map((i) => (
                    <tr key={i.id}>
                      <td><EntityLink kind="product" id={i.product_id}>{i.product?.name} {i.product?.strength}</EntityLink></td>
                      <td>{i.dosage_instructions || "—"}</td>
                      <td className="num">{i.quantity}</td>
                      <td>{i.repeats_used}/{i.repeats_allowed}</td>
                      <td className="num">
                        <RepeatValue
                          value={(i.product?.unit_price ?? 0) * (i.quantity ?? 0)}
                          remaining={(i.product?.unit_price ?? 0) * (i.quantity ?? 0)
                            * Math.max(0, (i.repeats_allowed ?? 0) - (i.repeats_used ?? 0))} />
                      </td>
                      <td>{fmtDate(i.next_repeat_date)}</td>
                      <td>{i.auto_refill ? <span className="badge ok">Yes</span> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {tab === "history" && (
        <div className="card">
          <table>
            <thead><tr><th>Date</th><th>Medication</th><th className="num">Qty</th><th>Dosage</th><th>Type</th><th>Script</th><th>By</th></tr></thead>
            <tbody>
              {history.map((h, i) => (
                // Every name in this row is a record. They were all printed as
                // text while the endpoint held the ids and sent none of them,
                // so "which script was this?" meant leaving the patient and
                // searching by number.
                // The row opens the handover itself. Every name on it opened
                // something and the row opened nothing, which is the same
                // fault the comment above describes, one level up.
                <RowLink key={i} to={`/dispensings/${h.id}`}
                         prefetch={prefetchRoute}>
                  <td>{fmtDateTime(h.date)}</td>
                  <td>
                    <EntityLink kind="product" id={h.product_id}>
                      {h.product} {h.strength}
                    </EntityLink>
                  </td>
                  <td className="num">{h.quantity}</td>
                  <td>{h.dosage}</td>
                  <td>{h.is_repeat ? <span className="badge">Repeat</span> : <span className="badge muted">Original</span>}</td>
                  <td className="mono">
                    <EntityLink kind="prescription" id={h.prescription_id}>
                      {h.rx_number}
                    </EntityLink>
                  </td>
                  <td>
                    <EntityLink kind="staff" id={h.dispensed_by_id}>
                      {h.dispensed_by}
                    </EntityLink>
                  </td>
                </RowLink>
              ))}
            </tbody>
          </table>
          {history.length === 0 && <div className="empty">Nothing dispensed yet</div>}
        </div>
      )}

      {tab === "sales" && (
        <div className="card">
          <table>
            <thead><tr><th>Date</th><th>Invoice</th><th>Items</th><th>Payment</th><th className="num">Total</th><th>Status</th></tr></thead>
            <tbody>
              {sales.map((s) => (
                <tr key={s.id}>
                  <td>{fmtDateTime(s.created_at)}</td>
                  <td className="mono">
                    <EntityLink kind="sale" id={s.id}>{s.sale_number}</EntityLink>
                  </td>
                  <td>{s.items.map((i) => i.description).join(", ")}</td>
                  <td>{s.payment_method.replace("_", " ")}</td>
                  <td className="num">{money(s.total)}</td>
                  <td><span className={`badge ${s.status === "paid" ? "ok" : s.status === "void" ? "danger" : "warn"}`}>{s.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {sales.length === 0 && <div className="empty">No purchases yet</div>}
        </div>
      )}

      {tab === "tax" && tax && (
        <div className="card">
          <h3>Medical expense statement, tax year {tax.tax_year}</h3>
          <div className="grid cols-3" style={{ margin: "14px 0" }}>
            <div className="card stat"><div className="label">Total spent</div><div className="value">{money(tax.total_spent)}</div></div>
            <div className="card stat"><div className="label">Medical aid paid</div><div className="value">{money(tax.total_medical_aid_paid)}</div></div>
            <div className="card stat"><div className="label">Out of pocket</div><div className="value accent">{money(tax.total_out_of_pocket)}</div></div>
          </div>
          <table>
            <thead><tr><th>Date</th><th>Invoice</th><th>Items</th><th className="num">Total</th><th className="num">Aid paid</th><th className="num">Out of pocket</th></tr></thead>
            <tbody>
              {tax.lines.map((l: any, i: number) => (
                <tr key={i}>
                  <td>{l.date}</td><td className="mono">{l.invoice}</td>
                  <td>{l.items.join(", ")}</td>
                  <td className="num">{money(l.total)}</td>
                  <td className="num">{money(l.medical_aid_paid)}</td>
                  <td className="num">{money(l.out_of_pocket)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 12 }}>
            <button className="secondary" onClick={printTaxStatement}>
              Print statement
            </button>
          </div>
        </div>
      )}

      {tab === "contact" && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>Log a contact</h3>
              <span className="muted small">
                Whoever picks this record up next reads what you write here.
              </span>
            </div>
            <div className="form-row">
              <div className="field">
                <label>What happened</label>
                <Select
                  value={logForm.activity_type}
                  onChange={(v) => setLogForm({ ...logForm, activity_type: v })}
                  options={[
                    { value: "call", label: "Phone call" },
                    { value: "sms", label: "Text message" },
                    { value: "email", label: "Email" },
                    { value: "meeting", label: "Spoke at the counter" },
                    { value: "note", label: "Note" },
                    { value: "task", label: "Something to do" },
                  ]}
                />
              </div>
              <div className="field">
                <label>In a line</label>
                <input
                  value={logForm.subject}
                  onChange={(e) => setLogForm({ ...logForm, subject: e.target.value })}
                  placeholder="e.g. Rang about the metformin repeat — no answer"
                />
              </div>
              <div className="field">
                <label>Come back to it on</label>
                <input type="date" value={logForm.due_at}
                       onChange={(e) => setLogForm({ ...logForm, due_at: e.target.value })} />
                <span className="field-hint">
                  {logForm.due_at
                    ? "It stays open until somebody ticks it off."
                    : "Leave empty if it is already done."}
                </span>
              </div>
            </div>
            <div className="field">
              <label>Anything else</label>
              <textarea rows={2} value={logForm.body}
                        onChange={(e) => setLogForm({ ...logForm, body: e.target.value })}
                        placeholder="optional" />
            </div>
            <div className="modal-actions">
              <BusyButton disabled={logForm.subject.trim().length < 3}
                          onClick={logContact}>
                Log it
              </BusyButton>
            </div>
          </div>

          <div className="card">
            <h3>Everything said to this patient</h3>
            {log.length === 0 && (
              <div className="empty">
                Nobody has recorded a conversation with this patient. Calls about
                a late repeat, a counselling point, a complaint — none of it is
                anywhere until somebody writes it down.
              </div>
            )}
            <table className="dt">
              <tbody>
                {log.map((t) => (
                  <tr key={t.id}>
                    <td style={{ width: 30 }}>
                      {t.type === "task" ? <CheckSquare size={14} />
                        : t.type === "call" ? <PhoneCall size={14} />
                        : t.type === "meeting" ? <CalendarBlank size={14} />
                        : <PencilSimpleLine size={14} />}
                    </td>
                    <td>
                      <b>{t.subject}</b>
                      {t.body && <div className="muted small wrap">{t.body}</div>}
                      <div className="muted small">
                        {t.owner ?? "system"} · {fmtDateTime(t.created_at)}
                        {t.completed_at && " · done"}
                      </div>
                    </td>
                    <td className="actions">
                      {/* Only what is still owed gets a button. Everything else
                          is history and needs nothing doing to it. */}
                      {t.due_at && !t.completed_at && (
                        <>
                          <span className="badge warn">due {fmtDate(t.due_at)}</span>
                          <BusyButton className="btn small secondary" onClick={async () => {
                            await api.post(`/api/crm/activities/${t.id}/complete`, {});
                            loadLog();
                          }}>Mark done</BusyButton>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "consent" && (
        <div className="card">
          <div className="card-head">
            <h3>What they have agreed to</h3>
          </div>
          <ConsentPanel subjectType="patient" subjectId={Number(id)} />
        </div>
      )}
      {link && (
        <SharePortalLink link={link} pharmacy={pharmacy.name}
          patientId={Number(id)} onClose={() => setLink(null)}
          onNewCode={(code) => setLink((l) => (l ? { ...l, code } : l))} />
      )}
      {asPatient && (
        <PatientPortalPreview record={asPatient}
          onClose={() => setAsPatient(null)} />
      )}
    </>
  );
}
