import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import RowLink, { RowActions } from "../components/RowLink";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import Pagination, { Paged } from "../components/Pagination";
import { Link } from "react-router-dom";
import { api, fmtDate, prefetchRoute, errorText  } from "../api";
import { MedicalAid, Patient } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import PatientForm from "../components/PatientForm";

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
                      full list on hover, and the badge keeps its shape. */}
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
        <PatientForm
          open={showForm}
          editing={editing}
          initial={editing ? (form as any) : { ...form }}
          onClose={() => setShowForm(false)}
          onSaved={() => load()}
        />
      )}
    </>
  );
}
