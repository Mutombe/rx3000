import RecordPage from "../components/RecordPage";
/** One shop: who is accountable for it, what it may trade on, what is on its
 *  shelves.
 *
 *  Neither of the two screens that list branches could be opened. The branch
 *  table offered a row of actions and no way through to the shop itself, and
 *  the compliance table answered "can this branch prove it may trade" with a
 *  seven line paragraph folded into a table cell, in a column narrow enough to
 *  break it after two words. Both were lists of things nobody could look at.
 *
 *  The two questions belong together, which is why this is one page rather
 *  than two. A branch's licences are not a separate subject from the branch:
 *  the premises licence IS the permission for that address to trade, and the
 *  responsible pharmacist named on the branch record is the person whose
 *  practising certificate has to be on file. Reading them on separate screens
 *  is what lets a shop hold a lapsed certificate for a pharmacist who left.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Buildings, Warning, CheckCircle, FileText, Package }
  from "@phosphor-icons/react";

import { api, errorText, fmtDate, fmtDateTime, money } from "../api";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { EntityLink } from "../components/Filters";
import Th from "../components/Th";

interface Branch {
  id: number; code: string; name: string; registration_no: string;
  phone: string; email: string; address: string; city: string;
  responsible_pharmacist: string; is_default: boolean; active: boolean;
  latitude: number | null; longitude: number | null;
  created_at: string | null;
  frozen: boolean; frozen_at: string | null; frozen_reason: string;
}

/** One document a branch is expected to hold, whether or not it does.
 *
 *  The register returns the whole expected set, so a row with a null `id` is
 *  not a missing record, it is a licence nobody has filed. That is the point
 *  of the screen, so those rows are shown rather than filtered away. */
interface Doc {
  kind: string;
  name: string;
  why: string;
  critical: boolean;
  expected_issuer: string;
  state: string;                 // held | expiring | expired | missing
  days_left: number | null;
  id: number | null;
  reference: string;
  issuer: string;
  issued_on: string | null;
  expires_on: string | null;
  renewal_cost: number;
  has_file: boolean;
  notes: string;
}

interface Register {
  branch_id: number; branch: string; code: string;
  documents: Doc[];
  counts: Record<string, number>;
  verdict: string;
  says: string;
  blocking: string[];
}

interface ShelfLine {
  product_id: number; name: string; here: number;
  group_total: number; reorder_level: number; below_reorder: boolean;
  /** Whether this shop has set its own reorder level, or is using the
   *  group's. Shown, because two branches reading different levels for the
   *  same medicine looks like a fault until you know it was a decision. */
  own_level?: boolean;
  group_level?: number;
}
interface Shelf { branch_id: number; lines: ShelfLine[]; below_reorder: number }

/** What a licence's standing is called, in the words an inspector would use.
 *
 *  "Nothing on file" is deliberately not softened to "pending". The branch may
 *  well hold the certificate in a folder somewhere; what is true, and what
 *  matters when somebody walks in asking, is that nobody here can produce it.
 */
function standing(d: Doc): { label: string; tone: string } {
  const days = d.days_left;
  if (!d.id) {
    return { label: "Nothing on file", tone: d.critical ? "danger" : "warn" };
  }
  if (days === null || days === undefined) {
    return { label: d.expires_on ? "On file" : "On file, no expiry", tone: "ok" };
  }
  if (days < 0) return { label: `Expired ${Math.abs(days)} days ago`, tone: "danger" };
  if (days <= 21) return { label: `${days} days left`, tone: "warn" };
  return { label: `Renews ${fmtDate(d.expires_on)}`, tone: "ok" };
}

