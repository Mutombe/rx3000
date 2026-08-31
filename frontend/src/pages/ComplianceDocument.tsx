/** One certificate: what it permits, when it lapses, and what it replaced.
 *
 *  THE QUESTION THIS PAGE ANSWERS THAT THE REGISTER DOES NOT
 *
 *  A register answers "are we licensed today". The other question — the one an
 *  inspection actually asks — is **were we licensed in March**. A pharmacy
 *  renews every year, and last year's certificate is the proof it traded
 *  lawfully last year. Nothing here is ever deleted for that reason: a
 *  superseded document keeps its dates, its file and its uploader, and simply
 *  stops being the current one.
 *
 *  So the chain is the point of the page, and it is walked both ways. From a
 *  lapsed number an inspector has read out, you can reach the one that replaced
 *  it without knowing which of eight rows is live.
 *
 *  WHAT IT COSTS AND WHO ISSUES IT
 *
 *  Stated, because a renewal is rarely difficult and is almost always late.
 *  Knowing it is due, who to ask, and what to budget is the whole job — and
 *  every pharmacy currently does it out of a lever-arch file and somebody's
 *  memory.
 */
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowCounterClockwise, CloudArrowUp, DownloadSimple, Warning }
  from "@phosphor-icons/react";
import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import RecordPage, { Fact, Panel } from "../components/RecordPage";
import { useConfirm } from "../components/Confirm";
import { useToast } from "../components/Toast";

interface Row {
  id: number | null;
  reference: string;
  issuer: string;
  issued_on: string | null;
  expires_on: string | null;
  renewal_cost: number;
  has_file: boolean;
  file_name: string;
  notes: string;
  uploaded_by: string;
  uploaded_at: string | null;
  state?: string;
}
interface Doc extends Row {
  kind: string;
  name: string;
  title: string;
  expected_issuer: string;
  renewal_months: number;
  critical: boolean;
  why: string;
  state: string;
  days_left: number | null;
  active: boolean;
  is_current: boolean;
  file_type: string;
  file_bytes: number;
  branch_id: number;
  branch: string;
  branch_code: string;
  replaced: Row[];
  replaced_by: Row | null;
}

/** How each state should read at a glance. `missing` cannot occur here — you
 *  are looking at a document, so one exists. */
const TONE: Record<string, string> = {
  expired: "bad", urgent: "warn", expiring: "warn",
  undated: "warn", valid: "ok",
};
const SAYS: Record<string, string> = {
  expired: "This has lapsed",
  urgent: "Renew this now",
  expiring: "Renewal is due",
  undated: "No expiry recorded",
  valid: "Current",
};

