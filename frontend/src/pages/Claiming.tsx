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

type Tab = "batches" | "models";

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
interface PayOffice {
  id: number; code: string; name: string; submission: string; active: boolean;
}

export default function Claiming() {
  const toast = useToast();
  const confirm = useConfirm();
  // Changing how claims are priced needs the same authority as changing a
  // scheme's terms, and the server decides that — this only answers the prompt.
  const { guarded, prompt } = useStepUp();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") === "models" ? "models" : "batches") as Tab;
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

  const load = useCallback(() => {
    api.get<Unbatched[]>("/api/claiming/unbatched").then(setUnbatched)
      .catch((e) => toast.error(errorText(e, "The unbatched claims could not be listed.")));
    api.get<Batch[]>("/api/claiming/batches").then(setBatches).catch(() => undefined);
    api.get<FeeModel[]>("/api/claiming/fee-models").then(setModels).catch(() => undefined);
    api.get<PayOffice[]>("/api/claiming/pay-offices").then(setOffices).catch(() => undefined);
  }, [toast]);

  useEffect(load, [load]);

  const officeName = (id: number) =>
    offices.find((o) => o.id === id)?.name ?? `#${id}`;

  async function makeBatch(row: Unbatched) {
    const ok = await confirm({
      title: `Batch ${row.claims} claim(s) for ${row.pay_office}?`,
      body: `${money(row.value)} of claims will be grouped into one batch ready to `
          + `send. Claims already in a batch are not touched.`,
      confirmLabel: "Create the batch",
    });
    if (!ok) return;
    setBusy(`batch-${row.pay_office_id}`);
    try {
      const made = await api.post<Batch>("/api/claiming/batches",
        { pay_office_id: row.pay_office_id });
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
      </div>

      <div className="pill-tabs">
        <button className={tab === "batches" ? "active" : ""} onClick={() => setTab("batches")}>
          Batches{open.length ? ` (${open.length} open)` : ""}
        </button>
        <button className={tab === "models" ? "active" : ""} onClick={() => setTab("models")}>
          Fee models
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
                      <th className="num">Value</th><th />
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
                            {busy === `batch-${row.pay_office_id}` ? "Creating…" : "Create batch"}
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
                    <th className="num">Settled</th><th className="num">Short</th><th />
                  </tr>
                </thead>
                <tbody>
                  {batches.map((b) => {
                    const short = round2(b.total_claimed - b.total_settled);
                    return (
                      <tr key={b.id}>
                        <td className="mono">{b.batch_number}</td>
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
              Enter what actually arrived — a scheme paying exactly what was
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
                <input
                  type="checkbox" id={`mmap-${m.id}`} checked={m.apply_mmap}
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
