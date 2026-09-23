/** Counting the shelves.
 *
 *  Six endpoints, step-up gated, with no way in. A stock take is the largest
 *  single adjustment anybody in the building can make — closing one posts every
 *  variance as a stock movement, and it could not be started.
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
import { useScanFeed } from "../components/ScannerHub";
import { Product } from "../types";
import Select from "../components/Select";

/** One count on file, as the history list needs it. */
interface PastTake {
  id: number;
  reference: string;
  status: string;
  closed_at: string | null;
  counted_lines: number;
  variance_units: number;
  variance_value: number;
  over_units: number;
  short_units: number;
}
import { EntityLink } from "../components/Filters";
import { TableSkeleton } from "../components/Skeleton";

interface Scope { category: string; bin: string }
interface Take {
  id: number; reference: string; status: string; scope: Scope;
  opened_at: string | null; closed_at: string | null;
  counted_lines: number; variance_units: number; variance_value: number;
  over_units: number; short_units: number;
}
interface Line {
  product_id: number; product: string; counted: number; expected: number;
  variance: number; value: number; note: string;
}
interface SheetLine {
  product_id: number; product: string; stock_code: string; bin: string;
  pack_size: string; expected: number; counted: number | null;
  variance: number | null;
}
interface Sheet {
  reference: string;
  scope: { category: string; bin: string };
  lines: SheetLine[];
  expected_lines: number;
  counted_lines: number;
  outstanding: number;
}
interface Detail extends Take { lines: Line[] }
interface CountReply {
  product: string; counted: number; expected: number;
  variance: number; value: number; message: string;
}


/** What is still to count, grouped by the shelf it is on.
 *
 *  A stock take is walked, not searched. The screen gave a search box and a
 *  running total, which answers "have I counted this one" and never answers
 *  the question somebody standing in an aisle actually has, which is "what is
 *  left on this shelf, and which shelf do I do next".
 *
 *  Nothing here reveals a quantity. The count is blind and the sheet carries
 *  what the system expects, so only the product, its pack and its bin are
 *  read off it: handing the counter the answer while they are holding the box
 *  is the one thing this page must never do.
 */
function shelvesLeft(sheet: Sheet | null): { bin: string; lines: SheetLine[] }[] {
  if (!sheet) return [];
  const byBin = new Map<string, SheetLine[]>();
  for (const line of sheet.lines) {
    if (line.counted !== null) continue;
    const where = line.bin || "no shelf recorded";
    const rows = byBin.get(where);
    if (rows) rows.push(line); else byBin.set(where, [line]);
  }
  // Fullest shelf first: it is the one that decides how long this takes, and
  // the lines with no shelf go last because they need finding rather than
  // walking to.
  return [...byBin.entries()]
    .map(([bin, lines]) => ({ bin, lines }))
    .sort((a, b) => (a.bin === "no shelf recorded" ? 1
      : b.bin === "no shelf recorded" ? -1 : b.lines.length - a.lines.length));
}

