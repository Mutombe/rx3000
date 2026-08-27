/** A prescriber, and the scripts they have sent in.
 *
 *  Doctors' names appear on every script and none of them opened. What a
 *  pharmacy wants to know about a prescriber it deals with often is what they
 *  write, so their habits are here alongside the list — a surgery that sends
 *  the same three medicines every week is a stock decision, not just a name.
 */
import { useEffect, useState } from "react";
import { api, errorText, fmtDate } from "../api";
import { EntityLink } from "../components/Filters";
import RecordPage, { Panel } from "../components/RecordPage";
import { useParams } from "react-router-dom";

interface Script {
  id: number; rx_number: string | null; status: string;
  date_prescribed: string; created_at: string;
  patient: { id: number | null; name: string };
}
interface Data {
  id: number; name: string; practice_number: string; phone: string;
  email: string; speciality: string; script_count: number;
  prescriptions: Script[];
  most_prescribed: { product_id: number; product: string; times: number }[];
}

export default function PrescriberDetail() {
  const { id } = useParams();
  const [d, setD] = useState<Data | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    api.get<Data>(`/api/doctors/${id}`)
      .then(setD)
      .catch((e) => setError(errorText(e, "That prescriber could not be opened.")));
  }, [id]);

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Control Panel", to: "/admin" },
              { label: d?.name ?? "This prescriber" }]}
      eyebrow="Prescriber"
      title={d?.name ?? ""}
      subtitle={d && [d.speciality, d.practice_number, d.phone]
        .filter(Boolean).join(" · ")}
      loading={!d && !error}
      error={error}
      facts={d ? [
        { label: "Scripts sent in", value: d.script_count },
        { label: "Practice number",
          value: <span className="mono">{d.practice_number || "—"}</span> },
        { label: "Telephone", value: d.phone || "—" },
        { label: "Email", value: d.email || "—" },
      ] : undefined}
    >
      {d && (
        <>
          <Panel title="What they prescribe most" count={d.most_prescribed.length}
                 empty="No script from this prescriber has been captured.">
            <table className="dt">
              <thead><tr><th>Medicine</th><th className="num">Times</th></tr></thead>
              <tbody>
                {d.most_prescribed.map((m) => (
                  <tr key={m.product_id}>
                    <td>
                      <EntityLink kind="product" id={m.product_id}>{m.product}</EntityLink>
                    </td>
                    <td className="num">{m.times}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Scripts" count={d.prescriptions.length}
                 empty="Nothing has come in from this prescriber."
                 aside={d.script_count > d.prescriptions.length
                   ? <span className="muted small">
                       showing the most recent {d.prescriptions.length} of {d.script_count}
                     </span>
                   : undefined}>
            <div className="dt-scroll" style={{ maxHeight: "50vh" }}>
              <table className="dt">
                <thead>
                  <tr><th>Script</th><th>Patient</th><th>Written</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {d.prescriptions.map((p) => (
                    <tr key={p.id}>
                      <td className="mono">
                        <EntityLink kind="prescription" id={p.id}>
                          {p.rx_number || `#${p.id}`}
                        </EntityLink>
                      </td>
                      <td>
                        <EntityLink kind="patient" id={p.patient.id}>
                          {p.patient.name}
                        </EntityLink>
                      </td>
                      <td>{fmtDate(p.date_prescribed)}</td>
                      <td><span className="badge">{p.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
