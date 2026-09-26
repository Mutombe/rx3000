/** The wholesalers, and the ability to keep them right.
 *
 *  There was no supplier list. `POST`, `PUT` and `DELETE /suppliers` had all
 *  existed for some time with no caller anywhere, so a supplier could be
 *  reached only by following a link from an order, and could not be created,
 *  corrected or retired from the product at all. Adding one meant a developer.
 *
 *  THE BANK ACCOUNT IS THE POINT
 *
 *  The endpoint that updates a supplier carries a comment saying why: "a
 *  wholesaler changes its bank account, which they do, and which is exactly
 *  the message a fraudster imitates". The field was accepted on the way in and
 *  never returned, so a pharmacy could record the new number and had no way to
 *  read it back and check it — which is the whole reason for recording it. It
 *  is shown here, and changing it is deliberately a little louder than
 *  changing a phone number.
 *
 *  RETIRED, NEVER DELETED. Their name is on every order they ever filled, and
 *  the server refuses to retire one that is still owed money: a creditor that
 *  stops appearing on the ageing is a debt nobody pays.
 */
import { useEffect, useMemo, useState } from "react";
import { Plus, Warning } from "@phosphor-icons/react";

import { api, errorText } from "../api";
import { useConfirm } from "../components/Confirm";
import Checkbox from "../components/Checkbox";
import { EntityLink, FilterToggle } from "../components/Filters";
import { Refreshable, TableSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import BusyButton from "../components/BusyButton";
import { useOptimisticList, rowClass } from "../hooks/useOptimisticList";
import Person from "../components/Person";
import PageHead from "../components/PageHead";
import ExportButton from "../components/ExportButton";
import Th from "../components/Th";

interface Supplier {
  id: number;
  name: string;
  contact_person: string;
  phone: string;
  email: string;
  account_number: string;
  payment_terms: string;
  notes: string;
  active: boolean;
}

/** How a wholesaler has actually behaved, from the buying record. Loaded
 *  apart from the list on purpose: it is the more expensive query of the two,
 *  and a supplier list that will not open because a performance figure could
 *  not be worked out is a worse list than one without the figure. */
interface Behaviour {
  supplier_id: number;
  fill_rate: number | null;
  short_orders: number;
  avg_days: number | null;
  orders: number;
  units_outstanding: number;
  spend: number;
  delivers: boolean;
  few_orders: boolean;
}

const BLANK = {
  name: "", contact_person: "", phone: "", email: "",
  account_number: "", payment_terms: "", notes: "",
};

export default function Suppliers() {
  const toast = useToast();
  const confirm = useConfirm();
  const [q, setQ] = useState("");
  const [showRetired, setShowRetired] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);

  const list = useOptimisticList<Supplier>({
    load: () => api.get<Supplier[]>("/api/suppliers"),
    key: (s) => s.id,
  });

  const reload = list.reload;

  const [records, setRecords] = useState<Record<number, Behaviour> | null>(null);
  useEffect(() => {
    api.get<{ suppliers: Behaviour[] }>("/api/suppliers/league")
      .then((r) => setRecords(Object.fromEntries(
        r.suppliers.map((s) => [s.supplier_id, s]))))
      // Deliberately quiet, and the column says "not known" rather than
      // going blank: the list itself is unaffected and a toast about a
      // figure nobody asked for is noise on a screen somebody opened to
      // change a phone number.
      .catch(() => setRecords({}));
  }, []);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return list.items.filter((s) => {
      if (!showRetired && s.active === false) return false;
      if (!needle) return true;
      return [s.name, s.contact_person, s.phone, s.email, s.account_number]
        .some((v) => (v || "").toLowerCase().includes(needle));
    });
  }, [list.items, q, showRetired]);

  async function retire(s: Supplier) {
    const ok = await confirm({
      title: `Retire ${s.name}?`,
      body: "They stay on every order they ever filled. They simply stop being "
          + "offered when a new order is raised. The server refuses this while "
          + "they are still owed money.",
      confirmLabel: "Retire them",
    });
    if (!ok) return;
    await list.update(
      s.id, { active: false } as Partial<Supplier>,
      () => api.delete(`/api/suppliers/${s.id}`),
      `${s.name} retired.`);
  }

  async function restore(s: Supplier) {
    await list.update(
      s.id, { active: true } as Partial<Supplier>,
      () => api.put(`/api/suppliers/${s.id}`, { active: true }),
      `${s.name} is back on the list.`);
  }

  return (
    <>
      <PageHead
        title="Suppliers"
        sub="Who this pharmacy buys from, and how they are paid"
        // Account numbers and terms, which is what a bookkeeper setting up
        // payments asks for and what a new branch is opened with.
        take={<ExportButton dataset="suppliers" />}
        primary={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={14} weight="bold" /> New supplier
          </button>
        }
      />

      <div className="card">
        <div className="toolbar">
          <input type="search" value={q} placeholder="Name, contact, phone or account…"
                 onChange={(e) => setQ(e.target.value)} />
          <FilterToggle checked={showRetired} onChange={setShowRetired}
                        hint="Include wholesalers this pharmacy no longer buys from">
            Show retired
          </FilterToggle>
        </div>

        <Refreshable loading={list.loading} hasData={list.items.length > 0}
                     skeleton={<TableSkeleton cols={5} rows={8} />}>
          {shown.length === 0 ? (
            <div className="empty">
              <b>No supplier matches that.</b>
              <p>Every wholesaler this pharmacy orders from should be here.</p>
            </div>
          ) : (
            <div className="table-wrap">
              {/* Widths given rather than left to the browser. Shared out by
                  content the contact column lost to two columns that are
                  mostly empty, and the email clipped mid-word with no
                  ellipsis — which reads as a rendering fault rather than as
                  a long address. */}
              <table className="dt sup-table">
                <thead>
                  <tr>
                    <Th className="sup-col-who">Supplier</Th><Th className="sup-col-contact">Contact</Th>
                    {/* The column a buyer renewing terms argues from. It was
                        in the purchase orders all along and had no screen. */}
                    <Th className="sup-col-arrive">How they arrive</Th>
                    <Th className="sup-col-paid">Paid to</Th>
                    <Th className="sup-col-terms">Terms</Th><th className="actions" />
                  </tr>
                </thead>
                <tbody>
                  {shown.map((s) => (
                    <tr key={s.id}
                        className={[s.active === false ? "is-muted" : "",
                                    rowClass(list.stateOf(s))]
                          .filter(Boolean).join(" ") || undefined}>
                      <td>
                        <EntityLink to={`/suppliers/${s.id}`}>{s.name}</EntityLink>
                        {s.active === false && <span className="badge">Retired</span>}
                        {s.notes && <div className="muted small wrap">{s.notes}</div>}
                      </td>
                      <td>
                        <Person name={s.contact_person} absent="Nobody named"
                                meta={s.phone || undefined} />
                        {/* Truncated with an ellipsis and its full value on
                            hover: an address that simply stops mid-word looks
                            broken, and one that wraps to three lines pushes
                            every row apart. */}
                        {s.email && (
                          <div className="muted small sup-email" title={s.email}>
                            {s.email}
                          </div>
                        )}
                      </td>
                      <td>
                        <SupplierRecord record={records?.[s.id]}
                                        loading={records === null} />
                      </td>
                      {/* The bank account, readable at last. A payment made
                          against a stale number is not a data-entry problem. */}
                      <td className="mono small">
                        {s.account_number || <span className="muted">Not recorded</span>}
                      </td>
                      <td className="small">
                        {s.payment_terms || <span className="muted">None agreed</span>}
                      </td>
                      <td className="actions">
                        <button className="btn ghost small"
                                disabled={list.isPending(s)}
                                onClick={() => setEditing(s)}>
                          Edit
                        </button>
                        {s.active === false ? (
                          <button className="btn ghost small"
                                  disabled={list.isPending(s)}
                                  onClick={() => void restore(s)}>
                            Restore
                          </button>
                        ) : (
                          <button className="btn ghost small"
                                  disabled={list.isPending(s)}
                                  onClick={() => void retire(s)}>
                            Retire
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Refreshable>
      </div>

      {(adding || editing) && (
        <SupplierForm
          supplier={editing}
          onClose={() => { setAdding(false); setEditing(null); }}
          onSaved={() => { setAdding(false); setEditing(null); void reload(); }}
        />
      )}
    </>
  );
}

/** Add or correct one supplier. */
function SupplierForm({ supplier, onClose, onSaved }: {
  supplier: Supplier | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState(() => supplier
    ? { name: supplier.name, contact_person: supplier.contact_person,
        phone: supplier.phone, email: supplier.email,
        account_number: supplier.account_number,
        payment_terms: supplier.payment_terms, notes: supplier.notes }
    : { ...BLANK });

  const set = (k: keyof typeof form) => (v: string) =>
    setForm((f) => ({ ...f, [k]: v }));

  /* Changing a bank account is the one field worth a second look. The reason
     is in the endpoint's own comment: it is precisely the change a fraudster
     imitates, and the pharmacy pays whatever number is on file. */
  const accountChanged = Boolean(
    supplier && form.account_number.trim() !== (supplier.account_number || "").trim());

  async function save() {
    const name = form.name.trim();
    if (name.length < 2) {
      toast.error("A supplier needs a name. It is on every order they send.");
      return;
    }
    try {
      if (supplier) {
        await api.put(`/api/suppliers/${supplier.id}`, { ...form, name });
        toast.ok(`${name} updated.`);
      } else {
        await api.post("/api/suppliers", { ...form, name });
        toast.ok(`${name} added.`);
      }
      onSaved();
    } catch (e) {
      toast.error(errorText(e, "That supplier could not be saved."));
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{supplier ? supplier.name : "New supplier"}</h2>
        <p className="muted">
          Who they are, and where their money goes.
        </p>

        <div className="form-row">
          <div className="field span-7">
            <label htmlFor="sup-name">Name</label>
            <input id="sup-name" value={form.name} autoFocus maxLength={160}
                   onChange={(e) => set("name")(e.target.value)}
                   placeholder="e.g. Pharmanova" />
          </div>
          <div className="field span-5">
            <label htmlFor="sup-contact">Contact</label>
            <input id="sup-contact" value={form.contact_person} maxLength={120}
                   onChange={(e) => set("contact_person")(e.target.value)}
                   placeholder="who to ring" />
          </div>
        </div>

        <div className="form-row">
          <div className="field span-6">
            <label htmlFor="sup-phone">Phone</label>
            <input id="sup-phone" value={form.phone} maxLength={30}
                   onChange={(e) => set("phone")(e.target.value)} />
          </div>
          <div className="field span-6">
            <label htmlFor="sup-email">Email</label>
            <input id="sup-email" value={form.email} maxLength={120}
                   onChange={(e) => set("email")(e.target.value)} />
          </div>
        </div>

        <div className="form-row">
          <div className="field span-7">
            <label htmlFor="sup-account">Bank account</label>
            <input id="sup-account" className="mono" value={form.account_number}
                   maxLength={60}
                   onChange={(e) => set("account_number")(e.target.value)}
                   placeholder="the account payments go to" />
            <span className="hint">
              Every payment goes here. Check a change against something other
              than the message that asked for it.
            </span>
          </div>
          <div className="field span-5">
            <label htmlFor="sup-terms">Payment terms</label>
            <input id="sup-terms" value={form.payment_terms} maxLength={60}
                   onChange={(e) => set("payment_terms")(e.target.value)}
                   placeholder="e.g. 30 days" />
          </div>
        </div>

        {accountChanged && (
          <div className="alert warn">
            <Warning size={15} weight="fill" /> You are changing where{" "}
            {supplier?.name} gets paid. A wholesaler really does change its bank
            account, and it is also exactly the message a fraudster sends.
            Confirm it by ringing the number you already had, not one in the
            message.
          </div>
        )}

        <div className="field">
          <label htmlFor="sup-notes">Notes <span className="muted">optional</span></label>
          <input id="sup-notes" value={form.notes} maxLength={400}
                 onChange={(e) => set("notes")(e.target.value)}
                 placeholder="delivery days, minimum order, anything worth knowing" />
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Cancel</button>
          <BusyButton className="btn primary" onClick={save}
                      disabled={form.name.trim().length < 2}
                      busyLabel="Saving…">
            {supplier ? "Save" : "Add supplier"}
          </BusyButton>
        </div>
      </div>
    </div>
  );
}

/** One wholesaler's delivery record, in the width of a table cell.
 *
 *  Two facts and no score: what arrived of what was asked for, and how long
 *  it took. See services/supplier_record for why there is no number out of
 *  five, and why a blended one would be worse than either fact alone.
 */
function SupplierRecord({ record, loading }: {
  record: Behaviour | undefined;
  loading: boolean;
}) {
  if (loading) return <span className="muted small">…</span>;
  if (!record || !record.orders) {
    return <span className="muted small">Never ordered from</span>;
  }
  // Waiting on them is not failing. An order still in transit used to drag
  // this to a red "0% arrives", which branded most of the supplier list as
  // total failures on the strength of having ordered from them yesterday.
  if (record.fill_rate === null) {
    // Longer than the column, and a sentence rather than a figure: shortened
    // with the whole of it on the hover, which is a shortened cell rather than
    // text that stops mid word.
    const said = record.units_outstanding
      ? `${record.units_outstanding} unit(s) still to come`
      : `${record.orders} order(s), none delivered yet`;
    return <span className="muted small clip" title={said}>{said}</span>;
  }
  return (
    <div className="sup-record">
      <span className={`badge ${record.delivers ? "ok" : "bad"}`}>
        {Math.round(record.fill_rate * 100)}% arrives
      </span>
      <span className="muted small">
        {[
          record.avg_days !== null ? `${record.avg_days} days` : "",
          record.short_orders ? `${record.short_orders} short` : "",
          record.few_orders ? `${record.orders} order(s) only` : "",
        ].filter(Boolean).join(" · ")}
      </span>
    </div>
  );
}