export default function BranchDetail() {
  const { id } = useParams();
  const toast = useToast();
  /** Which line is being written, so its box holds still while it saves. */
  const [savingLevel, setSavingLevel] = useState<number | null>(null);

  /** Set or clear what THIS branch reorders a line at.
   *
   *  Null clears the override. The server says which way it went, and its
   *  sentence is shown rather than a made-up one, because "back to the
   *  group's figures" and "keeps its own" are different facts.
   */
  async function setLevel(productId: number, value: number | null) {
    setSavingLevel(productId);
    try {
      const said = await api.put<{ message: string }>(
        `/api/branches/${id}/levels/${productId}`, { reorder_level: value });
      toast.ok(said.message);
      await load();
    } catch (e) {
      toast.error(errorText(e, "That level could not be set."));
    } finally {
      setSavingLevel(null);
    }
  }
  const [branch, setBranch] = useState<Branch | null>(null);
  const [register, setRegister] = useState<Register | null>(null);
  const [shelf, setShelf] = useState<Shelf | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get<Branch>(`/api/branches/${id}`),
      // The licences are the other half of the same question, so they are
      // fetched with the branch rather than behind another click.
      api.get<Register>(`/api/compliance/branches/${id}`).catch(() => null),
      api.get<Shelf>(`/api/branches/${id}/stock`).catch(() => null),
    ])
      .then(([b, r, s]) => { setBranch(b); setRegister(r); setShelf(s); })
      .catch((e) => setError(errorText(e, "That branch could not be opened.")))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(load, [load]);

  if (error) return <div className="alert error">{error}</div>;

  const docs = register?.documents ?? [];
  const lines = shelf?.lines ?? [];
  const missing = register?.blocking ?? [];

  return (
    <RecordPage
      trail={[{ label: "Dashboard", to: "/" },
              { label: "Branches", to: "/branches" },
              { label: branch?.name ?? "Branch" }]}
      eyebrow="Branch"
      title={
        <>
          {branch?.name ?? "Branch"}
          {branch?.is_default && <span className="badge ok bd-tag">Default</span>}
          {branch && !branch.active && <span className="badge muted bd-tag">Closed</span>}
          {branch?.frozen && <span className="badge danger bd-tag">Frozen</span>}
        </>
      }
      meta={[
        ...(branch?.code
          ? [{ label: "Code", value: branch.code, mono: true }] : []),
        ...(branch?.city ? [{ label: "Town", value: branch.city }] : []),
      ]}
      actions={
        <Link className="btn secondary" to={`/branches/${id}/performance`}>
          Performance
        </Link>
      }
    >

      {/* A frozen or closed shop explains itself here rather than leaving a
          badge to be interpreted. */}
      {branch?.frozen && (
        <div className="alert error bd-why">
          <Warning size={15} weight="fill" />
          <span>
            Trading is stopped at this branch
            {branch.frozen_at ? ` since ${fmtDateTime(branch.frozen_at)}` : ""}.
            {branch.frozen_reason ? ` ${branch.frozen_reason}` : ""}
          </span>
        </div>
      )}

      <div className="bd-grid">
        {/* ---- who and where ---- */}
        <section className="card bd-facts">
          <h3><Buildings size={15} /> The shop</h3>
          <dl className="bd-dl">
            <dt>Responsible pharmacist</dt>
            <dd>{branch?.responsible_pharmacist
              || <span className="muted">Nobody named, and an inspector asks for one</span>}</dd>

            <dt>Registration</dt>
            <dd className="mono">{branch?.registration_no || <span className="muted">Not recorded</span>}</dd>

            <dt>Address</dt>
            <dd>{branch?.address || <span className="muted">Not recorded</span>}</dd>

            <dt>Telephone</dt>
            <dd>{branch?.phone || <span className="muted">Not recorded</span>}</dd>

            <dt>Email</dt>
            <dd>{branch?.email || <span className="muted">Not recorded</span>}</dd>

            <dt>On the map</dt>
            <dd>
              {branch?.latitude != null && branch?.longitude != null
                ? <span className="mono">{branch.latitude.toFixed(5)}, {branch.longitude.toFixed(5)}</span>
                : <span className="muted">Not placed, so deliveries cannot be zoned from it</span>}
            </dd>

            <dt>Opened</dt>
            <dd>{branch?.created_at ? fmtDate(branch.created_at)
              : <span className="muted">Not recorded</span>}</dd>
          </dl>
        </section>

        {/* ---- what it may trade on ---- */}
        <section className="card bd-licences">
          <h3><FileText size={15} /> Licences and permits</h3>
          {register && (
            <p className={register.verdict === "ok" ? "muted bd-says" : "alert warn bd-says"}>
              {register.verdict === "ok"
                ? <><CheckCircle size={14} weight="fill" /> {register.says}</>
                : <><Warning size={14} weight="fill" /> {register.says}</>}
            </p>
          )}

          {missing.length > 0 && (
            <div className="bd-missing">
              <span className="bd-missing-head">
                A branch cannot trade without these, and they are not on file
              </span>
              <ul>{missing.map((m) => <li key={m}>{m}</li>)}</ul>
            </div>
          )}

          {!loading && docs.length === 0 && (
            <p className="muted">
              Nothing is on file for this branch. The premises licence and the
              practice certificate are the two an inspector asks for first.
            </p>
          )}
          <Refreshable
            loading={loading}
            hasData={docs.length > 0}
            skeleton={<TableSkeleton cols={4} rows={4} widths={["24ch", "14ch", "12ch", "10ch"]} />}
          >
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <Th>Document</Th><Th>Reference</Th><Th>Issuer</Th>
                    <Th>Standing</Th><Th className="num">Renewal</Th>
                  </tr>
                </thead>
                <tbody>
                  {docs.map((d) => {
                    const s = standing(d);
                    return (
                      <tr key={d.kind}
                          className={!d.id && d.critical ? "row-danger" : undefined}>
                        <td className="bd-doc">
                          {d.id
                            ? <EntityLink kind="compliance_document" id={d.id}>{d.name}</EntityLink>
                            : <b>{d.name}</b>}
                          {d.critical && (
                            <span className="badge muted bd-crit">Cannot trade without it</span>
                          )}
                          {/* Why it matters, for whoever is deciding what to
                              chase first. The register already knows this and
                              it was being thrown away. */}
                          <div className="muted small bd-doc-why">{d.why}</div>
                          {d.issued_on && (
                            <div className="muted small">Issued {fmtDate(d.issued_on)}</div>
                          )}
                        </td>
                        <td className="mono">{d.reference || "none"}</td>
                        <td>{d.issuer || d.expected_issuer || "none"}</td>
                        <td><span className={`badge ${s.tone}`}>{s.label}</span></td>
                        <td className="num">
                          {d.renewal_cost ? money(d.renewal_cost) : "none"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Refreshable>
        </section>
      </div>

      {/* ---- what is on its shelves ---- */}
      <section className="card">
        <h3><Package size={15} /> On these shelves</h3>
        {!loading && lines.length === 0 && (
          <p className="muted">Nothing is held at this branch.</p>
        )}
        {shelf && shelf.below_reorder > 0 && (
          <p className="muted small">
            {shelf.below_reorder} line(s) here are at or below their reorder level.
          </p>
        )}
        <Refreshable
          loading={loading}
          hasData={lines.length > 0}
          skeleton={<TableSkeleton cols={3} rows={5} widths={["30ch", "10ch", "10ch"]} />}
        >
          <div className="dt-scroll">
            <table className="dt">
              <thead>
                <tr>
                  <Th>Medicine</Th>
                  <Th className="num">Here</Th>
                  <Th className="num">Reorder at</Th>
                  <Th className="num">Across the group</Th>
                </tr>
              </thead>
              <tbody>
                {lines.slice(0, 25).map((row) => (
                  <tr key={row.product_id} className={row.below_reorder ? "row-flag" : undefined}>
                    <td>
                      <EntityLink kind="product" id={row.product_id}>{row.name}</EntityLink>
                      {row.below_reorder && (
                        <span className="badge warn">At the reorder level</span>
                      )}
                    </td>
                    <td className="num">{row.here}</td>
                    {/* SET HERE, WHERE IT IS READ.
                        `PUT /branches/:id/levels/:product` has existed since
                        branches could depart from the group and no screen ever
                        called it, so this figure could be seen and never
                        changed: a shop that needed a different level had to
                        ask a developer. Emptying the box clears the override
                        and the group's figure takes over again, which is how a
                        branch goes back without having to know what that
                        figure is. */}
                    <td className="num">
                      <input
                        type="number" min={0} className="bd-level"
                        key={`${row.product_id}-${row.reorder_level}`}
                        defaultValue={row.own_level ? row.reorder_level : ""}
                        placeholder={String(row.group_level ?? row.reorder_level)}
                        title="What THIS branch reorders at. Empty takes the group's figure."
                        disabled={savingLevel === row.product_id}
                        onClick={(e) => e.stopPropagation()}
                        onBlur={(e) => {
                          const raw = e.target.value.trim();
                          const next = raw === "" ? null : Number(raw);
                          const now = row.own_level ? row.reorder_level : null;
                          if ((next ?? null) === (now ?? null)) return;
                          void setLevel(row.product_id, next);
                        }}
                      />
                      {/* Said out loud when this shop has set its own. Two
                          branches showing different levels for one medicine
                          reads as a fault until you know it was a decision. */}
                      {row.own_level && (
                        <div className="muted small">
                          its own, group says {row.group_level}
                        </div>
                      )}
                    </td>
                    <td className="num muted">{row.group_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {lines.length > 25 && (
            <p className="muted small">
              Showing 25 of {lines.length} lines held here.
            </p>
          )}
        </Refreshable>
      </section>
    </RecordPage>
  );
}