export default function StockTake() {
  const toast = useToast();
  /** Counts already closed. Null while loading, so the panel can hold its
   *  shape rather than flashing an empty state at somebody. */
  const [past, setPast] = useState<PastTake[] | null>(null);
  useEffect(() => {
    api.get<{ items: PastTake[] }>("/api/stock-takes?page=1&per_page=25")
      .then((r) => setPast(r.items))
      .catch((e) => toast.error(errorText(e, "The count history could not be read.")));
  }, []);
  useScanFeed("Stock count", (code) => void fromPhone(code));
  const confirm = useConfirm();
  const { guarded, prompt } = useStepUp();

  const [take, setTake] = useState<Take | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  /** What this count is supposed to cover, and how much of it is done.
   *
   *  The scope fields have been on the record since it was written and were
   *  used for nothing, so a count of one line out of a thousand closed and
   *  posted as if the aisle had been checked. */
  const [sheet, setSheet] = useState<Sheet | null>(null);
  /** Which shelf is open in the walk. One at a time: a list of every
   *  uncounted line in the shop is the thing this replaced. */
  const [walking, setWalking] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");

  /** The shelves with something still on them, fullest first. */
  const shelves = shelvesLeft(sheet);

  // opening
  const [category, setCategory] = useState("");
  const [bin, setBin] = useState("");
  /* THE SHOP'S OWN SHELVES AND DEPARTMENTS, RATHER THAN TWO EMPTY BOXES.
     Scope was two free-text fields reading "e.g. medicine" and "e.g. A3", so
     starting a count began by remembering what this pharmacy calls its
     departments and how its shelf labels are spelled. Get either wrong and the
     count opens over nothing and says so only once somebody has walked to the
     shelf. Both are on file; both are offered. */
  const [bins, setBins] = useState<{ bin: string; lines: number }[]>([]);
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);
  useEffect(() => {
    api.get<{ bins: { bin: string; lines: number }[] }>("/api/stock/bins")
      .then((r) => setBins((r.bins ?? []).filter((b) => b.bin)))
      .catch(() => setBins([]));
    api.get<{ id: number; name: string }[]>("/api/stock-categories")
      .then(setDepartments).catch(() => setDepartments([]));
  }, []);

  // counting
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [picked, setPicked] = useState<Product | null>(null);
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const [lastCount, setLastCount] = useState<CountReply | null>(null);
  const countBox = useRef<HTMLInputElement>(null);

  /** ARRIVING WITH A PRODUCT ALREADY IN MIND.
   *
   *  Reconciliation names a stock take as the thing that settles a
   *  disagreement and could not open one: somebody read "Methylphenidate,
   *  own count 0, 518 in the batches", came here, and typed the name in
   *  again from memory. `?product=` picks it on arrival, exactly as a
   *  scanned pack does, so the line that raised the question is the line
   *  being counted.
   *
   *  Silent when the id is nonsense or the product has since gone: the
   *  screen still works, it just opens without a pick. An error toast for a
   *  stale link would be shouting about the one thing that does not matter.
   */
  useEffect(() => {
    const wanted = Number(new URLSearchParams(window.location.search).get("product"));
    if (!wanted) return;
    let live = true;
    api.get<{ product: Product }>(`/api/products/${wanted}`)
      .then((r) => {
        if (!live || !r.product) return;
        setPicked(r.product);
        setLastCount(null);
        window.setTimeout(() => countBox.current?.focus(), 0);
      })
      .catch(() => {});
    return () => { live = false; };
  }, []);

  /** A pack scanned on a phone at the shelf.
   *
   *  Picks the product straight away and puts the cursor in the count box, so
   *  the whole interaction is: point the phone, type what is on the shelf,
   *  press record. Nothing is typed twice and nothing is carried anywhere.
   */
  async function fromPhone(code: string) {
    try {
      const r = await api.post<{ found: boolean; product: Product | null }>(
        "/api/scan", { code, context: "stock" });
      if (!r.found || !r.product) {
        toast.error("That pack is not one this pharmacy stocks.");
        return;
      }
      setPicked(r.product);
      setLastCount(null);
      window.setTimeout(() => countBox.current?.focus(), 0);
    } catch (e) {
      toast.error(errorText(e, "That pack could not be read."));
    }
  }

  const load = useCallback(() => {
    setSheet(null);
    api.get<Take | null>("/api/stock-takes/open")
      .then((open) => {
        setTake(open);
        if (open) {
          api.get<Detail>(`/api/stock-takes/${open.id}`).then(setDetail).catch(() => undefined);
          // What the count is supposed to cover, so the screen can say how
          // much is left rather than only what has been done.
          api.get<Sheet>(`/api/stock-takes/${open.id}/sheet`)
            .then(setSheet).catch(() => undefined);
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
      // A count that has not covered its own scope is refused, and the
      // refusal names what is left. Offering to post it anyway is a separate
      // decision the person has to make out loud, because an uncounted line
      // keeps its old figure while the paperwork says the shelf was checked.
      let asPartial = false;
      const left = sheet ? sheet.outstanding : 0;
      if (left > 0) {
        // The house dialog, not the browser's. A native confirm freezes the
        // whole application until somebody clicks OK and cannot name the
        // action or park focus on Cancel, which is the wrong default when
        // the answer posts an incomplete count.
        asPartial = await confirm({
          title: "Post an incomplete count?",
          body: <>
            {left} line{left === 1 ? " has" : "s have"} not been counted yet.
            {" "}The lines you did not count keep their present figures, and
            {" "}this count is recorded as incomplete so the next person knows
            {" "}what it covered.
          </>,
          confirmLabel: "Post what was counted",
          cancelLabel: "Keep counting",
          destructive: true,
        });
        if (!asPartial) return;
      }
      const res = await guarded(
        "stocktake.close",
        (token) => api.post<{ message: string }>(
          `/api/stock-takes/${take.id}/close${asPartial ? "?partial=true" : ""}`,
          {}, token),
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

  // "Loading…" in the middle of an empty card is the placeholder a skeleton
  // replaces: it says nothing about what is coming and the page jumps when it
  // does.
  if (loading) {
    return (
      <div className="card">
        <TableSkeleton cols={5} rows={5}
          widths={["22ch", "10ch", "10ch", "10ch", "12ch"]} />
      </div>
    );
  }

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
              <label>Department</label>
              <Select value={category} onChange={setCategory}
                options={[{ value: "", label: "Every department" },
                          ...departments.map((d) => ({
                            value: d.name, label: d.name }))]} />
            </div>
            <div className="field">
              <label>Shelf</label>
              {/* Each shelf says how many lines are on it, because that is the
                  question somebody is actually answering: not "which shelf"
                  but "how long is this going to take". */}
              <Select value={bin} onChange={setBin}
                options={[{ value: "", label: "Every shelf" },
                          ...bins.map((b) => ({
                            value: b.bin,
                            label: `${b.bin}. ${b.lines} line${b.lines === 1 ? "" : "s"}`,
                          }))]} />
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
              Opened {take.opened_at ? fmtDateTime(take.opened_at) : "no date"}
              {take.scope.category || take.scope.bin
                ? ` · counting ${[take.scope.category, take.scope.bin].filter(Boolean).join(" / ")}`
                : " · counting everything"}
            </p>

            {/* HOW FAR THROUGH THIS IS, AS A SHAPE.
                Two numbers beside each other are a sum somebody does in their
                head every time they look. A count of eleven hundred lines is
                walked over an afternoon and the question at every pause is the
                same one: how much of this is left. */}
            {sheet && sheet.expected_lines > 0 && (
              <div className="st-progress"
                   role="progressbar" aria-valuemin={0}
                   aria-valuemax={sheet.expected_lines}
                   aria-valuenow={sheet.counted_lines}
                   aria-label={`${sheet.counted_lines} of ${sheet.expected_lines} lines counted`}>
                <div className="st-progress-done" style={{
                  width: `${Math.round(
                    (sheet.counted_lines / sheet.expected_lines) * 100)}%` }} />
              </div>
            )}

            <div className="stat-row">
              <div className="stat">
                <span className="stat-label">Lines counted</span>
                <span className="stat-value">
                  {take.counted_lines}
                  {/* Out of how many. A count that shows only what has been
                      done cannot tell anybody it is unfinished, which is how
                      one line out of a thousand used to close and post. */}
                  {sheet && <span className="muted"> of {sheet.expected_lines}</span>}
                </span>
              </div>
              {sheet && sheet.outstanding > 0 && (
                <div className="stat">
                  <span className="stat-label">Still to count</span>
                  <span className="stat-value tone-danger">{sheet.outstanding}</span>
                </div>
              )}
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

          {/* WHAT IS LEFT, AND WHERE IT IS.
              The screen could say how many lines had been counted and could
              not say which ones were missing, so finishing a count meant
              remembering the shop. This is the walk: the fullest shelf first,
              every uncounted line on it, and a tap to start counting one.
              Nothing here shows a quantity, because the count is blind. */}
          {shelves.length > 0 && (
            <div className="card">
              <div className="card-head">
                <h3>Still to count</h3>
                <span className="muted small">
                  {sheet?.outstanding} line{sheet?.outstanding === 1 ? "" : "s"} across{" "}
                  {shelves.length} shelf{shelves.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="st-shelves">
                {shelves.map((shelf) => (
                  <div key={shelf.bin} className="st-shelf">
                    <button type="button" className="st-shelf-head"
                            aria-expanded={walking === shelf.bin}
                            onClick={() => setWalking(
                              walking === shelf.bin ? "" : shelf.bin)}>
                      <b>{shelf.bin}</b>
                      <span className="muted small">
                        {shelf.lines.length} to count
                      </span>
                    </button>
                    {walking === shelf.bin && (
                      <ul className="st-results st-shelf-lines">
                        {shelf.lines.map((line) => (
                          <li key={line.product_id}>
                            <button type="button" onClick={() => {
                              // Straight into the count box, with the product
                              // already chosen. Searching for a line the screen
                              // has just listed is work the screen can do.
                              setPicked({
                                id: line.product_id, name: line.product,
                                pack_size: line.pack_size,
                                bin_location: line.bin,
                              } as unknown as Product);
                              setLastCount(null); setCounted(""); setNote("");
                              setTimeout(() => countBox.current?.focus(), 0);
                            }}>
                              <b>{line.product}</b>
                              <span className="muted">
                                {line.pack_size ? ` · ${line.pack_size}` : ""}
                                {line.stock_code ? ` · ${line.stock_code}` : ""}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

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
                {/* A COUNT IS DONE AT THE SHELF, NOT AT THE MACHINE.
                    This box said "or scan the barcode" and nothing behind it
                    could scan anything: a scanner plugged into the counter
                    types into it, which works if you carry every box to the
                    till, and that is not how a stock count is done. The phone
                    goes to the shelf. */}
                <div className="field">
                  <label htmlFor="st-find">Find the product</label>
                  <input
                    id="st-find" value={query} autoFocus
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
                        <td><EntityLink kind="product" id={l.product_id}>{l.product}</EntityLink></td>
                        <td className="num">{l.counted}</td>
                        <td className="num">{l.expected}</td>
                        <td className={`num${l.variance !== 0 ? " cu-diff" : ""}`}>
                          {l.variance > 0 ? `+${l.variance}` : l.variance || "none"}
                        </td>
                        <td className="num">{l.variance ? money(l.value) : "none"}</td>
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

      {/* EVERY COUNT EVER DONE, WHICH WAS UNREACHABLE.
          The screen loaded the count currently open and showed nothing else,
          because no endpoint listed them. So every completed count — the
          variances found, what they were worth, when they closed — sat on the
          database with no way to it. A variance is the start of an insurance
          claim, a write-off, or a conversation with somebody about missing
          stock, and it is the record a pharmacy is most likely to be asked
          for months later. */}
      <div className="card">
        <div className="card-head">
          <div>
            <h3>Counts already done</h3>
            <span className="muted small">
              What each one found, and what it was worth.
            </span>
          </div>
        </div>
        {past === null ? (
          <TableSkeleton cols={5} rows={3} />
        ) : past.length === 0 ? (
          <div className="empty">
            <b>No counts have been closed yet.</b>
            <p>Once a count is closed it stays here with what it found.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="dt">
              <thead>
                <tr>
                  <th>Reference</th><th>Status</th><th>Closed</th>
                  <th className="num">Lines</th>
                  <th className="num">Over</th>
                  <th className="num">Short</th>
                  <th className="num">Worth</th>
                </tr>
              </thead>
              <tbody>
                {past.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <EntityLink to={`/stock-takes/${t.id}`}>{t.reference}</EntityLink>
                    </td>
                    <td><span className="badge muted">{t.status}</span></td>
                    <td className="small">
                      {t.closed_at ? fmtDateTime(t.closed_at)
                                   : <span className="muted">still open</span>}
                    </td>
                    <td className="num">{t.counted_lines}</td>
                    {/* Over and short kept apart. A count 40 over and 40 short
                        nets to nothing and is not a clean count, it is two
                        errors. */}
                    <td className="num">{t.over_units || <span className="muted">none</span>}</td>
                    <td className="num">{t.short_units || <span className="muted">none</span>}</td>
                    <td className="num">
                      <span className={t.variance_value < 0 ? "neg" : undefined}>
                        {money(t.variance_value)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
