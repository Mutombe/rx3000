import { FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toast";
import { api, fmtDateTime, errorText  } from "../api";
import { Message, Patient } from "../types";
import Pagination, { Paged } from "../components/Pagination";
import Select from "../components/Select";
import { ArrowsClockwise } from "@phosphor-icons/react";
import BusyButton from "../components/BusyButton";

export default function Reminders() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [meta, setMeta] = useState<Paged<Message> | null>(null);
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState("");
  const [showCompose, setShowCompose] = useState(false);
  const [patientQ, setPatientQ] = useState("");
  const [patients, setPatients] = useState<Patient[]>([]);
  const [patient, setPatient] = useState<Patient | null>(null);
  const [channel, setChannel] = useState("sms");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  function load() {
    api.get<Paged<Message>>(
      `/api/messages/paged?message_type=${typeFilter}&page=${page}&per_page=25`)
      .then((res) => {
        setMessages(res.items);
        setMeta(res);
        if (res.page !== page) setPage(res.page);
      })
      .catch((e) => toast.error(errorText(e)));
  }

  useEffect(load, [typeFilter, page]);

  // Changing the filter changes the set, so the page number no longer means
  // anything — page 40 of the birthdays is not page 40 of everything.
  useEffect(() => { setPage(1); }, [typeFilter]);

  useEffect(() => {
    if (patientQ.length < 2) { setPatients([]); return; }
    api.get<Patient[]>(`/api/patients?q=${encodeURIComponent(patientQ)}&limit=6`).then(setPatients);
  }, [patientQ]);

  async function runJobs() {
    setBusy(true);
    try {
      const res = await api.post<any>("/api/messages/run-jobs");
      toast.ok(`Queued ${res.repeat_reminders_queued} repeat + ${res.birthday_messages_queued} birthday reminders; delivered ${res.messages_sent} message(s).`);
      load();
    } catch (e: any) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!patient) return;
    setBusy(true);
    try {
      await api.post("/api/messages", {
        patient_id: patient.id, channel, subject, body, message_type: "custom",
      });
      setShowCompose(false);
      setPatient(null); setSubject(""); setBody("");
      load();
    } catch (err: any) {
      toast.error(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const badge = (s: string) => (s === "sent" ? "ok" : s === "failed" ? "danger" : "warn");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Patient Adherence</h1>
          <div className="sub">SMS &amp; email for repeat prescriptions, birthdays and free-type messages</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {/* The glyph was a literal ⟳ in the label. It is an icon now, and it
              turns while the jobs are actually running. */}
          <BusyButton className="btn secondary" onClick={runJobs}
                      icon={ArrowsClockwise} busyLabel="Running…">
            Run reminder jobs now
          </BusyButton>
          <button onClick={() => setShowCompose(true)}>+ Compose message</button>
        </div>
      </div>

      <div className="pill-tabs">
        {[["", "All"], ["repeat", "Repeat reminders"], ["birthday", "Birthdays"], ["custom", "Free-type"]].map(([v, l]) => (
          <button key={v} className={typeFilter === v ? "active" : ""} onClick={() => setTypeFilter(v)}>{l}</button>
        ))}
      </div>

      <div className="card">
        <table>
          <thead><tr><th>Patient</th><th>Type</th><th>Channel</th><th>Message</th><th>Status</th><th>When</th></tr></thead>
          <tbody>
            {messages.map((m) => (
              <tr key={m.id}>
                <td><b>{m.patient ? `${m.patient.first_name} ${m.patient.last_name}` : m.patient_id}</b></td>
                <td><span className="badge muted">{m.message_type.replace("_", " ")}</span></td>
                <td>{m.channel.toUpperCase()}</td>
                <td style={{ maxWidth: 420 }}>{m.subject && <b>{m.subject}. </b>}{m.body}</td>
                <td>
                  <span className={`badge ${badge(m.status)}`}>{m.status}</span>
                  {m.detail && <div className="muted" style={{ fontSize: 11 }}>{m.detail}</div>}
                </td>
                <td className="muted">{fmtDateTime(m.sent_at ?? m.scheduled_for)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {meta && <Pagination meta={meta} onPage={setPage} noun="reminders" />}
        {messages.length === 0 && <div className="empty">No messages yet, run the reminder jobs or compose one.</div>}
      </div>

      {showCompose && (
        <div className="modal-backdrop" onClick={() => setShowCompose(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Compose message</h2>
            <form onSubmit={send}>
              <div className="field">
                <label>Patient</label>
                {patient ? (
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <b>{patient.first_name} {patient.last_name}</b>
                    <button type="button" className="ghost small" onClick={() => setPatient(null)}>Change</button>
                  </div>
                ) : (
                  <>
                    <input type="search" placeholder="Search patient…" value={patientQ} onChange={(e) => setPatientQ(e.target.value)} />
                    {patients.map((p) => (
                      <div key={p.id} className="product-pick" onClick={() => { setPatient(p); setPatients([]); setPatientQ(""); }}>
                        <span>{p.last_name}, {p.first_name}</span>
                        <span className="muted">{p.phone || p.email || "no contact"}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
              <div className="form-row">
                <div className="field">
                  <label>Channel</label>
                  <Select
                    value={String(channel ?? "")}
                    onChange={(__value) => setChannel(__value)}
                    options={[{ value: "sms", label: "SMS" }, { value: "email", label: "Email" }]}
                  />
                </div>
                {channel === "email" && (
                  <div className="field"><label>Subject</label><input value={subject} onChange={(e) => setSubject(e.target.value)} /></div>
                )}
              </div>
              <div className="field">
                <label>Message</label>
                <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} required />
              </div>
              <div className="modal-actions">
                <button type="button" className="secondary" onClick={() => setShowCompose(false)}>Cancel</button>
                <button type="submit" disabled={!patient || busy}>{busy ? "Sending…" : "Send now"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
