import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import Pagination, { Paged } from "../components/Pagination";
import { Link } from "react-router-dom";
import { api, fmtDate, prefetchRoute, errorText  } from "../api";
import { MedicalAid, Patient } from "../types";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import IconButton from "../components/IconButton";

const EMPTY = {
  first_name: "", last_name: "", id_number: "", date_of_birth: "",
  phone: "", email: "", address: "", allergies: "", chronic_conditions: "",
  medical_aid_id: "" as string | number, medical_aid_number: "", dependent_code: "00",
  // Who to deal with when it is not the patient. The columns and the worklist
  // that reads them existed; the form had no fields, so nothing was ever set.
  caregiver_name: "", caregiver_phone: "", caregiver_relationship: "",
  contact_caregiver_first: false,
};

export default function Patients() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loading, setLoading] = useState(true);
  const [meta, setMeta] = useState<Paged<Patient> | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [aids, setAids] = useState<MedicalAid[]>([]);
  const [q, setQ] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Patient | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const toast = useToast();

  function load() {
    setLoading(true);
    api
      .get<Paged<Patient>>(
        `/api/patients/paged?q=${encodeURIComponent(q)}&page=${page}&per_page=${perPage}`,
      )
      .then((r) => {
        setPatients(r.items);
        setMeta(r);
        // The server clamps a page past the end; follow it, or the controls and
        // the data disagree about where we are.
        if (r.page !== page) setPage(r.page);
      })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, [q, page, perPage]);
  useEffect(() => setPage(1), [q]);
  useEffect(() => { api.get<MedicalAid[]>("/api/medical-aids").then(setAids); }, []);

  function openNew() {
    setEditing(null);
    setForm({ ...EMPTY });
    setShowForm(true);
  }

  function openEdit(p: Patient) {
    setEditing(p);
    setForm({
      first_name: p.first_name, last_name: p.last_name, id_number: p.id_number,
      date_of_birth: p.date_of_birth ?? "", phone: p.phone, email: p.email, address: p.address,
      allergies: p.allergies, chronic_conditions: p.chronic_conditions,
      medical_aid_id: p.medical_aid_id ?? "", medical_aid_number: p.medical_aid_number,
      dependent_code: p.dependent_code,
      caregiver_name: p.caregiver_name ?? "", caregiver_phone: p.caregiver_phone ?? "",
      caregiver_relationship: p.caregiver_relationship ?? "",
      contact_caregiver_first: p.contact_caregiver_first ?? false,
    });
    setShowForm(true);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = {
      ...form,
      date_of_birth: form.date_of_birth || null,
      medical_aid_id: form.medical_aid_id === "" ? null : Number(form.medical_aid_id),
    };
    try {
      if (editing) await api.put(`/api/patients/${editing.id}`, body);
      else await api.post("/api/patients", body);
      setShowForm(false);
      load();
    } catch (err: any) {
      toast.error(errorText(err));
    }
  }

  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Patients</h1>
          <div className="sub">Profiles, medical aid membership, allergies and loyalty</div>
        </div>
        <button onClick={openNew}>+ New Patient</button>
      </div>
      <div className="card">
        <div className="toolbar">
          <input type="search" placeholder="Search name, ID number, phone, member no…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Refreshable
          loading={loading}
          hasData={patients.length > 0}
          skeleton={
            <TableSkeleton cols={7} rows={6}
              widths={["22ch", "14ch", "16ch", "16ch", "14ch", "8ch", "10ch"]} />
          }
        >
        <div className="dt-scroll">
          <table className="dt">
            <thead>
              <tr>
                <th>Patient</th><th>ID Number</th><th>Contact</th><th>Medical Aid</th>
                <th>Allergies</th><th className="num">Loyalty</th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {patients.map((p) => (
                <RowLink key={p.id} to={`/patients/${p.id}`} prefetch={prefetchRoute}>
                  {/* The name was the cell making rows ragged: "Probe 02872A,
                      Allergy…" wrapped to four lines and took its row from 66px to
                      86px. Two clipped lines, each with the full value on hover. */}
                  <td>
                    <Link to={`/patients/${p.id}`} className="clip"
                      title={`${p.last_name}, ${p.first_name}`}>
                      <b>{p.last_name}, {p.first_name}</b>
                    </Link>
                    <div className="muted clip">{fmtDate(p.date_of_birth)}</div>
                  </td>
                  <td className="mono">{p.id_number || "—"}</td>
                  <td>
                    <span className="clip" title={p.phone}>{p.phone}</span>
                    <span className="clip muted" title={p.email}>{p.email}</span>
                  </td>
                  <td>
                    {p.medical_aid ? (
                      <>
                        <span className="badge clip" title={p.medical_aid.name}
                          style={{ maxWidth: "10rem" }}>{p.medical_aid.name}</span>
                        <div className="muted mono clip">{p.medical_aid_number}</div>
                      </>
                    ) : <span className="badge muted">Private</span>}
                  </td>
                  {/* Free text in a badge: "penicillin, sulfa, aspirin, latex,
                      iodine…" grew the row past its neighbours. Clipped, with the
                      full list on hover — and the badge keeps its shape. */}
                  <td>
                    {p.allergies
                      ? <span className="badge danger clip" title={p.allergies}
                          style={{ maxWidth: "12rem" }}>{p.allergies}</span>
                      : "—"}
                  </td>
                  <td className="num">{p.loyalty_points} pts</td>
                  <RowActions>
                    <IconButton action="edit" onClick={() => openEdit(p)} />
                  </RowActions>
                </RowLink>
              ))}
            </tbody>
          </table>
        </div>
          {meta && (
            <Pagination
              meta={meta}
              noun="patients"
              onPage={setPage}
              onPerPage={(n) => { setPerPage(n); setPage(1); }}
            />
          )}
        </Refreshable>
        {patients.length === 0 && <div className="empty">No patients found</div>}
      </div>

      {showForm && (
        <div className="modal-backdrop" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editing ? "Edit Patient" : "New Patient"}</h2>
            <form onSubmit={save}>
              <div className="form-row">
                <div className="field"><label>First name</label><input required value={form.first_name} onChange={set("first_name")} /></div>
                <div className="field"><label>Last name</label><input required value={form.last_name} onChange={set("last_name")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>ID number</label><input value={form.id_number} onChange={set("id_number")} /></div>
                <div className="field"><label>Date of birth</label><input type="date" value={form.date_of_birth} onChange={set("date_of_birth")} /></div>
              </div>
              <div className="form-row">
                <div className="field"><label>Phone</label><input value={form.phone} onChange={set("phone")} /></div>
                <div className="field"><label>Email</label><input type="email" value={form.email} onChange={set("email")} /></div>
              </div>
              <div className="field"><label>Address</label><input value={form.address} onChange={set("address")} /></div>
              <div className="form-row">
                <div className="field"><label>Allergies</label><input value={form.allergies} onChange={set("allergies")} placeholder="e.g. Penicillin" /></div>
                <div className="field"><label>Chronic conditions</label><input value={form.chronic_conditions} onChange={set("chronic_conditions")} /></div>
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Medical aid</label>
                  <Select
                    value={String(form.medical_aid_id ?? "")}
                    onChange={(__value) => set("medical_aid_id")({ target: { value: __value } } as any)}
                    options={[{ value: "", label: "Private (none)" }, ...aids.map((a) => ({ value: String(a.id), label: a.name }))]}
                  />
                </div>
                <div className="field"><label>Member number</label><input value={form.medical_aid_number} onChange={set("medical_aid_number")} /></div>
                <div className="field" style={{ maxWidth: 90 }}><label>Dep.</label><input value={form.dependent_code} onChange={set("dependent_code")} /></div>
              </div>

              <h4 className="form-section">Caregiver</h4>
              <p className="muted small">
                Left blank for a patient who manages their own medicine. Filled in,
                this is who gets the reminder, signs for a delivery and takes the
                follow-up call.
              </p>
              <div className="form-row">
                <div className="field"><label>Name</label><input value={form.caregiver_name} onChange={set("caregiver_name")} /></div>
                <div className="field"><label>Phone</label><input value={form.caregiver_phone} onChange={set("caregiver_phone")} placeholder="+263…" /></div>
                <div className="field"><label>Relationship</label><input value={form.caregiver_relationship} onChange={set("caregiver_relationship")} placeholder="e.g. daughter" /></div>
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
                <button type="button" className="secondary" onClick={() => setShowForm(false)}>Cancel</button>
                <button type="submit">Save patient</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
