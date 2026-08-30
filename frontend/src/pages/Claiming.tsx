/** Claim batching and the fee models that price a claim.
 *
 *  Thirteen endpoints with no screen. Claims were being priced, batched, sent and
 *  settled by code that nobody could reach, which meant the two things a pharmacy
 *  does with claims every week — send this batch, record what came back — had no
 *  home.
 *
 *  Two tabs, because they are different jobs on different days. Batching is the
 *  weekly operational round: what is unbatched, group it by pay office, submit,
 *  and record the settlement when the remittance lands. Fee models are set up
 *  once and revisited when a scheme renegotiates.
 *
 *  Fee models matter more than they look. `apply_mmap` on a model is the switch
 *  that caps what a scheme is charged at the molecule's reference price — the
 *  cap was in pricing.py all along, reading a field nothing populated, and the
 *  price file now populates it. Without this screen the switch stayed off and
 *  the fix stayed half delivered.
 */
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, errorText, fmtDate, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import ExportButton from "../components/ExportButton";
import Checkbox from "../components/Checkbox";
import Select from "../components/Select";
import BusyButton from "../components/BusyButton";
import { EntityLink } from "../components/Filters";

type Tab = "batches" | "models" | "formularies";

interface Unbatched {
  pay_office_id: number; pay_office: string; code: string;
  claims: number; value: number;
}
interface Batch {
  id: number; batch_number: string; pay_office_id: number; status: string;
  claim_count: number; total_gross: number; total_discount: number;
  total_levy: number; total_claimed: number; total_settled: number;
  period_from: string | null; period_to: string | null;
}
interface Tier {
  up_to: number | null; percentage: number; fixed_fee: number;
  min_fee: number; max_fee: number | null;
}
interface FeeModel {
  id: number; code: string; name: string; basis: string;
  vat_on_fee: boolean; apply_mmap: boolean; notes: string; active: boolean;
  tiers: Tier[];
}
/** A scheme's list of what it will pay for.
 *
 *  `default_rule` decides what happens to a product with no explicit entry.
 *  The model's own warning: getting this backwards is the difference between
 *  over-claiming and rejecting everything.
 */
interface Formulary {
  id: number; code: string; name: string; default_rule: string;
  active: boolean; notes: string;
}
interface FormularyEntry {
  id: number; formulary_id: number; product_id: number; status: string;
  reference_price: number; max_quantity: number;
  requires_authorisation: boolean; note: string;
  /** The server sends the whole product with each entry. */
  product?: { id: number; name: string; strength: string } | null;
}

const ENTRY_STATUS = [
  { value: "covered", label: "Paid in full",
    hint: "at the scheme's fee model" },
  { value: "reference", label: "Up to a reference price",
    hint: "the patient pays the difference" },
  { value: "authorisation", label: "Only against an authorisation",
    hint: "no number, no payment" },
  { value: "excluded", label: "Not paid at all",
    hint: "the patient carries it" },
];

interface PayOffice {
  id: number; code: string; name: string; submission: string; active: boolean;
}

/** The calendar month just gone, which is what a claiming cycle almost always
 *  means: a memorandum says "claims for August by the 25th of September". */
function lastMonth(): { from: string; to: string } {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const last = new Date(now.getFullYear(), now.getMonth(), 0);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(first), to: iso(last) };
}

function lastMonthName(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return d.toLocaleDateString(undefined, { month: "long" });
}

