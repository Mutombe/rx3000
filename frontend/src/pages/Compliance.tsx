/** The licences and certificates a branch trades on.
 *
 *  A pharmacy in Zimbabwe trades on a stack of paper that all expires: the MCAZ
 *  premises licence, the responsible pharmacist's practice certificate, the
 *  city health licence, fire brigade clearance, the ZIMRA tax clearance, the
 *  dangerous drugs permit. Every one has its own issuer and its own renewal
 *  month, and for three of them the consequence of lapsing is that the shop
 *  closes.
 *
 *  This is managed everywhere in a lever-arch file and somebody's diary, and it
 *  fails the same way every time: nobody notices a certificate has expired
 *  until an inspector does. The renewal is rarely difficult — knowing it is due
 *  is the whole problem.
 *
 *  **The missing rows are the point.** A register of what has been uploaded
 *  cannot say what has not, and a branch with four current certificates and no
 *  fire clearance at all looks perfectly healthy as four green rows. So every
 *  branch is measured against what a pharmacy is expected to hold, and a
 *  document nobody has entered appears in the same table with the same weight
 *  as one that has expired.
 *
 *  Lapsed and never-entered are still shown apart, because they are different
 *  findings. An expired critical licence means the branch is trading on
 *  something that ran out. A missing one means nobody has scanned it yet —
 *  which is the state every branch is in on the day this is switched on, and
 *  telling a fifteen-year-old pharmacy it "cannot lawfully open" for that
 *  reason is how the whole screen gets disbelieved.
 */
import { useCallback, useEffect, useState } from "react";
import { CloudArrowUp, FileText, Warning } from "@phosphor-icons/react";
import { api, errorText, fmtDate, money , sentence} from "../api";
import BusyButton from "../components/BusyButton";
import Select from "../components/Select";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useOptimisticList, rowClass } from "../hooks/useOptimisticList";
import { useConfirm } from "../components/Confirm";
import { Link, useSearchParams } from "react-router-dom";
import SectionNav from "../components/SectionNav";
import { BRANCH_TABS } from "../branchTabs";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import Th from "../components/Th";

interface Doc {
  id: number | null; kind: string; name: string; expected_issuer: string;
  renewal_months: number; critical: boolean; why: string;
  state: string; days_left: number | null;
  reference: string; issuer: string;
  issued_on: string | null; expires_on: string | null;
  renewal_cost: number; has_file: boolean; file_name: string;
  notes: string; uploaded_by: string; uploaded_at: string | null;
}
interface Register {
  branch_id: number; branch: string; code: string;
  documents: Doc[]; history: Doc[];
  counts: Record<string, number>; verdict: string; says: string;
  blocking: string[]; at_risk: string[]; renewal_cost_year: number;
}
interface Overview {
  branches: { branch_id: number; branch: string; code: string;
              verdict: string; says: string; expired: number; missing: number;
              urgent: number; renewal_cost_year: number;
              next: { name: string; days: number; on: string } | null }[];
  cannot_trade: string[]; cannot_be_proved: string[];
  expired: number; missing: number; urgent: number;
  renewal_cost_year: number; headline: string;
}
interface Kind {
  kind: string; name: string; issuer: string;
  renewal_months: number; critical: boolean; why: string;
}

/** How each state reads. Only two are loud, and they are the two that mean
 *  somebody has to do something rather than know something. */
const TONE: Record<string, string> = {
  expired: "bad", missing: "warn", urgent: "warn",
  expiring: "muted", undated: "muted", valid: "ok",
};
const SAYS: Record<string, string> = {
  expired: "expired", missing: "Nothing on file", urgent: "Renew now",
  expiring: "Renewal due", undated: "No expiry", valid: "current",
};
/** Keyed on what the SERVER sends, so these stay in its spelling. */
const VERDICT: Record<string, string> = {
  "cannot trade": "bad", "cannot be proved": "warn", expired: "bad",
  gaps: "warn", "renew now": "warn", "renewals due": "muted",
  "in order": "ok",
};

