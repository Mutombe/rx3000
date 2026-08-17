/** Counting the shelves.
 *
 *  Six endpoints, step-up gated, with no way in. A stock take is the largest
 *  single adjustment anybody in the building can make — closing one posts every
 *  variance as a stock movement — and it could not be started.
 *
 *  The count is blind, and the screen has to work at keeping it that way. The
 *  server reveals what it expected only in the reply to a submitted count, so
 *  the one thing this page must never do is show a quantity beside a product
 *  before it has been counted. That rules out the ordinary product picker, which
 *  puts stock on hand next to every result: it would hand the counter the answer
 *  while they are still holding the box.
 *
 *  So the search here shows name, pack and bin — enough to find the right line on
 *  a shelf, and nothing about how many there should be.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText, fmtDateTime, money } from "../api";
import { useConfirm } from "../components/Confirm";
import { useStepUp, CANCELLED } from "../components/StepUp";
import { useToast } from "../components/Toast";
import { Product } from "../types";

interface Scope { category: string; bin: string }
interface Take {
  id: number; reference: string; status: string; scope: Scope;
  opened_at: string | null; closed_at: string | null;
  counted_lines: number; variance_units: number; variance_value: number;
  over_units: number; short_units: number;
}
interface Line {
  product: string; counted: number; expected: number;
  variance: number; value: number; note: string;
}
interface Detail extends Take { lines: Line[] }
interface CountReply {
  product: string; counted: number; expected: number;
  variance: number; value: number; message: string;
}

export default function StockTake() {
  const toast = useToast();
  const confirm = useConfirm();
  const { guarded, prompt } = useStepUp();

  const [take, setTake] = useState<Take | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  // opening
  const [category, setCategory] = useState("");
  const [bin, setBin] = useState("");

  // counting
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [picked, setPicked] = useState<Product | null>(null);
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const [lastCount, setLastCount] = useState<CountReply | null>(null);
  const countBox = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.get<Take | null>("/api/stock-takes/open")
      .then((open) => {
        setTake(open);
        if (open) {
          api.get<Detail>(`/api/stock-takes/${open.id}`).then(setDetail).catch(() => undefined);
        } else {
          setDetail(null);
        }
      })
      .catch((e) => toast.error(errorText(e, "The stock take could not be loaded.")))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(query)}&limit=8`)
      .then(setResults)
      .catch(() => setResults([]));
  }, [query]);

  async function open() {
    setBusy("open");
    try {
      const made = await api.post<Take & { message: string }>("/api/stock-takes", {
        scope_category: category.trim(), scope_bin: bin.trim(),
      });
      toast.ok(made.message);
      setCategory(""); setBin("");
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function recordCount(e: React.FormEvent) {
    e.preventDefault();
    if (!take || !picked) return;
    const n = Number(counted);
    if (!Number.isInteger(n) || n < 0) {
      toast.error("Enter how many are on the shelf, as a whole number.");
      return;
    }
    setBusy("count");
    try {
      const reply = await api.post<CountReply>(`/api/stock-takes/${take.id}/count`, {
        product_id: picked.id, counted: n, note: note.trim(),
      });
      // Shown, not toasted away: the variance for the line just counted is the
      // only moment the counter learns what the system believed, and it is worth
      // reading before moving to the next shelf.
      setLastCount(reply);
      setPicked(null); setCounted(""); setNote(""); setQuery("");
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function close() {
    if (!take) return;
    const ok = await confirm({
      title: `Close ${take.reference}?`,
      body: `This posts every variance as a stock movement: ${take.over_units} unit(s) `
          + `over and ${take.short_units} short, ${money(Math.abs(take.variance_value))} `
          + `in all. Stock on hand changes to what was counted, and it cannot be undone.`,
      confirmLabel: "Close and adjust stock",
      destructive: true,
    });
    if (!ok) return;
    setBusy("close");
    try {
      const res = await guarded(
        "stocktake.close",
        (token) => api.post<{ message: string }>(
          `/api/stock-takes/${take.id}/close`, {}, token),
        take.reference,
      );
      if (res === CANCELLED) return;
      toast.ok(res.message);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function abandon() {
    if (!take) return;
    const ok = await confirm({
      title: `Abandon ${take.reference}?`,
      body: `The ${take.counted_lines} line(s) already counted are discarded and no `
          + `stock is adjusted. Use this when a count has gone wrong, not to avoid `
          + `a variance.`,
      confirmLabel: "Abandon the count",
      destructive: true,
    });
    if (!ok) return;
    setBusy("abandon");
    try {
      await api.post(`/api/stock-takes/${take.id}/abandon`, {});
      toast.ok(`${take.reference} abandoned. Nothing was adjusted.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  if (loading) return <div className="card"><div className="empty">Loading…</div></div>;

  return (
    <>
      {prompt}
      <div className="page-head">
        <div>
          <h1>Stock take</h1>
          <div className="sub">
            Count what is on the shelf. Nothing is adjusted until the count is closed
          </div>
        </div>
      </div>

      {!take ? (
        <div className="card">
          <h3>Start a count</h3>
          <p className="muted">
            Leave both boxes empty to count everything. A scope keeps a count to
            one part of the shop, which is how a pharmacy counts without closing:
            a shelf at a time, on a quiet afternoon.
          </p>
          <div className="form-row">
            <div className="field">
              <label>Category <span className="muted">(optional)</span></label>
              <input value={category} onChange={(e) => setCategory(e.target.value)}
                placeholder="e.g. medicine" />
            </div>
            <div className="field">
              <label>Bin location <span className="muted">(optional)</span></label>
              <input value={bin} onChange={(e) => setBin(e.target.value)}
                placeholder="e.g. A3" />
            </div>
          </div>
          <div className="cu-actions">
            <button className="btn primary" disabled={busy === "open"} onClick={open}>
              {busy === "open" ? "Opening…" : "Open a stock take"}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="card">
            <div className="cu-head">
              <h3 style={{ margin: 0 }}>{take.reference}</h3>
              <span className="badge ok">{take.status}</span>
            </div>
            <p className="muted">
              Opened {take.opened_at ? fmtDateTime(take.opened_at) : "—"}
              {take.scope.category || take.scope.bin
                ? ` · counting ${[take.scope.category, take.scope.bin].filter(Boolean).join(" / ")}`
                : " · counting everything"}
            </p>

            <div className="stat-row">
              <div className="stat">
                <span className="stat-label">Lines counted</span>
                <span className="stat-value">{take.counted_lines}</span>
              </div>
              {/* Over and short separately, never netted. A count 40 over and 40
                  short is not a clean count, it is two errors. */}
              <div className="stat">
                <span className="stat-label">Units over</span>
                <span className="stat-value">{take.over_units}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Units short</span>
                <span className="stat-value">{take.short_units}</span>
              </div>
              <div className="stat">
                <span className="stat-label">Value at cost</span>
                <span className="stat-value">{money(take.variance_value)}</span>
              </div>
            </div>

            <div className="cu-actions">
              <button className="btn ghost small" disabled={busy === "abandon"} onClick={abandon}>
                {busy === "abandon" ? "Abandoning…" : "Abandon"}
              </button>
              <button className="btn primary" disabled={busy === "close"} onClick={close}>
                {busy === "close" ? "Closing…" : "Close and adjust stock"}
              </button>
            </div>
          </div>

          <div className="card">
            <h3>Count a product</h3>
            {/* No quantities in these results, deliberately. */}
            <p className="muted small">
              What the system expected appears once you have entered a count, not
              before.
            </p>

            {picked ? (
              <form onSubmit={recordCount}>
                <div className="st-picked">
                  <b>{picked.name}</b>
                  <span className="muted">
                    {picked.strength ? ` ${picked.strength}` : ""}
                    {picked.pack_size ? ` · ${picked.pack_size}` : ""}
                    {picked.bin_location ? ` · bin ${picked.bin_location}` : ""}
                  </span>
                  <button type="button" className="btn ghost small"
                    onClick={() => { setPicked(null); setCounted(""); }}>
                    Change
                  </button>
                </div>
                <div className="form-row">
                  <div className="field">
                    <label>Counted on the shelf</label>
                    <input
                      ref={countBox} type="number" min={0} step={1} autoFocus
                      value={counted} onChange={(e) => setCounted(e.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label>Note <span className="muted">(optional)</span></label>
                    <input value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="e.g. two boxes damaged" />
                  </div>
                </div>
                <div className="cu-actions">
                  <button className="btn primary" type="submit" disabled={busy === "count"}>
                    {busy === "count" ? "Recording…" : "Record the count"}
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="field">
                  <label>Find the product</label>
                  <input
                    value={query} autoFocus
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Name, or scan the barcode"
                  />
                </div>
                {results.length > 0 && (
                  <ul className="st-results">
                    {results.map((p) => (
                      <li key={p.id}>
                        <button type="button" onClick={() => {
                          setPicked(p); setLastCount(null);
                          setTimeout(() => countBox.current?.focus(), 0);
                        }}>
                          <b>{p.name}</b>
                          <span className="muted">
                            {p.strength ? ` ${p.strength}` : ""}
                            {p.pack_size ? ` · ${p.pack_size}` : ""}
                            {p.bin_location ? ` · bin ${p.bin_location}` : ""}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}

            {lastCount && (
              <p className={`st-note ${lastCount.variance === 0 ? "is-ok" : "is-bad"}`}>
                {lastCount.message}
                {lastCount.variance !== 0 && ` ${money(Math.abs(lastCount.value))} at cost.`}
              </p>
            )}
          </div>

          <div className="card">
            <h3>Counted so far</h3>
            {!detail || detail.lines.length === 0 ? (
              <div className="empty">Nothing counted yet.</div>
            ) : (
              <div className="cu-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th className="num">Counted</th><th className="num">System</th>
                      <th className="num">Variance</th><th className="num">At cost</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* Biggest variance first, from the server. The line worth
                        recounting is the one at the top. */}
                    {detail.lines.map((l, i) => (
                      <tr key={i} className={l.variance !== 0 ? "is-off" : ""}>
                        <td>{l.product}</td>
                        <td className="num">{l.counted}</td>
                        <td className="num">{l.expected}</td>
                        <td className={`num${l.variance !== 0 ? " cu-diff" : ""}`}>
                          {l.variance > 0 ? `+${l.variance}` : l.variance || "—"}
                        </td>
                        <td className="num">{l.variance ? money(l.value) : "—"}</td>
                        <td className="muted">{l.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