export default function Claiming() {
  const toast = useToast();
  const confirm = useConfirm();
  // Changing how claims are priced needs the same authority as changing a
  // scheme's terms, and the server decides that — this only answers the prompt.
  const { guarded, prompt } = useStepUp();
  const [params, setParams] = useSearchParams();
  // Read against the list of tabs rather than against two hard-coded names.
  // It used to be `=== "models" ? "models" : "batches"`, so adding a third tab
  // gave you a button that set ?tab=formularies in the URL and a reader that
  // mapped it straight back to Batches — the screen behind it was unreachable.
  const TABS: Tab[] = ["batches", "models", "formularies"];
  const tab = (TABS.find((t) => t === params.get("tab")) ?? "batches") as Tab;
  const setTab = (t: Tab) =>
    setParams(t === "batches" ? {} : { tab: t }, { replace: true });

  const [unbatched, setUnbatched] = useState<Unbatched[] | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [models, setModels] = useState<FeeModel[] | null>(null);
  const [offices, setOffices] = useState<PayOffice[]>([]);
  const [busy, setBusy] = useState("");
  // Recording a payment is a form, not a browser prompt: the amount needs a
  // default, the reference needs a second field, and window.prompt gives neither
  // — besides blocking the page while it is up.
  const [settling, setSettling] = useState<Batch | null>(null);
  const [paid, setPaid] = useState("");
  const [reference, setReference] = useState("");
  const [formularies, setFormularies] = useState<Formulary[]>([]);
  const [openFormulary, setOpenFormulary] = useState<Formulary | null>(null);
  const [entries, setEntries] = useState<FormularyEntry[]>([]);
  const [newFormulary, setNewFormulary] = useState<
    { code: string; name: string; default_rule: string; notes: string } | null>(null);
  const [addingEntry, setAddingEntry] = useState(false);
  const [entryProductQ, setEntryProductQ] = useState("");
  const [entryHits, setEntryHits] = useState<any[]>([]);
  const [entryForm, setEntryForm] = useState({
    product_id: 0, product_name: "", status: "covered",
    reference_price: "", max_quantity: "", requires_authorisation: false, note: "",
  });

  const load = useCallback(() => {
    api.get<Unbatched[]>("/api/claiming/unbatched").then(setUnbatched)
      .catch((e) => toast.error(errorText(e, "The unbatched claims could not be listed.")));
    api.get<Batch[]>("/api/claiming/batches").then(setBatches).catch(() => undefined);
    api.get<FeeModel[]>("/api/claiming/fee-models").then(setModels).catch(() => undefined);
    api.get<PayOffice[]>("/api/claiming/pay-offices").then(setOffices).catch(() => undefined);
    api.get<Formulary[]>("/api/claiming/formularies")
      .then(setFormularies).catch(() => undefined);
  }, [toast]);

  useEffect(load, [load]);

  // The entries of whichever formulary is open. Fetched on demand: a scheme's
  // list runs to thousands of lines and none of it is wanted until somebody
  // asks for that scheme.
  useEffect(() => {
    if (!openFormulary) { setEntries([]); return; }
    api.get<FormularyEntry[]>(`/api/claiming/formularies/${openFormulary.id}/entries`)
      .then(setEntries).catch(() => setEntries([]));
  }, [openFormulary]);

  useEffect(() => {
    if (entryProductQ.trim().length < 2) { setEntryHits([]); return; }
    api.get<any>(`/api/products?q=${encodeURIComponent(entryProductQ)}&limit=6`)
      .then((d) => setEntryHits(d.items ?? d ?? []))
      .catch(() => setEntryHits([]));
  }, [entryProductQ]);

  async function createFormulary() {
    if (!newFormulary) return;
    try {
      await api.post("/api/claiming/formularies", newFormulary);
      toast.ok(`${newFormulary.name} added.`);
      setNewFormulary(null);
      load();
    } catch (e) {
      toast.error(errorText(e, "That formulary could not be created."));
    }
  }

  async function saveEntry() {
    if (!openFormulary || !entryForm.product_id) return;
    try {
      await api.post(`/api/claiming/formularies/${openFormulary.id}/entries`, {
        product_id: entryForm.product_id,
        status: entryForm.status,
        reference_price: Number(entryForm.reference_price) || 0,
        max_quantity: Number(entryForm.max_quantity) || 0,
        // A reference-priced or excluded line does not need an authorisation;
        // the flag only means anything on a line the scheme will actually pay.
        requires_authorisation: entryForm.status === "authorisation"
          || entryForm.requires_authorisation,
        note: entryForm.note,
      });
      toast.ok(`${entryForm.product_name} filed on ${openFormulary.name}.`);
      setAddingEntry(false);
      setEntryForm({ product_id: 0, product_name: "", status: "covered",
                     reference_price: "", max_quantity: "",
                     requires_authorisation: false, note: "" });
      setEntryProductQ("");
      const rows = await api.get<FormularyEntry[]>(
        `/api/claiming/formularies/${openFormulary.id}/entries`);
      setEntries(rows);
    } catch (e) {
      toast.error(errorText(e, "That entry could not be saved."));
    }
  }

  const officeName = (id: number) =>
    offices.find((o) => o.id === id)?.name ?? `#${id}`;

  /** Batch a funder's claims, optionally only those in a period.
   *
   *  The endpoint has always taken a date range and the screen never offered
   *  one, so every batch swept up every unbatched claim regardless of when it
   *  was raised. That is wrong in the one case claiming is actually about: a
   *  funder whose memorandum says "claims for August, in by the 25th" wants
   *  August, and a batch carrying three days of September in it is one they
   *  can reject whole.
   */
  async function makeBatch(row: Unbatched, period?: { from: string; to: string }) {
    const ok = await confirm({
      title: `Batch ${row.claims} claim(s) for ${row.pay_office}?`,
      body: period
        ? `Claims raised between ${period.from} and ${period.to} will be grouped `
          + `into one batch ready to send. Anything outside those dates is left `
          + `for the next batch.`
        : `${money(row.value)} of claims will be grouped into one batch ready to `
          + `send. Claims already in a batch are not touched.`,
      confirmLabel: "Create the batch",
    });
    if (!ok) return;
    setBusy(`batch-${row.pay_office_id}`);
    try {
      const made = await api.post<Batch>("/api/claiming/batches",
        { pay_office_id: row.pay_office_id,
          ...(period ? { date_from: period.from, date_to: period.to } : {}) });
      toast.ok(`Batch ${made.batch_number} created with ${made.claim_count} claim(s).`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function submit(batch: Batch) {
    const ok = await confirm({
      title: `Send batch ${batch.batch_number}?`,
      body: `${batch.claim_count} claim(s) worth ${money(batch.total_claimed)} go to `
          + `${officeName(batch.pay_office_id)}. What comes back is recorded against `
          + `this batch.`,
      confirmLabel: "Send the batch",
    });
    if (!ok) return;
    setBusy(`send-${batch.id}`);
    try {
      await api.post(`/api/claiming/batches/${batch.id}/submit`, {});
      toast.ok(`Batch ${batch.batch_number} sent.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function settle(e: React.FormEvent) {
    e.preventDefault();
    if (!settling) return;
    // The amount is asked for rather than assumed to be the claimed total,
    // because a scheme paying exactly what was claimed is the exception. A
    // settlement recorded as the claimed figure hides every short payment.
    const amount = Number(paid);
    if (!Number.isFinite(amount) || amount < 0) {
      toast.error("Enter the amount that was paid, as a number.");
      return;
    }
    setBusy(`settle-${settling.id}`);
    try {
      await api.post(`/api/claiming/batches/${settling.id}/settle`,
        { amount, reference: reference.trim() });
      const short = settling.total_claimed - amount;
      toast.ok(short > 0.005
        ? `Settled. ${money(short)} short of what was claimed.`
        : "Settled in full.");
      setSettling(null);
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function toggleMmap(model: FeeModel) {
    const turningOn = !model.apply_mmap;
    const ok = await confirm({
      title: turningOn
        ? `Cap ${model.name} at the reference price?`
        : `Stop capping ${model.name}?`,
      body: turningOn
        ? "Claims priced on this model will be capped at each medicine's MMAP "
          + "reference price where one is published. Products with no reference "
          + "price are unaffected."
        : "Claims priced on this model will no longer be capped, so they may be "
          + "charged above the published reference price.",
      confirmLabel: turningOn ? "Apply the cap" : "Remove the cap",
    });
    if (!ok) return;
    setBusy(`mmap-${model.id}`);
    try {
      // PATCH, not POST. POST creates and refuses a duplicate code, so sending
      // the model back to it returned 400 — which is how it turned out that
      // nothing could change a fee model at all.
      const res = await guarded(
        "scheme.edit",
        (token) => api.patch(`/api/claiming/fee-models/${model.id}`,
          { apply_mmap: turningOn }, token),
        model.code,
      );
      if (res === CANCELLED) return;
      toast.ok(turningOn ? "Reference-price cap applied." : "Reference-price cap removed.");
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  const open = batches.filter((b) => b.status !== "settled");

  return (
    <>
      {prompt}
      <div className="page-head">
        <div>
          <h1>Claiming</h1>
          <div className="sub">
            Group claims into batches, send them, record what came back, and set
            how a claim is priced
          </div>
        </div>
        {/* A pharmacy reconciles what a funder paid against what was claimed in
            Excel, whatever the software offers. */}
        <ExportButton dataset="claims" label="Claims as a spreadsheet" />
      </div>

      <div className="pill-tabs">
        <button className={tab === "batches" ? "active" : ""} onClick={() => setTab("batches")}>
          Batches{open.length ? ` (${open.length} open)` : ""}
        </button>
        <button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}>
          Fee models
        </button>
        <button className={tab === "formularies" ? "active" : ""}
                onClick={() => setTab("formularies")}>
          Formularies{formularies.length ? ` (${formularies.length})` : ""}
        </button>
      </div>

      {tab === "batches" && (
        <>
          <div className="card">
            <h3>Waiting to be batched</h3>
            {!unbatched ? <TableSkeleton cols={3} rows={3} />
              : unbatched.length === 0 ? (
                <p className="st-note is-ok">
                  Every claim is in a batch. Nothing is sitting unsent.
                </p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Pay office</th><th className="num">Claims</th>
                      <th className="num">Value</th><th className="actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {unbatched.map((row) => (
                      <tr key={row.pay_office_id}>
                        <td>
                          <b>{row.pay_office}</b>
                          <div className="muted mono">{row.code}</div>
                        </td>
                        <td className="num">{row.claims}</td>
                        <td className="num">{money(row.value)}</td>
                        <td className="num">
                          <button
                            className="small"
                            disabled={busy === `batch-${row.pay_office_id}`}
                            onClick={() => makeBatch(row)}
                          >
                            {busy === `batch-${row.pay_office_id}` ? "Creating…" : "Everything"}
                          </button>{" "}
                          {/* A funder whose memorandum says "August, in by the
                              25th" wants August. Batching the lot sweeps in
                              whatever was raised since, which is a batch they
                              can reject whole. */}
                          <button
                            className="small secondary"
                            disabled={busy === `batch-${row.pay_office_id}`}
                            onClick={() => makeBatch(row, lastMonth())}
                          >
                            {lastMonthName()}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
          </div>

          <div className="card">
            <h3>Batches</h3>
            <div className="cu-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Batch</th><th>Pay office</th><th>Period</th><th>Status</th>
                    <th className="num">Claims</th><th className="num">Claimed</th>
                    <th className="num">Settled</th><th className="num">Short</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {batches.map((b) => {
                    const short = round2(b.total_claimed - b.total_settled);
                    return (
                      <tr key={b.id}>
                        {/* The batch opens. A batch that came back short is a
                            figure nobody can act on until they can see which
                            claims were cut, and the endpoint behind that page
                            had been written since claiming was. */}
                        <td className="mono" title={b.batch_number}>
                          <EntityLink kind="claim_batch" id={b.id}>
                            {b.batch_number}
                          </EntityLink>
                        </td>
                        <td>{officeName(b.pay_office_id)}</td>
                        <td className="muted">
                          {b.period_from ? fmtDate(b.period_from) : "—"}
                          {b.period_to ? ` – ${fmtDate(b.period_to)}` : ""}
                        </td>
                        <td><span className={`badge ${badgeFor(b.status)}`}>{b.status}</span></td>
                        <td className="num">{b.claim_count}</td>
                        <td className="num">{money(b.total_claimed)}</td>
                        <td className="num">{money(b.total_settled)}</td>
                        {/* Only on a settled batch. A short figure on a batch that
                            has not been paid yet is not short, it is unpaid. */}
                        <td className={`num${b.status === "settled" && short > 0.005 ? " cu-diff" : ""}`}>
                          {b.status === "settled" && short > 0.005 ? money(short) : "—"}
                        </td>
                        <td className="num">
                          {b.status === "open" && (
                            <button className="small" disabled={busy === `send-${b.id}`}
                              onClick={() => submit(b)}>
                              {busy === `send-${b.id}` ? "Sending…" : "Send"}
                            </button>
                          )}
                          {b.status === "submitted" && (
                            <button className="small"
                              onClick={() => {
                                setSettling(b);
                                setPaid(String(b.total_claimed));
                                setReference("");
                              }}>
                              Record payment
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {settling && (
        <div className="modal-backdrop" onClick={() => setSettling(null)}>
          <form className="modal" onClick={(ev) => ev.stopPropagation()} onSubmit={settle}>
            <h2>Record payment for {settling.batch_number}</h2>
            <p className="muted">
              {officeName(settling.pay_office_id)} was claimed{" "}
              {money(settling.total_claimed)} for {settling.claim_count} claim(s).
              Enter what actually arrived. A scheme paying exactly what was
              claimed is the exception, and a settlement typed as the claimed
              figure hides every short payment.
            </p>
            <label>
              Amount received
              <input
                type="number" step="0.01" min="0" value={paid} autoFocus
                onChange={(ev) => setPaid(ev.target.value)}
              />
            </label>
            <label>
              Payment reference <span className="muted">(optional)</span>
              <input value={reference} onChange={(ev) => setReference(ev.target.value)} />
            </label>
            {Number(paid) < settling.total_claimed - 0.005 && (
              <p className="alert warn">
                {money(settling.total_claimed - Number(paid || 0))} short of what was
                claimed. The shortfall stays against the batch.
              </p>
            )}
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setSettling(null)}>
                Cancel
              </button>
              <button type="submit" className="btn primary" disabled={busy.startsWith("settle")}>
                {busy.startsWith("settle") ? "Saving…" : "Record it"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* What each scheme will pay for.
          Full CRUD on the server since it was written, and no screen: the
          coverage check on the dispensing page has been answering from
          formularies nobody could see, let alone maintain. */}
      {tab === "formularies" && (
        <>
          <div className="card">
            <div className="card-head">
              <h3>Formularies</h3>
              <button className="btn" onClick={() => setNewFormulary(
                { code: "", name: "", default_rule: "covered", notes: "" })}>
                New formulary
              </button>
            </div>
            {formularies.length === 0 ? (
              <div className="empty">
                <b>No scheme has a formulary on file.</b>
                <p>
                  Without one, every claim is priced as though the scheme pays
                  for everything. The rejections arrive weeks later, one at a
                  time, and by then the medicine has gone out.
                </p>
              </div>
            ) : (
              <table className="dt">
                <thead>
                  <tr>
                    <th>Formulary</th><th>What it does by default</th>
                    <th className="num">Listed</th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {formularies.map((f) => (
                    <tr key={f.id} className={f.active ? "" : "row-flag"}>
                      <td>
                        <b>{f.name}</b>
                        <div className="muted small mono">
                          {f.code}{f.active ? "" : " · not in use"}
                        </div>
                      </td>
                      <td className="wrap">
                        {/* Spelled out rather than shown as the stored word.
                            "covered" and "excluded" read as a property of the
                            formulary; what they actually decide is the fate of
                            every product nobody has listed. */}
                        {f.default_rule === "covered"
                          ? <>Open — pays for anything not explicitly excluded</>
                          : <>Closed — pays only for what is listed below</>}
                        {f.notes && <div className="muted small">{f.notes}</div>}
                      </td>
                      <td className="num">
                        {openFormulary?.id === f.id ? entries.length
                          : <span className="muted">—</span>}
                      </td>
                      <td className="actions">
                        <button className="btn small secondary"
                                onClick={() => setOpenFormulary(
                                  openFormulary?.id === f.id ? null : f)}>
                          {openFormulary?.id === f.id ? "Close" : "Open"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {openFormulary && (
            <div className="card">
              <div className="card-head">
                <h3>{openFormulary.name}</h3>
                <button className="btn" onClick={() => setAddingEntry(true)}>
                  List a product
                </button>
              </div>
              <p className="muted">
                {openFormulary.default_rule === "covered"
                  ? "This formulary is open, so anything not listed here is paid for. List the exceptions."
                  : "This formulary is closed, so anything not listed here is refused. List what the scheme pays for."}
              </p>
              {entries.length === 0 ? (
                <div className="empty">
                  Nothing is listed.{" "}
                  {openFormulary.default_rule === "covered"
                    ? "Every product is being claimed as covered."
                    : "Every claim against this scheme will be refused."}
                </div>
              ) : (
                <table className="dt">
                  <thead>
                    <tr>
                      <th>Product</th><th>Standing</th>
                      <th className="num">Reference price</th>
                      <th className="num">Max per dispensing</th><th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e) => (
                      <tr key={e.id}>
                        <td>
                          <EntityLink kind="product" id={e.product_id}>
                            {/* The server sends the product with the entry.
                                Showing the id instead would make a formulary
                                a list of numbers to look up one at a time. */}
                            <b>{e.product?.name ?? `#${e.product_id}`}</b>
                            {e.product?.strength ? ` ${e.product.strength}` : ""}
                          </EntityLink>
                        </td>
                        <td>
                          {ENTRY_STATUS.find((x) => x.value === e.status)?.label
                            ?? e.status}
                          {e.requires_authorisation && (
                            <div className="muted small">needs an authorisation number</div>
                          )}
                        </td>
                        <td className="num">
                          {e.reference_price
                            ? money(e.reference_price)
                            : <span className="muted">—</span>}
                        </td>
                        <td className="num">
                          {e.max_quantity || <span className="muted">no limit</span>}
                        </td>
                        <td className="small wrap">{e.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}

      {newFormulary && (
        <div className="modal-backdrop" onClick={() => setNewFormulary(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>New formulary</h2>
            <div className="form-row">
              <div className="field">
                <label>Name</label>
                <input value={newFormulary.name} autoFocus
                       onChange={(e) => setNewFormulary({ ...newFormulary, name: e.target.value })}
                       placeholder="e.g. CIMAS Private Hospital Plan" />
              </div>
              <div className="field">
                <label>Code</label>
                <input value={newFormulary.code}
                       onChange={(e) => setNewFormulary({ ...newFormulary, code: e.target.value.toUpperCase() })}
                       placeholder="as the scheme writes it" />
              </div>
            </div>
            <div className="field">
              <label>What happens to a product nobody has listed</label>
              <Select
                value={newFormulary.default_rule}
                onChange={(v) => setNewFormulary({ ...newFormulary, default_rule: v })}
                options={[
                  { value: "covered", label: "Open — pay unless told otherwise" },
                  { value: "excluded", label: "Closed — pay only what is listed" },
                ]}
              />
              {/* The model's own warning, put where the choice is made rather
                  than left in the source. */}
              <span className="field-hint">
                Getting this backwards is the difference between over-claiming
                and rejecting everything.
              </span>
            </div>
            <div className="field">
              <label>Notes</label>
              <input value={newFormulary.notes}
                     onChange={(e) => setNewFormulary({ ...newFormulary, notes: e.target.value })}
                     placeholder="optional" />
            </div>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setNewFormulary(null)}>Cancel</button>
              <BusyButton
                disabled={newFormulary.name.trim().length < 2 || !newFormulary.code.trim()}
                onClick={createFormulary}>
                Create it
              </BusyButton>
            </div>
          </div>
        </div>
      )}

      {addingEntry && openFormulary && (
        <div className="modal-backdrop" onClick={() => setAddingEntry(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>List a product on {openFormulary.name}</h2>
            <div className="field">
              <label>Which product</label>
              {entryForm.product_id ? (
                <div className="product-pick">
                  <span>{entryForm.product_name}</span>
                  <button type="button" className="btn ghost small"
                          onClick={() => setEntryForm({ ...entryForm, product_id: 0, product_name: "" })}>
                    Change
                  </button>
                </div>
              ) : (
                <>
                  <input type="search" autoFocus value={entryProductQ}
                         onChange={(e) => setEntryProductQ(e.target.value)}
                         placeholder="Search the catalogue…" />
                  {entryHits.map((pr: any) => (
                    <div key={pr.id} className="product-pick"
                         onClick={() => {
                           setEntryForm({ ...entryForm, product_id: pr.id,
                                          product_name: `${pr.name} ${pr.strength ?? ""}`.trim() });
                           setEntryProductQ("");
                         }}>
                      <span>{pr.name} {pr.strength}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
            <div className="field">
              <label>What the scheme does with it</label>
              <Select value={entryForm.status}
                      onChange={(v) => setEntryForm({ ...entryForm, status: v })}
                      options={ENTRY_STATUS} />
            </div>
            {entryForm.status === "reference" && (
              <div className="field">
                <label>Reference price</label>
                <input type="number" step="0.01" min="0"
                       value={entryForm.reference_price}
                       onChange={(e) => setEntryForm({ ...entryForm, reference_price: e.target.value })} />
                <span className="field-hint">
                  The scheme pays up to this; the patient pays whatever the
                  product costs above it.
                </span>
              </div>
            )}
            <div className="field">
              <label>Most it will pay for in one dispensing</label>
              <input type="number" min="0" value={entryForm.max_quantity}
                     onChange={(e) => setEntryForm({ ...entryForm, max_quantity: e.target.value })}
                     placeholder="leave empty for no limit" />
            </div>
            <div className="field">
              <label>Note</label>
              <input value={entryForm.note}
                     onChange={(e) => setEntryForm({ ...entryForm, note: e.target.value })}
                     placeholder="e.g. chronic only, per the March memorandum" />
            </div>
            <div className="modal-actions">
              <button className="btn ghost" onClick={() => setAddingEntry(false)}>Cancel</button>
              <BusyButton disabled={!entryForm.product_id} onClick={saveEntry}>
                File it
              </BusyButton>
            </div>
          </div>
        </div>
      )}

      {tab === "models" && (
        <div className="card">
          <h3>Fee models</h3>
          <p className="muted">
            How a claim is priced: what the fee is based on, the bands that apply,
            and whether the charge is capped at the published reference price.
          </p>
          {!models ? <TableSkeleton cols={4} rows={3} /> : models.map((m) => (
            <div className="fm-model" key={m.id}>
              <div className="fm-head">
                <div>
                  <span className="fm-name">{m.name}</span>
                  <span className="muted mono"> {m.code}</span>
                  {!m.active && <span className="badge muted">inactive</span>}
                </div>
                <div className="fm-flags">
                  <span className="badge muted">basis: {m.basis}</span>
                  <span className="badge muted">
                    {m.vat_on_fee ? "VAT on fee" : "no VAT on fee"}
                  </span>
                </div>
              </div>

              {m.notes && <p className="muted small">{m.notes}</p>}

              <table className="fm-tiers">
                <thead>
                  <tr>
                    <th>Up to</th><th className="num">Percentage</th>
                    <th className="num">Fixed fee</th><th className="num">Minimum</th>
                    <th className="num">Maximum</th>
                  </tr>
                </thead>
                <tbody>
                  {m.tiers.map((t, i) => (
                    <tr key={i}>
                      <td>{t.up_to === null ? "and above" : money(t.up_to)}</td>
                      <td className="num">{t.percentage}%</td>
                      <td className="num">{money(t.fixed_fee)}</td>
                      <td className="num">{money(t.min_fee)}</td>
                      <td className="num">{t.max_fee === null ? "—" : money(t.max_fee)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="check-row fm-mmap">
                <Checkbox
                  id={`mmap-${m.id}`} checked={m.apply_mmap}
                  disabled={busy === `mmap-${m.id}`}
                  onChange={() => toggleMmap(m)}
                />
                <label htmlFor={`mmap-${m.id}`}>
                  Cap at the reference price (MMAP)
                  <span className="muted">
                    {" "}— charges no more than the molecule's published reference
                    price, where one has been loaded.
                  </span>
                </label>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}

function badgeFor(status: string) {
  if (status === "settled") return "ok";
  if (status === "submitted") return "sched";
  if (status === "rejected") return "danger";
  return "muted";
}