function bytes(n: number): string {
  if (!n) return "";
  return n < 1024 ? `${n} B`
    : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB`
      : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ComplianceDocument() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<Doc | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState("");
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(() => {
    api.get<Doc>(`/api/compliance/documents/${id}`)
      .then((d) => { setDoc(d); setFailed(""); })
      .catch((e) => setFailed(errorText(e, "That document is not on file.")))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(load, [load]);

  /** Fetch the certificate with the session's credentials and open it.
   *
   *  Not an `<a href>`: that cannot carry the Authorization header, and the
   *  usual workaround puts the token in a query string where it lands in every
   *  access log the request passes through — for a file that is, by its
   *  nature, the pharmacy's licence to trade.
   */
  async function openFile() {
    if (!doc?.has_file) return;
    try {
      const file = await api.blob(`/api/compliance/documents/${doc.id}/file`);
      const url = URL.createObjectURL(file.body);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(errorText(e, "That file could not be opened."));
    }
  }

  async function retire() {
    if (!doc) return;
    const ok = await confirm({
      title: `Take ${doc.name} off the register?`,
      body: "It stays on file as proof of the period it covered. A certificate "
          + "that was held is evidence the branch held it, and removing the row "
          + "does not un-hold it — it removes the ability to prove it.",
      confirmLabel: "Take it off",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/compliance/documents/${doc.id}`);
      toast.ok(`${doc.name} is off the register and still on file.`);
      navigate(`/compliance?branch=${doc.branch_id}`);
    } catch (e) {
      toast.error(errorText(e));
    }
  }

  const facts: Fact[] = doc ? [
    { label: "Standing", value: SAYS[doc.state] ?? doc.state,
      tone: TONE[doc.state],
      hint: doc.days_left === null ? undefined
        : doc.days_left < 0 ? `${Math.abs(doc.days_left)} days ago`
          : `${doc.days_left} days left` },
    { label: "Expires", value: doc.expires_on ? fmtDate(doc.expires_on) : "—",
      hint: doc.renewal_months
        ? `renewed every ${doc.renewal_months} months` : undefined },
    { label: "Reference", value: doc.reference || "—" },
    { label: "Renewal", value: doc.renewal_cost ? money(doc.renewal_cost) : "—",
      hint: doc.renewal_cost ? "what it costs to renew" : "no cost recorded" },
  ] : [];

  return (
    <RecordPage
      trail={[{ to: "/branches", label: "Branches" },
              { to: "/compliance", label: "Licences" },
              { label: doc?.name ?? "" }]}
      eyebrow={doc?.critical ? "Licence to trade" : "Permit"}
      title={doc?.name ?? ""}
      subtitle={doc ? (
        <>
          <Link to={`/compliance?branch=${doc.branch_id}`}>{doc.branch}</Link>
          <span className="muted"> · {doc.branch_code}</span>
          {doc.issuer && <> · issued by {doc.issuer}</>}
        </>
      ) : undefined}
      facts={facts}
      loading={loading}
      error={failed}
      actions={doc ? (
        <>
          {doc.has_file && (
            <button className="btn secondary" onClick={openFile}>
              <DownloadSimple size={15} /> Open the certificate
            </button>
          )}
          {/* Renewing is recording the new one, not editing this one. Editing
              an expiry in place would overwrite the proof of what was held
              before it — which is the one thing this register exists to keep. */}
          <Link className="btn primary"
                to={`/compliance?branch=${doc.branch_id}&renew=${doc.kind}`}>
            <CloudArrowUp size={15} /> Record a renewal
          </Link>
          {doc.active && (
            <button className="btn ghost" onClick={retire}>
              Take off the register
            </button>
          )}
        </>
      ) : undefined}
    >
      {doc && (
        <>
          {/* A document opened from an old link, when a newer one exists.
              Said before anything else on the page: somebody reading an expiry
              here and acting on it would be acting on last year's. */}
          {doc.replaced_by && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                <b>This is not the current {doc.name}.</b> It was replaced by{" "}
                <Link to={`/compliance/documents/${doc.replaced_by.id}`}>
                  {doc.replaced_by.reference || "a later certificate"}
                </Link>
                {doc.replaced_by.expires_on && <>, which expires {fmtDate(doc.replaced_by.expires_on)}</>}.
                It is kept because it is the proof the branch was licensed for
                the period it covered.
              </span>
            </div>
          )}

          {doc.state === "expired" && doc.critical && !doc.replaced_by && (
            <div className="alert error">
              <Warning size={16} weight="fill" />
              <span>
                <b>This has lapsed and nothing has replaced it.</b> {doc.why}
              </span>
            </div>
          )}

          {!doc.has_file && (
            <div className="alert warn">
              <Warning size={16} weight="fill" />
              <span>
                <b>The certificate itself is not on file.</b> The dates here are
                a claim; an inspector asks to see the licence. Record a renewal
                with the scan attached, or add the file to this one.
              </span>
            </div>
          )}

          <div className="grid cols-2">
            <Panel title="What this permits">
              <p className="prose">{doc.why}</p>
              <dl className="kv">
                <dt>Issued by</dt>
                <dd>
                  {doc.issuer || <span className="muted">not recorded</span>}
                  {doc.expected_issuer && doc.issuer
                    && doc.issuer !== doc.expected_issuer && (
                    <div className="muted small">
                      usually {doc.expected_issuer}
                    </div>
                  )}
                </dd>
                <dt>Issued on</dt>
                <dd>{doc.issued_on ? fmtDate(doc.issued_on)
                  : <span className="muted">not recorded</span>}</dd>
                <dt>Expires</dt>
                <dd>
                  {doc.expires_on ? fmtDate(doc.expires_on)
                    : <span className="muted">does not expire</span>}
                </dd>
                <dt>Renewal cost</dt>
                <dd>{doc.renewal_cost ? money(doc.renewal_cost)
                  : <span className="muted">not recorded</span>}</dd>
              </dl>
            </Panel>

            <Panel title="The document">
              <dl className="kv">
                <dt>File</dt>
                <dd>
                  {doc.has_file ? (
                    <>
                      <button className="linkish" onClick={openFile}>
                        {doc.file_name || "the certificate"}
                      </button>
                      <div className="muted small">
                        {doc.file_type}{doc.file_bytes ? ` · ${bytes(doc.file_bytes)}` : ""}
                      </div>
                    </>
                  ) : <span className="cu-diff">nothing attached</span>}
                </dd>
                <dt>Recorded by</dt>
                <dd>
                  {doc.uploaded_by || <span className="muted">—</span>}
                  {doc.uploaded_at && (
                    <div className="muted small">{fmtDateTime(doc.uploaded_at)}</div>
                  )}
                </dd>
                <dt>On the register</dt>
                <dd>
                  {doc.is_current
                    ? <span className="badge ok">the current one</span>
                    : doc.active
                      ? <span className="badge muted">held, superseded</span>
                      : <span className="badge muted">taken off</span>}
                </dd>
              </dl>
              {doc.notes.trim() && <p className="prose">{doc.notes.trim()}</p>}
            </Panel>
          </div>

          {/* The chain. This is what makes the page worth opening — the
              register can say what is current, and only this can say what was
              current in March. */}
          <Panel title="What this replaced" count={doc.replaced.length}
                 empty="Nothing — this is the first of its kind on file for this branch.">
            <table className="dt">
              <thead>
                <tr>
                  <th>Reference</th><th>Issued</th><th>Expired</th>
                  <th>Recorded by</th><th className="num">Cost</th><th />
                </tr>
              </thead>
              <tbody>
                {doc.replaced.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.reference || "—"}</td>
                    <td>{r.issued_on ? fmtDate(r.issued_on) : "—"}</td>
                    <td>{r.expires_on ? fmtDate(r.expires_on) : "—"}</td>
                    <td className="muted">{r.uploaded_by || "—"}</td>
                    <td className="num">{r.renewal_cost ? money(r.renewal_cost) : "—"}</td>
                    <td>
                      <Link to={`/compliance/documents/${r.id}`}
                            className="muted small">
                        <ArrowCounterClockwise size={12} /> open it
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </RecordPage>
  );
}