export default function Compliance() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [kinds, setKinds] = useState<Kind[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [register, setRegister] = useState<Register | null>(null);
  const [adding, setAdding] = useState<Doc | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<Overview>("/api/compliance/overview"),
      api.get<Kind[]>("/api/compliance/kinds"),
    ])
      .then(([o, k]) => { setOverview(o); setKinds(k); })
      .catch((e) => toast.error(errorText(e)))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  /* One row per kind of document, which is what the register is.
   *
   * `register` keeps the verdict, the history and the renewal costs; the hook
   * keeps the rows, because those are the only part that changes when somebody
   * files a certificate. */
  const docs = useOptimisticList<Doc>({
    enabled: open != null,
    load: async () => {
      if (open == null) return [];
      const r = await api.get<Register>(`/api/compliance/branches/${open}`);
      setRegister(r);
      return r.documents ?? [];
    },
    key: (d) => d.kind,
  });

  const openBranch = useCallback((id: number) => {
    setOpen(id);
    setRegister(null);
  }, []);

  useEffect(() => {
    if (open != null) docs.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  /** Arrive on one branch's register from its row on the Branches table.
   *
   *  The link carries the branch, so a manager who clicked "cannot trade" on
   *  the shop list lands on the certificates that say why rather than on a
   *  summary of all six shops with theirs somewhere in it.
   */
  const [params, setParams] = useSearchParams();
  const wanted = Number(params.get("branch") || 0);
  useEffect(() => {
    if (wanted) openBranch(wanted);
    // Read once and cleared, so refreshing the page later does not silently
    // reopen a branch somebody has since closed.
    if (wanted) { params.delete("branch"); setParams(params, { replace: true }); }
  }, [wanted]);

  /** `?renew=<kind>` opens the upload already knowing what is being renewed.
   *
   *  A renewal is recorded as a new document rather than by editing the old
   *  one — editing an expiry in place overwrites the proof of what was held
   *  before it, which is the one thing this register exists to keep. So the
   *  button on a certificate's own page arrives here with the kind in hand.
   */
  const renewing = params.get("renew") || "";
  useEffect(() => {
    if (!renewing || !register) return;
    const row = register.documents.find((d) => d.kind === renewing);
    if (row) setAdding({ ...row, id: null });
    params.delete("renew");
    setParams(params, { replace: true });
  }, [renewing, register]);

  /** Open a certificate with the session's credentials attached. */
  async function openFile(doc: Doc) {
    if (!doc.id) return;
    try {
      const file = await api.blob(`/api/compliance/documents/${doc.id}/file`);
      const url = URL.createObjectURL(file.body);
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(errorText(e, "That certificate could not be opened."));
    }
  }

  async function remove(doc: Doc) {
    if (!doc.id) return;
    const ok = await confirm({
      title: `Take ${doc.name} off the register?`,
      body: "It stays on file as proof of the period it covered. A certificate "
          + "that was held is evidence the branch held it, and removing the row "
          + "does not un-hold it. It removes the ability to prove it.",
      confirmLabel: "Take it off",
      destructive: true,
    });
    if (!ok) return;
    // Off the register on the click, back in its old place with the reason if
    // the server refuses. The row already carries a pending state for exactly
    // this; it was waiting on the request and then reloading the branch and
    // the overview, so a register of fifteen documents blinked twice before
    // anything looked different.
    await docs.remove(doc.kind,
      () => api.delete(`/api/compliance/documents/${doc.id}`),
      "Off the register.");
    load();
  }

  return (
    <div className="page">
      <PageHead
        title="Licences and compliance"
        sub={overview?.headline
          ?? "What each branch must hold to trade, and when it expires."}
        count={overview && (overview.expired || overview.missing)
          ? `${overview.expired + overview.missing} need attention`
          : undefined}
        /* WHAT AN INSPECTION ACTUALLY ASKS FOR.
           Not a screen: a list of what each branch holds, its reference, who
           issued it and when it runs out. It is also what an insurer wants
           annually, and what a pharmacy renewing twelve licences works from. */
        take={<ExportButton dataset="compliance" />}
      />

      {/* The family this page belongs to. It used to sit in the
          page's action slot beside a primary button, and on Authorisations
          beside a search box as well, so three different kinds of control
          shared one corner and wrapped the header to 176px against 76 on an
          ordinary page. Navigation is not an action. */}
      <SectionNav tabs={BRANCH_TABS} end="/compliance" />

      <Refreshable loading={loading} hasData={!!overview}
        skeleton={<TableSkeleton cols={5} rows={4} />}>
        {overview && (
          <>
            {overview.cannot_trade.length > 0 && (
              <div className="alert error">
                <Warning size={16} weight="fill" />{" "}
                <b>{overview.cannot_trade.join(", ")}</b>. A licence the shop
                cannot trade without has expired. This is today's job, not this
                month's.
              </div>
            )}

            <div className="wc-bands">
              <div className={`wl-stat${overview.expired ? " wc-abandoned" : ""}`}>
                <b className={overview.expired ? "tone-danger" : undefined}>
                  {overview.expired}
                </b>
                <span>Expired</span>
              </div>
              <div className="wl-stat">
                <b>{overview.urgent}</b><span>Due within three weeks</span>
              </div>
              <div className={`wl-stat${overview.missing ? " wc-stale" : ""}`}>
                <b>{overview.missing}</b>
                {/* Not "non-compliant". Nothing on file means nobody has
                    scanned it, which is a different fact from not holding it. */}
                <span>nothing on file</span>
              </div>
              <div className="wl-stat">
                <b>{money(overview.renewal_cost_year)}</b>
                <span>A year in renewals</span>
              </div>
            </div>

            <div className="dt-scroll">
              <table className="dt dt-wide">
                <thead>
                  <tr>
                    <Th>Branch</Th><Th>Standing</Th>
                    <Th className="num">Expired</Th>
                    <Th className="num">Not on file</Th>
                    <Th>Next renewal</Th>
                    <Th className="num">Renewals a year</Th>
                  </tr>
                </thead>
                <tbody>
                  {overview.branches.map((b) => (
                    // A plain row, not a RowLink: this opens the branch's
                    // register below rather than navigating, so somebody
                    // checking four shops before an inspection keeps the
                    // comparison in front of them.
                    <tr key={b.branch_id}
                      onClick={() => openBranch(b.branch_id)}
                      style={{ cursor: "pointer" }}
                      className={b.verdict === "cannot trade" ? "row-danger"
                        : b.expired || b.urgent ? "row-flag" : undefined}>
                      <td className="br-name">
                        <b>{b.branch}</b>
                        <div className="muted small mono">{b.code}</div>
                      </td>
                      <td>
                        {/* The verdict, and the reason on one line. The whole
                            sentence was folded into this cell, in a column
                            narrow enough to break it after two words: seven
                            lines of wrapped prose per row, which made a table
                            of four branches taller than the screen and told
                            nobody anything faster. It is on the hover, and in
                            full on the branch itself. */}
                        {/* The badge, and nothing under it. Clamping the
                            sentence to two lines still left every row three
                            lines tall for prose that is word for word the same
                            on each branch, and the two columns beside it carry
                            the facts it was restating. On the hover, and in
                            full on the branch. */}
                        <span className={`badge ${VERDICT[b.verdict] ?? "muted"}`}
                              title={b.says}>
                          {sentence(b.verdict)}
                        </span>
                      </td>
                      <td className="num">
                        {b.expired || <span className="muted">None</span>}
                      </td>
                      <td className="num">
                        {b.missing || <span className="muted">None</span>}
                      </td>
                      <td>
                        {b.next
                          ? <>{b.next.name}
                              <div className="muted small">
                                in {b.next.days} days
                              </div></>
                          : <span className="muted">Nothing dated</span>}
                      </td>
                      <td className="num mono">{money(b.renewal_cost_year)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Refreshable>

      {/* The branch's own register, opened in place rather than on its own
          route: somebody checking four shops before an inspection is comparing
          them, and a page change per branch loses the comparison. */}
      {open && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>{register?.branch ?? "Loading…"}</h3>
              {register && (
                <span className="muted small">{register.says}</span>
              )}
            </div>
            <div className="page-actions">
              <BusyButton className="btn primary" icon={CloudArrowUp}
                onClick={() => setAdding({
                  ...(register?.documents.find((d) => d.state === "missing"
                                                     && d.critical)
                      ?? register?.documents[0]
                      ?? ({} as Doc)),
                  id: null,
                })}
                busyLabel="">
                Record a document
              </BusyButton>
              <button className="btn ghost" onClick={() => { setOpen(null); setRegister(null); }}>
                Close
              </button>
            </div>
          </div>

          {!register ? <TableSkeleton cols={5} rows={6} /> : (
            <div className="dt-scroll">
              <table className="dt dt-wide">
                <thead>
                  <tr>
                    <Th>Document</Th><Th>Standing</Th><Th>Reference</Th>
                    <Th>Expires</Th><Th>Scan</Th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {docs.items.map((d) => (
                    <tr key={d.kind}
                        className={[
                          d.state === "expired" ? "row-danger"
                            : d.state === "missing" && d.critical ? "row-flag" : "",
                          rowClass(docs.stateOf(d)),
                        ].filter(Boolean).join(" ") || undefined}>
                      {/* ONE LINE PER DOCUMENT.
                          This cell stacked four things: the name, a five word
                          badge, a wrapped sentence of regulation and the
                          issuer. Fifteen documents at four lines each is a
                          register nobody can scan, and the sentence was the
                          same on every branch's copy of the same row.

                          The name and the issuer read across; the reason is on
                          hover and on the record behind the name, which is
                          where somebody goes when they want to know why the
                          licence exists rather than whether it is current. */}
                      <td title={d.why}>
                        {/* The name gets the column to itself.
                            The critical badge sat beside it as a flex sibling
                            that would not shrink, so on a real register the
                            names read "MCA...", "Resp...", "Dang..." and the
                            one thing somebody scans the column for was the
                            part that had been cut. It is a fact about
                            STANDING, so it now sits with the standing. */}
                        <span className="cl-doc">
                          {d.critical && (
                            <span className="cl-dot" aria-hidden="true"
                                  title="The shop cannot trade without this one" />
                          )}
                          {d.id
                            ? <Link to={`/compliance/documents/${d.id}`}><b>{d.name}</b></Link>
                            : <b>{d.name}</b>}
                        </span>
                        <span className="muted small cl-issuer">
                          {d.critical && (
                            <span className="sr-only">
                              The shop cannot trade without this one.{" "}
                            </span>
                          )}
                          {d.issuer || d.expected_issuer}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${TONE[d.state] ?? "muted"}`}>
                          {SAYS[d.state] ?? d.state}
                        </span>

                        {d.days_left !== null && (
                          <span className="muted small cl-days">
                            {d.days_left < 0
                              ? `${Math.abs(d.days_left)} days ago`
                              : `in ${d.days_left} days`}
                          </span>
                        )}
                      </td>
                      {/* THREE COLUMNS THAT ALL SAID "none".
                          One word repeated across a row says only that the
                          row is empty; each of these is a different job
                          somebody has not done, and naming the job is what
                          turns the register into a list of things to do. */}
                      <td className="mono small">
                        {d.reference
                          || <span className="muted">No number</span>}
                      </td>
                      <td>
                        {d.expires_on ? fmtDate(d.expires_on)
                          : <span className="muted">No expiry</span>}
                      </td>
                      <td>
                        {d.has_file ? (
                          // The certificate itself. A date without the document
                          // behind it is a claim, and an inspector asks to see
                          // the licence rather than a system that says there
                          // is one.
                          //
                          // Fetched, not linked. This was an `<a href>` at the
                          // API path, which cannot carry the session's
                          // Authorization header, so every attempt to open a
                          // licence from this register was refused, on the one
                          // screen whose entire purpose is producing the
                          // document when somebody asks for it.
                          <button className="linkish"
                                  onClick={() => openFile(d)}>
                            <FileText size={13} /> {d.file_name || "open"}
                          </button>
                        ) : d.id ? (
                          <span className="muted small">Not scanned</span>
                        ) : <span className="muted">Not scanned</span>}
                      </td>
                      <td className="actions">
                        <button className="btn ghost sm"
                          onClick={() => setAdding({ ...d, id: null })}>
                          {d.id ? "Renew" : "Record it"}
                        </button>
                        {d.id && (
                          <button className="btn ghost sm" onClick={() => remove(d)}>
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {register && register.history.length > 0 && (
            <>
              <h4 className="cu-section">Superseded</h4>
              <p className="muted small">
                Kept, never deleted. Last year's certificate is the proof the
                branch was licensed last year, which is what an audit asks
                about.
              </p>
              <div className="dt-scroll">
                <table className="dt dt-wide">
                  <thead>
                    <tr><Th>Document</Th><Th>Reference</Th><Th>Expired</Th>
                      <Th>Scan</Th></tr>
                  </thead>
                  <tbody>
                    {register.history.map((d) => (
                      <tr key={d.id} className="row-muted">
                        <td>
                          {/* Superseded, and still the proof the branch was
                              licensed for the period it covered, which is
                              what an audit asks about. */}
                          <Link to={`/compliance/documents/${d.id}`}>{d.name}</Link>
                        </td>
                        <td className="mono small">{d.reference || "none"}</td>
                        <td>{d.expires_on ? fmtDate(d.expires_on) : "No date"}</td>
                        <td>
                          {d.has_file && (
                            <button className="linkish" onClick={() => openFile(d)}>
                              open
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {adding && open && (
        <RecordDocument
          branchId={open}
          kinds={kinds}
          starting={adding}
          onClose={() => setAdding(null)}
          onSubmit={async (kind, body, says) => {
            // Closed here, and the row for that kind stops saying "missing"
            // before the upload finishes. The form knows what was typed; only
            // the list can show it in place and put the old state back.
            setAdding(null);
            const ok = await docs.update(
              kind, { state: "current" } as Partial<Doc>,
              () => api.post(
                `/api/compliance/branches/${open}/documents`, body),
              says);
            // The verdict at the top of the page — can this branch trade —
            // is the server's and is re-read either way.
            if (ok) load();
            // Reopened on the same row's document, which is what `adding`
            // holds — the kind alone is not enough to reopen the form.
            else setAdding(docs.items.find((d) => d.kind === kind) ?? null);
          }}
        />
      )}
    </div>
  );
}

/** Recording one, with the scan where there is one.
 *
 *  The file is optional and the date is not. A pharmacy that knows its licence
 *  runs out in March and has not scanned it yet is better served by entering
 *  the date now — the date is what produces the reminder, and a register
 *  nobody can enter anything into stays empty.
 */
function RecordDocument({ branchId, kinds, starting, onClose, onSubmit }: {
  branchId: number; kinds: Kind[]; starting: Doc;
  onClose: () => void;
  /** Hands the kind and the multipart body to whoever owns the register. */
  onSubmit: (kind: string, body: FormData, says: string) => void | Promise<void>;
}) {
  const [kind, setKind] = useState(starting.kind || kinds[0]?.kind || "");
  const [reference, setReference] = useState("");
  const [issuer, setIssuer] = useState(starting.expected_issuer || "");
  const [issued, setIssued] = useState("");
  const [expires, setExpires] = useState("");
  const [cost, setCost] = useState(String(starting.renewal_cost || ""));
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const toast = useToast();

  const chosen = kinds.find((k) => k.kind === kind);

  // The usual renewal, offered rather than imposed: a pharmacy whose licence
  // runs to a different month types the real date, and a typed date always
  // wins because this only fills a blank field.
  function onIssued(value: string) {
    setIssued(value);
    if (!value || expires || !chosen?.renewal_months) return;
    const d = new Date(value);
    d.setMonth(d.getMonth() + chosen.renewal_months);
    setExpires(d.toISOString().slice(0, 10));
  }

  async function save() {
    const body = new FormData();
    body.append("kind", kind);
    body.append("reference", reference);
    body.append("issuer", issuer);
    body.append("issued_on", issued);
    body.append("expires_on", expires);
    body.append("renewal_cost", String(Number(cost) || 0));
    body.append("notes", notes);
    if (file) body.append("file", file);
    // `api.post` passes a FormData through untouched and leaves the browser to
    // set the multipart boundary, which is the one header that must not be set
    // by hand. That call happens where the list is, one level up.
    await onSubmit(kind, body, `${chosen?.name ?? kind} recorded.`);
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <h2>Record a document</h2>
        {chosen && <p className="muted">{chosen.why}</p>}

        <div className="form-row">
          <div className="field span-6">
            <label>Which document</label>
            <Select value={kind} onChange={(v) => {
              setKind(v);
              const k = kinds.find((x) => x.kind === v);
              if (k && !issuer) setIssuer(k.issuer);
            }} options={kinds.map((k) => ({
              value: k.kind,
              label: k.critical ? `${k.name}. The shop closes without it` : k.name,
            }))} />
          </div>
          <div className="field span-6">
            <label>Reference / certificate number</label>
            <input value={reference} maxLength={80}
              onChange={(e) => setReference(e.target.value)}
              placeholder="MCAZ/2026/0117" />
            <span className="hint">
              What a wholesaler or an inspector asks for.
            </span>
          </div>
          <div className="field span-6">
            <label>Issued by</label>
            <input value={issuer} maxLength={120}
              onChange={(e) => setIssuer(e.target.value)} />
          </div>
          <div className="field span-3">
            <label>Issued on</label>
            <input type="date" value={issued}
              onChange={(e) => onIssued(e.target.value)} />
          </div>
          <div className="field span-3">
            <label>Expires</label>
            <input type="date" value={expires}
              onChange={(e) => setExpires(e.target.value)} />
            <span className="hint">
              {chosen?.renewal_months
                ? `Usually ${chosen.renewal_months} months. Filled in from the `
                  + "issue date; type over it if yours differs."
                : "Leave blank if it does not expire."}
            </span>
          </div>
          <div className="field span-3">
            <label>Renewal cost <span className="muted">optional</span></label>
            <input type="number" step="0.01" value={cost}
              onChange={(e) => setCost(e.target.value)} placeholder="0.00" />
            <span className="hint">
              So a year of compliance can be budgeted rather than met a
              certificate at a time.
            </span>
          </div>
          <div className="field span-9">
            <label>The scan <span className="muted">optional</span></label>
            <input type="file" accept=".pdf,image/*"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <span className="hint">
              A PDF or a photograph. The date on its own already produces the
              reminder: the scan is what you show an inspector.
            </span>
          </div>
          <div className="field span-12">
            <label>Notes <span className="muted">optional</span></label>
            <input value={notes} maxLength={400}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Renewal needs an inspection booked six weeks ahead" />
          </div>
        </div>

        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={save}
            disabled={!kind} busyLabel="Recording…">
            Record it
          </BusyButton>
        </div>
      </div>
    </div>
  );
}
