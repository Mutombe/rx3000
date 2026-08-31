/** Branches: where stock is, and moving it between them.
 *
 *  Eight endpoints, three of them uncalled and two more only ever reached
 *  indirectly. A group with stock in Harare and a patient in Bulawayo could not
 *  move a box between them, and the branch record had no screen at all — which is
 *  why `city` and `responsible_pharmacist` sat empty on every branch while both
 *  were accepted by the API.
 *
 *  The responsible pharmacist is not an optional nicety. Every branch must name
 *  the pharmacist accountable for it, and that name belongs on the branch record
 *  rather than in somebody's memory, because it is what a regulator asks for.
 *
 *  Transfers are two movements, not one. Stock leaves the sending branch when the
 *  transfer is raised and arrives when the receiving branch confirms it, and in
 *  between it is in transit and belongs to neither. That is deliberate: a box on a
 *  bus is not on either shelf, and a system that moves it instantly cannot explain
 *  the shortfall when it never turns up.
 */
import { useCallback, useEffect, useState } from "react";
import { api, errorText, fmtDate } from "../api";
import { useConfirm } from "../components/Confirm";
import { TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { Product } from "../types";
import Select from "../components/Select";
import IconButton from "../components/IconButton";
import { EntityLink } from "../components/Filters";
import { Link } from "react-router-dom";
import SectionNav from "../components/SectionNav";
import { BRANCH_TABS } from "../branchTabs";

/** A verdict, in the badge tone it deserves. Only two of the four are alarms:
 *  a shop that may not trade, and one that cannot prove it may. */
const VERDICT_TONE: Record<string, string> = {
  "cannot trade": "danger",
  "cannot be proved": "warn",
  "renewals due": "warn",
  "in order": "ok",
};

interface Standing {
  branch_id: number;
  verdict: string;
  says: string;
  next: { name: string; days: number } | null;
}

interface Branch {
  id: number; code: string; name: string; registration_no: string;
  phone: string; email: string; address: string; city: string;
  responsible_pharmacist: string; is_default: boolean; active: boolean;
}
interface StockLine {
  product_id: number; name: string; here: number; group_total: number;
  reorder_level: number; below_reorder: boolean;
}
interface BranchStock { branch_id: number; lines: StockLine[] }
/** As the server actually returns it: branch *names*, not ids, plus how long it
 *  has been in the gap. My first version of this interface invented
 *  from_branch_id/to_branch_id/created_at, and the confirmation dialog duly read
 *  "Confirms it arrived at #undefined" — the same mistake as the label field that
 *  read a `pharmacist` key nothing sends. Declaring your own interface means
 *  TypeScript cannot help. */
interface Transit {
  product_id: number;
  id: number; reference: string;
  from_branch: string; to_branch: string;
  product: string; quantity: number;
  despatched_at: string | null; days_in_transit: number;
}

export default function Branches() {
  const toast = useToast();
  const confirm = useConfirm();
  const [branches, setBranches] = useState<Branch[] | null>(null);
  const [transit, setTransit] = useState<Transit[]>([]);
  const [busy, setBusy] = useState("");

  const [viewing, setViewing] = useState<number | null>(null);
  const [stock, setStock] = useState<BranchStock | null>(null);

  const [editing, setEditing] = useState<Branch | null>(null);
  const [form, setForm] = useState<Partial<Branch>>({});

  // transfer
  const [moving, setMoving] = useState(false);
  const [fromId, setFromId] = useState<number | "">("");
  const [toId, setToId] = useState<number | "">("");
  const [productQ, setProductQ] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [notes, setNotes] = useState("");

  const load = useCallback(() => {
    api.get<Branch[]>("/api/branches")
      .then(setBranches)
      .catch((e) => toast.error(errorText(e, "The branches could not be listed.")));
    api.get<Transit[]>("/api/branches/transfers/in-transit")
      .then(setTransit).catch(() => undefined);
  }, [toast]);

  useEffect(load, [load]);

  /** Each branch's licence standing, for the column on its row.
   *
   *  One request for every branch, not one per row: this table is read by a
   *  manager comparing shops, and a query per row is the thing that makes a
   *  page slower every time the business grows.
   */
  const [standing, setStanding] = useState<Record<number, Standing>>({});
  useEffect(() => {
    let live = true;
    api.get<{ branches: Standing[] }>("/api/compliance/overview")
      .then((d) => {
        if (!live) return;
        setStanding(Object.fromEntries(d.branches.map((b) => [b.branch_id, b])));
      })
      // The column stays blank. A licence figure that cannot be fetched must
      // not take down the page somebody opened to move stock.
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (productQ.trim().length < 2) { setProducts([]); return; }
    api.get<Product[]>(`/api/products?q=${encodeURIComponent(productQ)}&limit=6`)
      .then(setProducts).catch(() => setProducts([]));
  }, [productQ]);

  const nameOf = (id: number) => branches?.find((b) => b.id === id)?.name ?? `#${id}`;

  function showStock(b: Branch) {
    if (viewing === b.id) { setViewing(null); setStock(null); return; }
    setViewing(b.id);
    setStock(null);
    api.get<BranchStock>(`/api/branches/${b.id}/stock?limit=200`)
      .then(setStock)
      .catch((e) => toast.error(errorText(e, "That branch's stock could not be read.")));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy("save");
    try {
      await api.put(`/api/branches/${editing.id}`, {
        code: form.code ?? editing.code,
        name: form.name ?? editing.name,
        registration_no: form.registration_no ?? "",
        phone: form.phone ?? "", email: form.email ?? "",
        address: form.address ?? "", city: form.city ?? "",
        responsible_pharmacist: form.responsible_pharmacist ?? "",
      });
      toast.ok(`${form.name ?? editing.name} saved.`);
      setEditing(null);
      load();
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function makeDefault(b: Branch) {
    setBusy(`default-${b.id}`);
    try {
      await api.post(`/api/branches/${b.id}/make-default`, {});
      toast.ok(`${b.name} is now the default branch.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function close(b: Branch) {
    const ok = await confirm({
      title: `Close ${b.name}?`,
      body: "A closed branch takes no more sales and cannot be the default. Its "
          + "stock and history stay exactly where they are.",
      confirmLabel: "Close the branch",
      destructive: true,
    });
    if (!ok) return;
    setBusy(`close-${b.id}`);
    try {
      await api.post(`/api/branches/${b.id}/close`, {});
      toast.ok(`${b.name} closed.`);
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function transfer(e: React.FormEvent) {
    e.preventDefault();
    if (fromId === "" || toId === "" || !product) return;
    setBusy("transfer");
    try {
      const res = await api.post<{ message?: string }>("/api/branches/transfers", {
        from_branch_id: Number(fromId), to_branch_id: Number(toId),
        product_id: product.id, quantity: Number(quantity) || 1,
        notes: notes.trim(),
      });
      toast.ok(res.message
        ?? `${quantity} × ${product.name} sent from ${nameOf(Number(fromId))} `
           + `to ${nameOf(Number(toId))}. It is in transit until received.`);
      setMoving(false);
      setProduct(null); setProductQ(""); setNotes(""); setQuantity("1");
      load();
      if (viewing) {
        api.get<BranchStock>(`/api/branches/${viewing}/stock?limit=200`)
          .then(setStock).catch(() => undefined);
      }
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setBusy("");
    }
  }

  async function receive(t: Transit) {
    const ok = await confirm({
      title: `Receive ${t.quantity} × ${t.product}?`,
      body: `Confirms it arrived at ${t.to_branch} and puts it on that `
          + `shelf. Only confirm what is physically in your hands, this is the `
          + `point at which a box that never arrived stops being invisible.`,
      confirmLabel: "Confirm it arrived",
    });
    if (!ok) return;
    setBusy(`receive-${t.id}`);
    try {
      await api.post(`/api/branches/transfers/${t.id}/receive`, {});
      toast.ok("Received into stock.");
      load();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Branches</h1>
          <div className="sub">
            Each branch, who is accountable for it, what is on its shelves, and
            stock moving between them
          </div>
        </div>
        <div className="page-actions">
          <SectionNav tabs={BRANCH_TABS} end="/branches" />
          <button className="btn primary" onClick={() => {
            setMoving(true);
            setFromId(branches?.find((b) => b.is_default)?.id ?? "");
          }}>
            Transfer stock
          </button>
        </div>
      </div>

      {transit.length > 0 && (
        <div className="card">
          <h3>In transit</h3>
          <p className="muted">
            Sent and not yet confirmed as arrived. Stock here is on neither shelf.
          </p>
          <div className="cu-scroll">
          <table>
            <thead>
              <tr>
                <th className="mono">Reference</th><th>Item</th><th className="num">Quantity</th>
                <th>From</th><th>To</th><th>Sent</th>
                <th className="num">Days out</th><th className="actions" />
              </tr>
            </thead>
            <tbody>
              {transit.map((t) => (
                <tr key={t.id} className={t.days_in_transit >= 7 ? "is-off" : ""}>
                  <td className="mono">{t.reference}</td>
                  <td>
                    <EntityLink kind="product" id={t.product_id}>
                      <span className="clip" title={t.product}>{t.product}</span>
                    </EntityLink>
                  </td>
                  <td className="num">{t.quantity}</td>
                  <td><span className="clip" title={t.from_branch}>{t.from_branch}</span></td>
                  <td><span className="clip" title={t.to_branch}>{t.to_branch}</span></td>
                  <td className="muted">
                    {t.despatched_at ? fmtDate(t.despatched_at) : "—"}
                  </td>
                  {/* A week on a bus is stock nobody has. Flagged, because the
                      alternative is finding it at the next stock take. */}
                  <td className={`num${t.days_in_transit >= 7 ? " cu-diff" : ""}`}>
                    {t.days_in_transit}
                  </td>
                  <td className="num lb-actions">
                    <button className="small" disabled={busy === `receive-${t.id}`}
                      onClick={() => receive(t)}>
                      {busy === `receive-${t.id}` ? "Receiving…" : "Confirm arrival"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      <div className="card">
        <h3>Branches</h3>
        {!branches ? <TableSkeleton cols={5} rows={4} /> : (
          <div className="cu-scroll">
            <table>
              <thead>
                <tr>
                  <th>Code</th><th>Branch</th><th>City</th>
                  <th>Responsible pharmacist</th><th>Registration</th>
                  {/* Whether the shop may lawfully open. It was three sections
                      away under its own sidebar entry, so a manager reading
                      this table had no way to know that the branch on row two
                      has no premises licence on file. */}
                  <th>Licences</th><th className="actions" />
                </tr>
              </thead>
              <tbody>
                {branches.map((b) => (
                  <tr key={b.id} className={b.active ? "" : "is-off"}>
                    <td className="mono">{b.code}</td>
                    <td>
                      <b>{b.name}</b>
                      {b.is_default && <span className="badge ok">default</span>}
                      {!b.active && <span className="badge muted">closed</span>}
                    </td>
                    <td><span className="clip" title={b.city}>
                      {b.city || <span className="muted">—</span>}</span></td>
                    <td>
                      {/* Empty is worth pointing at rather than leaving blank: a
                          branch with nobody named is a compliance gap, not a
                          missing nicety. */}
                      <span className="clip" title={b.responsible_pharmacist}>
                        {b.responsible_pharmacist || (
                          <span className="cu-diff">nobody named</span>
                        )}
                      </span>
                    </td>
                    <td className="mono muted">{b.registration_no || "—"}</td>
                    <td>
                      {/* The one figure that decides whether the shop opens,
                          linked to the register that explains it. Silent while
                          it loads rather than showing a reassuring dash: a
                          blank that means "not known yet" and a blank that
                          means "nothing wrong" must not look the same on a
                          compliance column. */}
                      {standing[b.id] ? (
                        <Link to={`/compliance?branch=${b.id}`}
                              className="lic-cell"
                              title={standing[b.id]!.says}>
                          <span className={`badge ${
                            VERDICT_TONE[standing[b.id]!.verdict] ?? "muted"}`}>
                            {standing[b.id]!.verdict}
                          </span>
                          {standing[b.id]!.next && (
                            <span className="muted small">
                              {standing[b.id]!.next!.name} in{" "}
                              {standing[b.id]!.next!.days} days
                            </span>
                          )}
                        </Link>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td className="num lb-actions">
                      <button className="small ghost" onClick={() => showStock(b)}>
                        {viewing === b.id ? "Hide stock" : "Stock"}
                      </button>
                      <IconButton action="edit" title="Edit this branch" onClick={() => {
                        setEditing(b); setForm({ ...b });
                      }} />
                      {b.active && !b.is_default && (
                        <>
                          <button className="small ghost" disabled={busy === `default-${b.id}`}
                            onClick={() => makeDefault(b)}>
                            Make default
                          </button>
                          <button className="small ghost" disabled={busy === `close-${b.id}`}
                            onClick={() => close(b)}>
                            Close
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {viewing !== null && (
        <div className="card">
          <h3>Stock at {nameOf(viewing)}</h3>
          {stock && stock.lines.length >= 200 && (
            <p className="muted small">
              The first 200 lines. This is a shelf list, not a stock report, use
              Analytics for the whole branch.
            </p>
          )}
          {!stock ? <TableSkeleton cols={4} rows={5} /> : stock.lines.length === 0 ? (
            <div className="empty">Nothing on this branch's shelves.</div>
          ) : (
            <div className="cu-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Product</th><th className="num">Here</th>
                    <th className="num">Group total</th><th className="num">Reorder at</th>
                  </tr>
                </thead>
                <tbody>
                  {stock.lines.map((l) => (
                    <tr key={l.product_id} className={l.below_reorder ? "is-off" : ""}>
                      <td><span className="clip" title={l.name}>{l.name}</span></td>
                      <td className={`num${l.below_reorder ? " cu-diff" : ""}`}>{l.here}</td>
                      {/* The group total answers the question a branch actually
                          asks when it runs low: is there any elsewhere? */}
                      <td className="num muted">{l.group_total}</td>
                      <td className="num muted">{l.reorder_level}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {editing && (
        <div className="modal-backdrop" onClick={() => setEditing(null)}>
          <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
            <h2>{editing.name}</h2>
            <div className="form-row">
              <div className="field">
                <label>Code</label>
                <input value={form.code ?? ""}
                  onChange={(e) => setForm({ ...form, code: e.target.value })} required />
              </div>
              <div className="field">
                <label>Name</label>
                <input value={form.name ?? ""}
                  onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>City</label>
                <input value={form.city ?? ""}
                  onChange={(e) => setForm({ ...form, city: e.target.value })} />
              </div>
              <div className="field">
                <label>Registration number</label>
                <input value={form.registration_no ?? ""}
                  onChange={(e) => setForm({ ...form, registration_no: e.target.value })} />
              </div>
            </div>
            <label>
              Responsible pharmacist
              <input value={form.responsible_pharmacist ?? ""}
                onChange={(e) => setForm({ ...form, responsible_pharmacist: e.target.value })}
                placeholder="The pharmacist accountable for this branch" />
            </label>
            <div className="form-row">
              <div className="field">
                <label>Phone</label>
                <input value={form.phone ?? ""}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div className="field">
                <label>Email</label>
                <input value={form.email ?? ""}
                  onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
            </div>
            <label>
              Address
              <textarea rows={2} value={form.address ?? ""}
                onChange={(e) => setForm({ ...form, address: e.target.value })} />
            </label>
            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="submit" className="btn primary" disabled={busy === "save"}>
                {busy === "save" ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}

      {moving && branches && (
        <div className="modal-backdrop" onClick={() => setMoving(false)}>
          <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={transfer}>
            <h2>Transfer stock</h2>
            <p className="muted">
              Leaves the sending branch now and arrives when the receiving branch
              confirms it. Until then it is in transit and on neither shelf.
            </p>
            <div className="form-row">
              <div className="field">
                <label>From</label>
                <Select
                  value={String(fromId ?? "")}
                  onChange={(__value) => setFromId(__value === "" ? "" : Number(__value))}
                  options={[{ value: "", label: "Choose…" }, ...branches.filter((b) => b.active).map((b) => ({ value: String(b.id), label: b.name }))]}
                />
              </div>
              <div className="field">
                <label>To</label>
                <Select
                  value={String(toId ?? "")}
                  onChange={(__value) => setToId(__value === "" ? "" : Number(__value))}
                  options={[{ value: "", label: "Choose…" }, ...branches.filter((b) => b.active && b.id !== fromId).map((b) => ({ value: String(b.id), label: b.name }))]}
                />
              </div>
            </div>

            <label>
              Product
              {product ? (
                <div className="st-picked">
                  <b>{product.name}</b>
                  <button type="button" className="btn ghost small"
                    onClick={() => { setProduct(null); setProductQ(""); }}>Change</button>
                </div>
              ) : (
                <input value={productQ} onChange={(e) => setProductQ(e.target.value)}
                  placeholder="Search for a product" />
              )}
            </label>
            {!product && products.length > 0 && (
              <ul className="st-results">
                {products.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => { setProduct(p); setProducts([]); }}>
                      {p.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="form-row">
              <div className="field">
                <label>Quantity</label>
                <input type="number" min="1" step="1" value={quantity}
                  onChange={(e) => setQuantity(e.target.value)} />
              </div>
              <div className="field">
                <label>Notes</label>
                <input value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="e.g. sent with the Friday driver" />
              </div>
            </div>

            <div className="modal-actions">
              <button type="button" className="btn ghost" onClick={() => setMoving(false)}>
                Cancel
              </button>
              <button type="submit" className="btn primary"
                disabled={busy === "transfer" || !product || fromId === "" || toId === ""}>
                {busy === "transfer" ? "Sending…" : "Send it"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
