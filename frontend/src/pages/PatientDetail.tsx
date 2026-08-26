import { useEffect, useState } from "react";
import { DetailSkeleton } from "../components/Skeleton";
import Breadcrumbs from "../components/Breadcrumbs";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, money, errorText  } from "../api";
import AiStreamBlock from "../components/AiStreamBlock";
import PageTabs, { TabDef, usePageTabs } from "../components/PageTabs";
import { printLabels } from "../print";
import { Label, Patient, Prescription, Sale } from "../types";
import { useToast } from "../components/Toast";
import ClaudeIcon from "../components/ClaudeIcon";

type Tab = "scripts" | "history" | "sales" | "tax";

interface HistoryLine {
  date: string; product: string; strength: string; quantity: number;
  dosage: string; is_repeat: boolean; rx_number: string; dispensed_by: string;
}

export default function PatientDetail() {
  const { id } = useParams();
  const toast = useToast();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [scripts, setScripts] = useState<Prescription[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [history, setHistory] = useState<HistoryLine[]>([]);
  const [tax, setTax] = useState<any>(null);
  const TABS: TabDef<Tab>[] = [
    { key: "scripts", label: "Prescriptions", count: scripts.length },
    { key: "history", label: "Dispensing history", count: history.length },
    { key: "sales", label: "Purchases", count: sales.length },
    { key: "tax", label: "Tax statement" },
  ];
  const [tab, setTab] = usePageTabs<Tab>(TABS, "scripts");

  useEffect(() => {
    api.get<Patient>(`/api/patients/${id}`).then(setPatient);
    api.get<Prescription[]>(`/api/prescriptions?patient_id=${id}`).then(setScripts);
    api.get<Sale[]>(`/api/patients/${id}/sales`).then(setSales);
    api.get<HistoryLine[]>(`/api/reports/patient/${id}/history`).then(setHistory);
    api.get(`/api/reports/patient/${id}/tax`).then(setTax);
  }, [id]);

  if (!patient) return <DetailSkeleton
        trail={[{ label: "Dashboard", to: "/" }, { label: "Patients", to: "/patients" }, { label: "This record" }]}
        eyebrow="Patient"
        tabs={["Prescriptions", "Dispensing history", "Purchases", "Tax statement"]}
        cards={3}
        avatar
        table={5}
      />;

  async function sendPortalLink() {
    try {
      const r = await api.post<{ path: string; send_to: string; expires_in_days: number }>(
        `/api/portal-admin/links/patient/${id}`);
      // Copied rather than sent: this pharmacy messages patients on WhatsApp,
      // and pasting a link into the chat they already have open beats building
      // a sending integration nobody asked for.
      const url = `${window.location.origin}${r.path}`;
      await navigator.clipboard?.writeText(url).catch(() => undefined);
      toast.ok(
        `Link copied, send it to ${r.send_to}. It works for ${r.expires_in_days} days.`);
    } catch (e: any) {
      toast.error(errorText(e));
    }
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
        <Link to="/dispense" className="btn">New Script</Link>
      </div>

      {(patient.allergies || patient.chronic_conditions) && (
        <div className="error-banner">
          {patient.allergies && <>⚠ Allergies: <b>{patient.allergies}</b>&nbsp;&nbsp;</>}
          {patient.chronic_conditions && <>· Chronic: {patient.chronic_conditions}</>}
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
              <b>{rx.rx_number}</b> · {fmtDate(rx.date_prescribed)} · {rx.doctor?.name}
              <button className="ghost small" onClick={() =>
                api.get<Label[]>(`/api/prescriptions/${rx.id}/labels`).then(printLabels)}>
                🖨 Labels
              </button>
              <table style={{ marginTop: 6 }}>
                <thead><tr><th>Medication</th><th>Dosage</th><th className="num">Qty</th><th>Repeats</th><th>Next repeat</th><th>Auto-refill</th></tr></thead>
                <tbody>
                  {rx.items.map((i) => (
                    <tr key={i.id}>
                      <td>{i.product?.name} {i.product?.strength}</td>
                      <td>{i.dosage_instructions || "—"}</td>
                      <td className="num">{i.quantity}</td>
                      <td>{i.repeats_used}/{i.repeats_allowed}</td>
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
                <tr key={i}>
                  <td>{fmtDateTime(h.date)}</td>
                  <td>{h.product} {h.strength}</td>
                  <td className="num">{h.quantity}</td>
                  <td>{h.dosage}</td>
                  <td>{h.is_repeat ? <span className="badge">Repeat</span> : <span className="badge muted">Original</span>}</td>
                  <td className="mono">{h.rx_number}</td>
                  <td>{h.dispensed_by}</td>
                </tr>
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
                  <td className="mono">{s.sale_number}</td>
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
            <button className="secondary" onClick={() => window.print()}>Print statement</button>
          </div>
        </div>
      )}
    </>
  );
}
